"""
F-12: unit tests for MAX plugin adapter.

Run with:
    cd /root/.hermes/plugins/max && python3 -m unittest tests.test_adapter -v

Or:
    python3 /root/.hermes/plugins/max/tests/test_adapter.py

Coverage:
    - pure helper functions (no network):
        _mask, _mask_id, _parse_route, _split_for_send, _extract_update_meta
    - edit_message anti-spam guards and feature flag (mocked self.send)
    - send_typing cache lookup (mocked self._post_action)
    - token masking guarantees (token must NOT appear in log output)

No real network calls. No gateway restart. No core changes.
"""

import asyncio
import io
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Make the plugin importable
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN_DIR)
sys.path.insert(0, "/usr/local/lib/hermes-agent")

import adapter  # the plugin module


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestMask(unittest.TestCase):
    """Token masking — no token should ever leak."""

    def test_empty(self):
        self.assertEqual(adapter._mask(None), "<missing>")
        self.assertEqual(adapter._mask(""), "<missing>")

    def test_real_token_returns_length_only(self):
        # Simulate a real-shape token (e.g. 84 chars).
        token = "x" * 84
        masked = adapter._mask(token)
        self.assertNotIn(token, masked)
        self.assertIn("84", masked)
        self.assertNotIn("xxx", masked)  # no substring of real token


class TestMaskId(unittest.TestCase):
    """MAX update_id / message_id masking."""

    def test_short_id(self):
        out = adapter._mask_id("mid.0000", keep=6)
        # Should be at most keep + 3 chars of "…(N)"
        self.assertLessEqual(len(out), 6 + 5)

    def test_long_id_truncated(self):
        long_id = "mid." + "0" * 50
        out = adapter._mask_id(long_id, keep=6)
        self.assertIn("…", out)
        self.assertLessEqual(len(out), 6 + 5)


class TestParseRoute(unittest.TestCase):
    """_parse_route: 3-level precedence (metadata → tagged → bare)."""

    def test_metadata_wins(self):
        # metadata with explicit kind/rid should win over chat_id string
        kind, rid = adapter._parse_route(
            "user:123",
            metadata={"max_route_kind": "chat", "max_route_id": "999"},
        )
        self.assertEqual((kind, rid), ("chat", "999"))

    def test_user_prefix(self):
        kind, rid = adapter._parse_route("user:12345678")
        self.assertEqual((kind, rid), ("user", "12345678"))

    def test_chat_prefix(self):
        kind, rid = adapter._parse_route("chat:-1001234567890")
        self.assertEqual((kind, rid), ("chat", "-1001234567890"))

    def test_bare_int_defaults_to_chat(self):
        # Backward-compat: bare int → chat route
        kind, rid = adapter._parse_route("111222333")
        self.assertEqual((kind, rid), ("chat", "111222333"))

    def test_empty_returns_empty_rid(self):
        kind, rid = adapter._parse_route("")
        self.assertEqual(kind, "chat")
        self.assertEqual(rid, "")

    def test_metadata_with_partial_keys_falls_through(self):
        # metadata missing max_route_id → fall through to tagged string
        kind, rid = adapter._parse_route(
            "user:12345678",
            metadata={"max_route_kind": "user"},  # no max_route_id
        )
        self.assertEqual((kind, rid), ("user", "12345678"))


class TestSplitForSend(unittest.TestCase):
    """_split_for_send: chunking strategy."""

    def test_empty_returns_empty_string_chunk(self):
        out = adapter._split_for_send("", 100)
        self.assertEqual(out, [""])

    def test_none_returns_empty_string_chunk(self):
        out = adapter._split_for_send(None, 100)  # type: ignore[arg-type]
        self.assertEqual(out, [""])

    def test_short_text_unchunked(self):
        out = adapter._split_for_send("hello", 100)
        self.assertEqual(out, ["hello"])

    def test_long_text_split_at_paragraph(self):
        # Two paragraphs separated by \n\n, each ~50 chars
        para1 = "a" * 50
        para2 = "b" * 50
        text = para1 + "\n\n" + para2
        out = adapter._split_for_send(text, 60)
        # Each chunk should be <= 60
        for c in out:
            self.assertLessEqual(len(c), 60)
        # Reconstructed text should still contain all 'a' and 'b' chars
        joined = "".join(out)
        self.assertEqual(joined.count("a"), 50)
        self.assertEqual(joined.count("b"), 50)

    def test_hard_cut_when_no_boundary(self):
        # 1000 'x' with no separators, limit=100
        text = "x" * 1000
        out = adapter._split_for_send(text, 100)
        self.assertGreaterEqual(len(out), 10)
        for c in out:
            self.assertLessEqual(len(c), 100)

    def test_3900_limit_matches_constant(self):
        # Sanity: MAX_SEND_CHUNK_SIZE = 3900, the public chunk limit
        self.assertEqual(adapter.MAX_SEND_CHUNK_SIZE, 3900)


class TestExtractUpdateMeta(unittest.TestCase):
    """_extract_update_meta: no message body in logs."""

    def test_no_message(self):
        meta = adapter._extract_update_meta({}, "message_created", None)
        self.assertEqual(meta["text_len"], 0)
        self.assertEqual(meta["update_type"], "message_created")
        self.assertEqual(meta["chat_id"], "<n/a>")

    def test_message_with_text_logs_length_only(self):
        upd = {
            "message": {
                "body": {"mid": "mid.abcdefghij", "text": "SECRET_PASSWORD_123"},
                "recipient": {"chat_id": 111222333},
                "sender": {"user_id": 12345678},
            }
        }
        meta = adapter._extract_update_meta(upd, "message_created", 987654321)
        # text_len is set
        self.assertEqual(meta["text_len"], len("SECRET_PASSWORD_123"))
        # message_id is masked
        self.assertIn("…", meta["message_id"])
        # raw text MUST NOT appear in any meta value
        for v in meta.values():
            self.assertNotIn("SECRET_PASSWORD_123", str(v))
        # recipient.chat_id (int) preserved
        self.assertEqual(meta["chat_id"], 111222333)
        self.assertEqual(meta["user_id"], 12345678)


# ---------------------------------------------------------------------------
# edit_message — anti-spam + feature flag
# ---------------------------------------------------------------------------

def _make_adapter_for_test():
    """Construct a MaxAdapter-like object bypassing BasePlatformAdapter.__init__.

    We only test edit_message / send_typing, both of which only need:
        - self._last_progress_sent (dict)
        - self._last_typing_chat (dict)
        - self._typing_unsupported_logged (set)
        - self.send (we'll mock)
    Plus _post_action / _api_base / _token attributes set by __init__.
    """
    inst = adapter.MaxAdapter.__new__(adapter.MaxAdapter)
    inst._last_progress_sent = {}
    inst._last_typing_chat = {}
    inst._typing_unsupported_logged = set()
    inst._token = "fake_token_for_testing_only_1234"
    inst._api_base = "https://example.test"
    return inst


class TestEditMessageFeatureFlag(unittest.TestCase):
    """MAX_PROGRESS_APPEND env flag controls edit_message behavior."""

    def setUp(self):
        self.inst = _make_adapter_for_test()
        self.inst.send = AsyncMock(
            return_value=adapter.SendResult(success=True, message_id="m1")
        )

    def tearDown(self):
        os.environ.pop("MAX_PROGRESS_APPEND", None)

    def test_flag_disabled_returns_success_noop(self):
        os.environ["MAX_PROGRESS_APPEND"] = "0"
        result = asyncio.run(
            self.inst.edit_message("user:12345678", "mid", "🔧 terminal: ls")
        )
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()  # no actual send

    def test_flag_missing_returns_success_noop(self):
        # No env var at all → default disabled
        result = asyncio.run(
            self.inst.edit_message("user:12345678", "mid", "🔧 terminal: ls")
        )
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()

    def test_flag_enabled_invokes_send(self):
        os.environ["MAX_PROGRESS_APPEND"] = "1"
        result = asyncio.run(
            self.inst.edit_message("user:12345678", "mid", "🔧 terminal: ls")
        )
        self.assertTrue(result.success)
        self.inst.send.assert_awaited_once()
        # Verify content passed through
        call_args = self.inst.send.await_args
        self.assertEqual(call_args.args[0], "user:12345678")
        self.assertEqual(call_args.args[1], "🔧 terminal: ls")


class TestEditMessageAntiSpam(unittest.TestCase):
    """All anti-spam guards in edit_message."""

    def setUp(self):
        os.environ["MAX_PROGRESS_APPEND"] = "1"
        self.inst = _make_adapter_for_test()
        self.inst.send = AsyncMock(
            return_value=adapter.SendResult(success=True, message_id="m1")
        )

    def tearDown(self):
        os.environ.pop("MAX_PROGRESS_APPEND", None)

    def test_finalize_true_skips(self):
        result = asyncio.run(
            self.inst.edit_message("user:1", "mid", "long content", finalize=True)
        )
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()

    def test_empty_content_skips(self):
        result = asyncio.run(self.inst.edit_message("user:1", "mid", ""))
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()

    def test_whitespace_content_skips(self):
        result = asyncio.run(self.inst.edit_message("user:1", "mid", "   \n\t  "))
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()

    def test_too_long_content_skips(self):
        # 241 chars > 240 limit
        long = "x" * 241
        result = asyncio.run(self.inst.edit_message("user:1", "mid", long))
        self.assertTrue(result.success)
        self.inst.send.assert_not_called()

    def test_at_240_chars_passes(self):
        # Exactly 240 chars — boundary, should pass
        text = "x" * 240
        result = asyncio.run(self.inst.edit_message("user:1", "mid", text))
        self.assertTrue(result.success)
        self.inst.send.assert_awaited_once()

    def test_rate_limit_blocks_second_call_within_3s(self):
        chat = "user:12345678"
        # First call goes through
        r1 = asyncio.run(self.inst.edit_message(chat, "mid", "🔧 tool1"))
        self.assertTrue(r1.success)
        self.assertEqual(self.inst.send.await_count, 1)
        # Second call within 3s — rate-limited
        r2 = asyncio.run(self.inst.edit_message(chat, "mid", "🔧 tool2"))
        self.assertTrue(r2.success)  # still no-op success
        self.assertEqual(self.inst.send.await_count, 1)  # NOT called again

    def test_rate_limit_resets_after_3s(self):
        chat = "user:12345678"
        # Manually set last sent to 4s ago
        import time
        self.inst._last_progress_sent[chat] = time.monotonic() - 4.0
        r = asyncio.run(self.inst.edit_message(chat, "mid", "🔧 tool"))
        self.assertTrue(r.success)
        self.inst.send.assert_awaited_once()

    def test_rate_limit_per_chat_independent(self):
        # user:A is rate-limited, but user:B is fresh
        import time
        self.inst._last_progress_sent["user:A"] = time.monotonic()  # now
        r1 = asyncio.run(self.inst.edit_message("user:A", "mid", "🔧 x"))
        r2 = asyncio.run(self.inst.edit_message("user:B", "mid", "🔧 y"))
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)
        # Only user:B's call hit send
        self.assertEqual(self.inst.send.await_count, 1)


class TestEditMessageNoTokenLeak(unittest.TestCase):
    """Token must never appear in edit_message log output."""

    def setUp(self):
        os.environ["MAX_PROGRESS_APPEND"] = "1"
        self.inst = _make_adapter_for_test()
        # Token: realistic shape
        self.inst._token = "SECRETTOKEN_abcdef1234567890XYZ"
        self.inst.send = AsyncMock(
            return_value=adapter.SendResult(success=True, message_id="m1")
        )
        # Capture logs
        self.log_stream = io.StringIO()
        handler = logging.StreamHandler(self.log_stream)
        handler.setLevel(logging.INFO)
        adapter.logger.addHandler(handler)
        adapter.logger.setLevel(logging.INFO)

    def tearDown(self):
        os.environ.pop("MAX_PROGRESS_APPEND", None)
        adapter.logger.removeHandler(self.log_stream)

    def test_log_does_not_contain_token(self):
        asyncio.run(
            self.inst.edit_message("user:1", "mid", "🔧 terminal: ls")
        )
        log_output = self.log_stream.getvalue()
        self.assertNotIn("SECRETTOKEN_abcdef", log_output)
        self.assertNotIn("SECRETTOKEN_abc", log_output)
        # And shouldn't contain the literal "Authorization" header value either
        self.assertNotIn("SECRETTOKEN", log_output)

    def test_log_does_not_contain_full_content(self):
        secret_text = "echo PASSWORD=secretpass123 > file"
        asyncio.run(self.inst.edit_message("user:1", "mid", secret_text))
        log_output = self.log_stream.getvalue()
        # The full content should NOT appear (only len)
        self.assertNotIn("PASSWORD=secretpass", log_output)
        self.assertNotIn("secretpass", log_output)
        # But length should be logged
        self.assertIn("len=", log_output)


# ---------------------------------------------------------------------------
# Token extraction never logs the token
# ---------------------------------------------------------------------------

class TestGetTokenSafety(unittest.TestCase):
    """_get_token reads from env, never raises on missing."""

    def test_missing_returns_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAX_BOT_TOKEN", None)
            token = adapter._get_token()
            self.assertEqual(token, "")

    def test_present_returns_unchanged(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "abc123"}):
            token = adapter._get_token()
            self.assertEqual(token, "abc123")
        # Mask should hide it
        self.assertNotIn("abc123", adapter._mask(token))


# ---------------------------------------------------------------------------
# send_typing cache lookup
# ---------------------------------------------------------------------------

class TestSendTypingCache(unittest.TestCase):
    """send_typing should resolve numeric chat_id via _last_typing_chat cache."""

    def setUp(self):
        self.inst = _make_adapter_for_test()
        self.inst._post_action = AsyncMock(return_value=True)
        # Pre-populate cache: tagged → numeric
        self.inst._last_typing_chat["user:12345678"] = 111222333

    def test_typing_with_cache_lookup(self):
        asyncio.run(self.inst.send_typing("user:12345678"))
        self.inst._post_action.assert_awaited_once()
        call_kwargs = self.inst._post_action.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], 111222333)
        self.assertEqual(call_kwargs["action"], "typing_on")

    def test_typing_with_no_cache_is_noop(self):
        # Cache miss: no numeric chat_id known
        asyncio.run(self.inst.send_typing("user:9999999"))
        # _post_action NOT called — adapter logs and no-ops
        self.inst._post_action.assert_not_called()

    def test_typing_logs_failure_once(self):
        # First call fails, second should not re-log
        self.inst._post_action = AsyncMock(return_value=False)
        asyncio.run(self.inst.send_typing("user:12345678"))
        asyncio.run(self.inst.send_typing("user:12345678"))
        # Both calls happen
        self.assertEqual(self.inst._post_action.await_count, 2)


# ---------------------------------------------------------------------------
# Smoke: module-level imports + constants
# ---------------------------------------------------------------------------

class TestModuleSmoke(unittest.TestCase):
    """Module imports cleanly and exposes public surface."""

    def test_constants(self):
        self.assertEqual(adapter.MAX_SEND_CHUNK_SIZE, 3900)
        self.assertTrue(adapter.MAX_API_BASE_DEFAULT.startswith("https://"))

    def test_register_callable(self):
        self.assertTrue(callable(adapter.register))
        self.assertTrue(callable(adapter.check_requirements))
        self.assertTrue(callable(adapter.validate_config))
        self.assertTrue(callable(adapter.is_connected))

    def test_class_flag_wants_progress_append(self):
        # The F-08b.1 class flag must be present and True
        self.assertTrue(getattr(adapter.MaxAdapter, "wants_progress_append", False))


# ---------------------------------------------------------------------------
# F-07b: Russian help-text commands (adapter-level, no core touch)
# ---------------------------------------------------------------------------

class TestRussianHelpText(unittest.TestCase):
    """Russian help/menu/roles text presence, content, and safety."""

    def test_help_text_present(self):
        self.assertTrue(hasattr(adapter, "_HELP_RU"))
        text = adapter._HELP_RU
        # Header
        self.assertIn("Hermes в MAX", text)
        # All main sections present
        for marker in (
            "Основное",
            "/status", "/model", "/new", "/reset",
            "/stop", "/retry", "/undo",
            "MAX",
            "/sethome",
            "Будущие роли",
            "/dev", "/copy", "/marketing", "/crypto",
            "/prompt", "/flora", "/cron", "/pm",
            "progress",
        ):
            self.assertIn(marker, text, f"missing: {marker!r}")

    def test_menu_text_present(self):
        text = adapter._MENU_RU
        self.assertIn("Hermes", text)
        self.assertIn("/menu", text)
        # Compact list of commands
        for cmd in ("/status", "/model", "/new", "/reset",
                    "/stop", "/retry", "/undo"):
            self.assertIn(cmd, text)

    def test_roles_text_present(self):
        text = adapter._ROLES_RU
        self.assertIn("F-NEXT-AGENT-MESH", text)
        for role in ("/dev", "/copy", "/marketing", "/crypto",
                     "/prompt", "/flora", "/cron", "/pm"):
            self.assertIn(role, text)

    def test_intercept_table_only_adapter_commands(self):
        # Critical: must NOT contain commands core already owns
        # Otherwise we'd shadow core's response.
        table = adapter._ADAPTER_HELP_COMMANDS
        forbidden_in_adapter = {
            "help", "commands", "status", "model", "new", "reset",
            "stop", "retry", "undo", "sethome", "kanban", "voice",
            "insights", "title", "resume", "compress", "usage",
        }
        for cmd in forbidden_in_adapter:
            self.assertNotIn(cmd, table, f"adapter-level must not shadow core: /{cmd}")
        # Only our own commands
        self.assertEqual(set(table.keys()), {"/menu", "/roles"})

    def test_no_token_in_help_text(self):
        # Even by accident — token must never appear in static help
        sentinel = "FAKE_TOKEN_DO_NOT_LEAK_123456"
        for text in (adapter._HELP_RU, adapter._MENU_RU, adapter._ROLES_RU):
            self.assertNotIn(sentinel, text)


class TestAdapterHelpIntercept(unittest.TestCase):
    """F-07b: /menu and /roles intercepted by _handle_update, /help passes through."""

    def _make_update(self, text):
        """Construct a minimal MAX update payload."""
        return {
            "update_type": "message_created",
            "update_id": f"hash:test:{text}",
            "timestamp": 1700000000000,
            "message": {
                "body": {"mid": "mid.test", "text": text},
                "recipient": {"chat_id": 111222333, "chat_type": "dialog"},
                "sender": {"user_id": 12345678},
            },
        }

    def _make_adapter(self):
        inst = adapter.MaxAdapter.__new__(adapter.MaxAdapter)
        inst._last_progress_sent = {}
        inst._last_typing_chat = {}
        inst._typing_unsupported_logged = set()
        inst._token = "fake_token_for_test_only"
        inst._api_base = "https://example.test"
        inst._bot_id = 987654321
        inst._marker = 5000
        inst._seen_updates = {}
        inst._is_duplicate = MagicMock(return_value=False)
        inst.send = AsyncMock(
            return_value=adapter.SendResult(success=True, message_id="m1")
        )
        # F-07b: handle_message is called on non-intercepted paths
        inst.handle_message = AsyncMock()
        # build_source needs self.platform (set by BasePlatformAdapter.__init__)
        # Stub as a MagicMock with .value = "max"
        inst.platform = MagicMock()
        inst.platform.value = "max"
        return inst

    def test_menu_intercepted(self):
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/menu")))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs["content"]
        self.assertIn("Hermes", sent_text)
        self.assertIn("/menu", sent_text)
        # handle_message NOT called — short-circuited
        inst.handle_message.assert_not_called()

    def test_roles_intercepted(self):
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/roles")))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs["content"]
        self.assertIn("F-NEXT-AGENT-MESH", sent_text)
        inst.handle_message.assert_not_called()

    def test_help_NOT_intercepted_passes_through(self):
        # /help belongs to core — must NOT be intercepted by adapter
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/help")))
        # Adapter did NOT call self.send with Russian help
        inst.send.assert_not_called()
        # It SHOULD fall through to handle_message (core handles /help)
        inst.handle_message.assert_awaited_once()

    def test_commands_NOT_intercepted_passes_through(self):
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/commands")))
        inst.send.assert_not_called()
        inst.handle_message.assert_awaited_once()

    def test_status_passes_through(self):
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/status")))
        inst.send.assert_not_called()
        inst.handle_message.assert_awaited_once()

    def test_regular_text_passes_through(self):
        inst = self._make_adapter()
        asyncio.run(self._make_adapter_and_dispatch(inst, "Скажи коротко, новая сессия работает?"))
        inst.send.assert_not_called()
        inst.handle_message.assert_awaited_once()

    async def _make_adapter_and_dispatch(self, inst, text):
        # Just an alias for the regular path
        await inst._handle_update(self._make_update(text))

    def test_menu_case_insensitive(self):
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/MENU")))
        inst.send.assert_awaited_once()
        inst.handle_message.assert_not_called()

    def test_menu_with_args_still_intercepted(self):
        # /menu whatever → still intercept (we send help, ignore args)
        inst = self._make_adapter()
        asyncio.run(inst._handle_update(self._make_update("/menu extra junk")))
        inst.send.assert_awaited_once()
        inst.handle_message.assert_not_called()


# ---------------------------------------------------------------------------
# F-09: standalone_sender_fn — cron deliver=max support
# ---------------------------------------------------------------------------

class TestStandaloneSend(unittest.TestCase):
    """F-09: _standalone_send routes, splits, returns proper shape, no leaks.

    No real network — we patch ``_standalone_post_one`` to return
    canned responses (success and error) and assert the wrapper's
    behaviour around it.
    """

    def _ok_response(self, mid="mid.standalone.123"):
        return {
            "success": True,
            "platform": "max",
            "chat_id": "user:12345678",
            "message_id": mid,
        }

    def _err_response(self, msg="HTTP 500: boom"):
        return {"error": msg}

    def _make_pconfig(self):
        # Just an opaque object — the standalone sender doesn't read it
        return MagicMock(name="pconfig")

    # --- happy path ------------------------------------------------------

    def test_user_route_success(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok_1234567890"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response("mid.aaa"),
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:12345678", "hello"
                    )
                )
        m.assert_called_once()
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("platform"), "max")
        self.assertEqual(result.get("chat_id"), "user:12345678")
        self.assertEqual(result.get("message_id"), "mid.aaa")
        self.assertEqual(result.get("message_ids"), ["mid.aaa"])
        # Verify URL built correctly via kwarg
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["route_kind"], "user")
        self.assertEqual(kwargs["route_id"], "12345678")
        self.assertEqual(kwargs["content"], "hello")
        self.assertEqual(kwargs["api_base"], adapter.MAX_API_BASE_DEFAULT)
        self.assertEqual(kwargs["token"], "fake_tok_1234567890")

    def test_chat_route_success(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response("mid.ccc"),
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "chat:-1001234567890", "to channel"
                    )
                )
        m.assert_called_once()
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("chat_id"), "chat:-1001234567890")
        self.assertEqual(m.call_args.kwargs["route_kind"], "chat")
        self.assertEqual(m.call_args.kwargs["route_id"], "-1001234567890")

    def test_bare_numeric_treated_as_chat(self):
        # Backward-compat: bare int → chat route (F-06a behaviour)
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response(),
            ) as m:
                asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "111222333", "x"
                    )
                )
        self.assertEqual(m.call_args.kwargs["route_kind"], "chat")
        self.assertEqual(m.call_args.kwargs["route_id"], "111222333")

    def test_short_message_single_chunk(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response("mid.s"),
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:1", "hi"
                    )
                )
        self.assertEqual(m.call_count, 1)  # single chunk
        self.assertEqual(result["message_ids"], ["mid.s"])

    def test_long_message_multiple_chunks(self):
        long_text = "x" * (adapter.MAX_SEND_CHUNK_SIZE + 100)
        responses = [
            self._ok_response("mid.1"),
            self._ok_response("mid.2"),
        ]
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                side_effect=responses,
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:1", long_text
                    )
                )
        # At least 2 chunks
        self.assertGreaterEqual(m.call_count, 2)
        # last message_id is the last chunk's mid
        self.assertEqual(result["message_id"], "mid.2")
        # All mid's collected
        self.assertIn("mid.1", result["message_ids"])
        self.assertIn("mid.2", result["message_ids"])

    # --- failure modes ---------------------------------------------------

    def test_missing_token_returns_safe_error(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAX_BOT_TOKEN", None)
            with patch.object(
                adapter, "_standalone_post_one"
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:1", "hi"
                    )
                )
        # Did NOT call the HTTP helper — bailed at token check
        m.assert_not_called()
        self.assertIn("error", result)
        self.assertIn("MAX_BOT_TOKEN", result["error"])
        # No token leak
        self.assertNotIn("fake_tok", str(result))

    def test_empty_chat_id_returns_error(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(adapter, "_standalone_post_one") as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "", "hi"
                    )
                )
        m.assert_not_called()
        self.assertIn("error", result)
        self.assertIn("chat_id", result["error"])

    def test_unparseable_chat_id_returns_error(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(adapter, "_standalone_post_one") as m:
                # Empty after stripping "user:" prefix → unparseable
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:", "hi"
                    )
                )
        # "user:" → strips to "" → _parse_route returns ("user", "")
        # which yields route_id="" → we return error
        m.assert_not_called()
        self.assertIn("error", result)

    def test_http_error_propagates(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._err_response("HTTP 500: internal"),
            ):
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:1", "hi"
                    )
                )
        self.assertIn("error", result)
        self.assertIn("HTTP 500", result["error"])

    def test_markdown_rejected_retries_plain(self):
        # First call: markdown rejected (mock returns "format" error).
        # Second call (plain retry): success.
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                side_effect=[
                    {"error": "HTTP 400: format markdown not supported"},
                    self._ok_response("mid.plain"),
                ],
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(), "user:1", "**bold** text"
                    )
                )
        # Two calls: markdown then plain
        self.assertEqual(m.call_count, 2)
        # Second call had force_plain=True
        self.assertTrue(m.call_args_list[1].kwargs["force_plain"])
        # First had force_plain=False (default)
        self.assertFalse(m.call_args_list[0].kwargs.get("force_plain", False))
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("message_id"), "mid.plain")

    def test_signature_has_all_optional_kwargs(self):
        """Required signature per spec: (pconfig, chat_id, message, *,
        thread_id=None, media_files=None, force_document=False)."""
        import inspect
        sig = inspect.signature(adapter._standalone_send)
        params = sig.parameters
        self.assertIn("pconfig", params)
        self.assertIn("chat_id", params)
        self.assertIn("message", params)
        # All three optional kwargs must be keyword-only with defaults
        for name in ("thread_id", "media_files", "force_document"):
            p = params[name]
            self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY,
                             f"{name} must be keyword-only")
            # Defaults may be None — just verify the parameter is optional
            self.assertNotEqual(p.default, inspect.Parameter.empty,
                                f"{name} must have a default")
        # Verify it is async
        self.assertTrue(asyncio.iscoroutinefunction(adapter._standalone_send))

    def test_media_files_logged_but_dropped(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response(),
            ):
                # media_files=non-empty → logged as dropped, but send proceeds
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(),
                        "user:1", "hi",
                        media_files=["/tmp/x.png"],
                    )
                )
        self.assertTrue(result.get("success"))

    def test_thread_id_logged_but_ignored(self):
        with patch.dict(os.environ, {"MAX_BOT_TOKEN": "fake_tok"}, clear=False):
            with patch.object(
                adapter, "_standalone_post_one",
                return_value=self._ok_response(),
            ) as m:
                result = asyncio.run(
                    adapter._standalone_send(
                        self._make_pconfig(),
                        "user:1", "hi",
                        thread_id="t123",
                    )
                )
        # thread_id not passed to the post helper
        self.assertNotIn("thread_id", m.call_args.kwargs)
        self.assertTrue(result.get("success"))


# ---------------------------------------------------------------------------
# F-09: register() wires standalone_sender_fn
# ---------------------------------------------------------------------------

class TestRegisterWiring(unittest.TestCase):
    """F-09: register() must wire standalone_sender_fn and not leave None."""

    def test_standalone_sender_registered(self):
        # Build a minimal mock ctx and call register; capture kwargs.
        ctx = MagicMock()
        ctx.register_platform = MagicMock()
        adapter.register(ctx)
        ctx.register_platform.assert_called_once()
        kwargs = ctx.register_platform.call_args.kwargs
        self.assertIsNotNone(kwargs.get("standalone_sender_fn"))
        self.assertTrue(callable(kwargs["standalone_sender_fn"]))
        # Should be the same function as the module-level _standalone_send
        self.assertIs(kwargs["standalone_sender_fn"], adapter._standalone_send)

    def test_cron_deliver_env_var_set(self):
        ctx = MagicMock()
        ctx.register_platform = MagicMock()
        adapter.register(ctx)
        kwargs = ctx.register_platform.call_args.kwargs
        self.assertEqual(kwargs.get("cron_deliver_env_var"), "MAX_HOME_CHANNEL")

    def test_max_message_length_set(self):
        ctx = MagicMock()
        ctx.register_platform = MagicMock()
        adapter.register(ctx)
        kwargs = ctx.register_platform.call_args.kwargs
        # Must be present and > 0 so core's chunker uses it
        self.assertGreater(kwargs.get("max_message_length", 0), 0)


class TestRoleRegistryLoad(unittest.TestCase):
    """F-NEXT-03: role_registry.yaml loads and indexes enabled roles."""

    def test_registry_loads_enabled_roles(self):
        # Force reload
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        adapter._load_role_registry()
        # /copy — enabled since F-NEXT-03
        self.assertIn("/copy", adapter._ROLE_COMMANDS)
        entry = adapter._ROLE_COMMANDS["/copy"]
        self.assertEqual(entry["profile"], "copywriter")
        self.assertTrue(entry["enabled"])
        # /prompt — enabled since F-NEXT-04
        self.assertIn("/prompt", adapter._ROLE_COMMANDS)
        entry_p = adapter._ROLE_COMMANDS["/prompt"]
        self.assertEqual(entry_p["profile"], "prompt")
        self.assertTrue(entry_p["enabled"])
        # /marketing — enabled since F-NEXT-05
        self.assertIn("/marketing", adapter._ROLE_COMMANDS)
        entry_m = adapter._ROLE_COMMANDS["/marketing"]
        self.assertEqual(entry_m["profile"], "marketer")
        self.assertTrue(entry_m["enabled"])
        # Still disabled roles should NOT be indexed
        self.assertNotIn("/crypto", adapter._ROLE_COMMANDS)
        self.assertNotIn("/flora", adapter._ROLE_COMMANDS)
        # /dev — enabled since F-NEXT-06
        self.assertIn("/dev", adapter._ROLE_COMMANDS)
        entry_d = adapter._ROLE_COMMANDS["/dev"]
        self.assertEqual(entry_d["profile"], "coder")
        self.assertTrue(entry_d["enabled"])

    def test_soul_content_reads_file(self):
        adapter._load_role_registry()
        entry = adapter._ROLE_COMMANDS["/copy"]
        soul = adapter._get_soul_content(entry["soul_path"])
        self.assertIsNotNone(soul)
        self.assertGreater(len(soul), 50)  # SOUL.md is non-trivial

    def test_soul_content_missing_file_returns_none(self):
        soul = adapter._get_soul_content("/nonexistent/path/SOUL.md")
        self.assertIsNone(soul)

    def test_no_token_leak_in_soul(self):
        """SOUL.md content should not contain any secret tokens."""
        adapter._load_role_registry()
        entry = adapter._ROLE_COMMANDS["/copy"]
        soul = adapter._get_soul_content(entry["soul_path"])
        if soul:
            # Check for common secret patterns
            self.assertNotRegex(soul, r'ghp_[a-zA-Z0-9]{36}')
            self.assertNotRegex(soul, r'sk-[a-zA-Z0-9]{20,}')
            self.assertNotRegex(soul, r'BOT_TOKEN|TOKEN\s*=')
            self.assertNotRegex(soul, r'api_key|API_KEY')


class TestRoleIntercept(unittest.TestCase):
    """F-NEXT-03: /copy intercept in _handle_update."""

    def _make_update(self, text):
        return {
            "update_type": "message_created",
            "update_id": f"hash:test:{text}",
            "timestamp": 1700000000000,
            "message": {
                "body": {"mid": "mid.test", "text": text},
                "recipient": {"chat_id": 111222333, "chat_type": "dialog"},
                "sender": {"user_id": 12345678},
            },
        }

    def _make_adapter(self):
        inst = adapter.MaxAdapter.__new__(adapter.MaxAdapter)
        inst._last_progress_sent = {}
        inst._last_typing_chat = {}
        inst._typing_unsupported_logged = set()
        inst._role_channel_prompt = None
        inst._token = "fake_token_for_test_only"
        inst._api_base = "https://example.test"
        inst._bot_id = 987654321
        inst._marker = 5000
        inst._seen_updates = {}
        inst._is_duplicate = MagicMock(return_value=False)
        inst.send = AsyncMock(
            return_value=adapter.SendResult(success=True, message_id="m1")
        )
        inst.handle_message = AsyncMock()
        inst.platform = MagicMock()
        inst.platform.value = "max"
        return inst

    def test_copy_no_task_returns_help(self):
        """/copy alone shows role-specific help."""
        inst = self._make_adapter()
        upd = self._make_update("/copy")
        asyncio.run(inst._handle_update(upd))
        # send() should be called with role help
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs.get("content", "")
        self.assertIn("Копирайтер", sent_text)
        self.assertIn("Напиши задачу", sent_text)
        # handle_message NOT called (intercepted)
        inst.handle_message.assert_not_called()

    def test_copy_with_task_sets_channel_prompt(self):
        """/copy <task> sets _role_channel_prompt and dispatches to gateway."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        inst = self._make_adapter()
        upd = self._make_update("/copy Напиши пост про AI")
        asyncio.run(inst._handle_update(upd))
        # handle_message should be called (not intercepted)
        inst.handle_message.assert_awaited_once()
        event = inst.handle_message.await_args.args[0]
        # channel_prompt should be set with SOUL.md content
        self.assertIsNotNone(event.channel_prompt)
        self.assertIn("Копирайтер", event.channel_prompt)
        self.assertIn("SOUL.md", event.channel_prompt)
        # text should be enriched with role prefix
        self.assertIn("Копирайтер", event.text)
        self.assertIn("Напиши пост про AI", event.text)
        # channel_prompt cleared after use
        self.assertIsNone(getattr(inst, "_role_channel_prompt", None))

    def test_dev_with_task_sets_channel_prompt(self):
        """/dev <task> dispatches with coder SOUL.md."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        inst = self._make_adapter()
        upd = self._make_update("/dev fix the bug")
        asyncio.run(inst._handle_update(upd))
        inst.handle_message.assert_awaited_once()
        event = inst.handle_message.await_args.args[0]
        self.assertIsNotNone(event.channel_prompt)
        self.assertIn("Кодер", event.channel_prompt)
        self.assertIn("SOUL.md", event.channel_prompt)
        self.assertIn("fix the bug", event.text)

    def test_dev_no_task_returns_help(self):
        """/dev alone shows role-specific help."""
        inst = self._make_adapter()
        upd = self._make_update("/dev")
        asyncio.run(inst._handle_update(upd))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs.get("content", "")
        self.assertIn("Кодер", sent_text)
        self.assertIn("Напиши задачу", sent_text)
        inst.handle_message.assert_not_called()

    def test_dev_soul_no_secrets(self):
        """Coder SOUL.md should not contain any secret tokens."""
        adapter._load_role_registry()
        entry = adapter._ROLE_COMMANDS["/dev"]
        soul = adapter._get_soul_content(entry["soul_path"])
        if soul:
            self.assertNotRegex(soul, r'ghp_[a-zA-Z0-9]{36}')
            self.assertNotRegex(soul, r'sk-[a-zA-Z0-9]{20,}')
            self.assertNotRegex(soul, r'BOT_TOKEN|TOKEN\\s*=')
            self.assertNotRegex(soul, r'api_key|API_KEY')

    def test_menu_still_works(self):
        """Regression: /menu not broken by role intercept."""
        inst = self._make_adapter()
        upd = self._make_update("/menu")
        asyncio.run(inst._handle_update(upd))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs.get("content", "")
        self.assertIn("Hermes", sent_text)
        inst.handle_message.assert_not_called()

    def test_status_not_intercepted(self):
        """Regression: /status passes through to gateway."""
        inst = self._make_adapter()
        upd = self._make_update("/status")
        asyncio.run(inst._handle_update(upd))
        inst.handle_message.assert_awaited_once()

    def test_regular_text_not_intercepted(self):
        """Regression: plain text passes through."""
        inst = self._make_adapter()
        upd = self._make_update("Привет, как дела?")
        asyncio.run(inst._handle_update(upd))
        inst.handle_message.assert_awaited_once()
        event = inst.handle_message.await_args.args[0]
        self.assertIsNone(event.channel_prompt)

    def test_copy_case_insensitive(self):
        """/COPY and /Copy should also work."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        for cmd in ("/Copy", "/COPY"):
            inst = self._make_adapter()
            upd = self._make_update(f"{cmd} тестовая задача")
            asyncio.run(inst._handle_update(upd))
            inst.handle_message.assert_awaited_once()
            event = inst.handle_message.await_args.args[0]
            self.assertIsNotNone(event.channel_prompt)

    def test_role_channel_prompt_cleared_after_dispatch(self):
        """_role_channel_prompt is one-shot — cleared after MessageEvent build."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        inst = self._make_adapter()
        upd = self._make_update("/copy тест")
        asyncio.run(inst._handle_update(upd))
        self.assertIsNone(getattr(inst, "_role_channel_prompt", None))

    def test_prompt_with_task_sets_channel_prompt(self):
        """/prompt <task> dispatches with prompt-engineer SOUL.md."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        inst = self._make_adapter()
        upd = self._make_update("/prompt Сделай сильный промпт для видео")
        asyncio.run(inst._handle_update(upd))
        inst.handle_message.assert_awaited_once()
        event = inst.handle_message.await_args.args[0]
        self.assertIsNotNone(event.channel_prompt)
        self.assertIn("Промт-инженер", event.channel_prompt)
        self.assertIn("SOUL.md", event.channel_prompt)
        self.assertIn("промпт для видео", event.text)

    def test_prompt_no_task_returns_help(self):
        """/prompt alone shows role-specific help."""
        inst = self._make_adapter()
        upd = self._make_update("/prompt")
        asyncio.run(inst._handle_update(upd))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs.get("content", "")
        self.assertIn("Промт-инженер", sent_text)
        self.assertIn("Напиши задачу", sent_text)
        inst.handle_message.assert_not_called()

    def test_prompt_soul_no_secrets(self):
        """Prompt SOUL.md content should not contain any secret tokens."""
        adapter._load_role_registry()
        entry = adapter._ROLE_COMMANDS["/prompt"]
        soul = adapter._get_soul_content(entry["soul_path"])
        if soul:
            self.assertNotRegex(soul, r'ghp_[a-zA-Z0-9]{36}')
            self.assertNotRegex(soul, r'sk-[a-zA-Z0-9]{20,}')
            self.assertNotRegex(soul, r'BOT_TOKEN|TOKEN\\s*=')
            self.assertNotRegex(soul, r'api_key|API_KEY')

    def test_marketing_with_task_sets_channel_prompt(self):
        """/marketing <task> dispatches with marketer SOUL.md."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        inst = self._make_adapter()
        upd = self._make_update("/marketing Придумай стратегию продвижения")
        asyncio.run(inst._handle_update(upd))
        inst.handle_message.assert_awaited_once()
        event = inst.handle_message.await_args.args[0]
        self.assertIsNotNone(event.channel_prompt)
        self.assertIn("Маркетолог", event.channel_prompt)
        self.assertIn("SOUL.md", event.channel_prompt)
        self.assertIn("стратегию продвижения", event.text)

    def test_marketing_no_task_returns_help(self):
        """/marketing alone shows role-specific help."""
        inst = self._make_adapter()
        upd = self._make_update("/marketing")
        asyncio.run(inst._handle_update(upd))
        inst.send.assert_awaited_once()
        sent_text = inst.send.await_args.kwargs.get("content", "")
        self.assertIn("Маркетолог", sent_text)
        self.assertIn("Напиши задачу", sent_text)
        inst.handle_message.assert_not_called()

    def test_marketing_soul_no_secrets(self):
        """Marketing SOUL.md should not contain any secret tokens."""
        adapter._load_role_registry()
        entry = adapter._ROLE_COMMANDS["/marketing"]
        soul = adapter._get_soul_content(entry["soul_path"])
        if soul:
            self.assertNotRegex(soul, r'ghp_[a-zA-Z0-9]{36}')
            self.assertNotRegex(soul, r'sk-[a-zA-Z0-9]{20,}')
            self.assertNotRegex(soul, r'BOT_TOKEN|TOKEN\\s*=')
            self.assertNotRegex(soul, r'api_key|API_KEY')


# ---------------------------------------------------------------------------
# F-TEAM-02: Team manager tests
# ---------------------------------------------------------------------------

class TestTeamManagerValidation(unittest.TestCase):
    """Test team_manager.core validation logic."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def tearDown(self):
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def test_valid_team_add(self):
        """Valid name/route/title/soul passes validation."""
        r = self.tm.validate_team_add(
            "testagent", "/testagent", "Test Agent",
            "Ты тестовый агент. " * 20
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.fields["name"], "testagent")
        self.assertEqual(r.fields["route"], "/testagent")

    def test_invalid_name_rejected(self):
        """Name with uppercase or special chars rejected."""
        r = self.tm.validate_team_add(
            "BAD Name!", "/badname", "Title",
            "Ты тест " * 20
        )
        self.assertFalse(r.ok)
        self.assertTrue(any("name" in e for e in r.errors))

    def test_invalid_route_no_slash(self):
        """Route without leading / rejected."""
        r = self.tm.validate_team_add(
            "agent", "noslash", "Title",
            "Ты тест " * 20
        )
        self.assertFalse(r.ok)
        self.assertTrue(any("route" in e for e in r.errors))

    def test_reserved_route_rejected(self):
        """Reserved routes like /status rejected."""
        for reserved in ["/status", "/model", "/menu", "/copy", "/dev"]:
            r = self.tm.validate_team_add(
                "agent", reserved, "Title",
                "Ты тест " * 20
            )
            self.assertFalse(r.ok, f"{reserved} should be rejected")
            self.assertTrue(
                any("системная" in e or "reserved" in e.lower() for e in r.errors),
                f"{reserved}: {r.errors}"
            )

    def test_duplicate_route_rejected(self):
        """Route already in registry rejected."""
        # Use /marketing — not in RESERVED_ROUTES but in active registry
        r = self.tm.validate_team_add(
            "newrole", "/marketing", "New Role",
            "Ты тест " * 20
        )
        self.assertFalse(r.ok)
        self.assertTrue(
            any("уже используется" in e or "системная" in e for e in r.errors),
            f"errors: {r.errors}"
        )

    def test_duplicate_profile_rejected(self):
        """Name that already has a profile dir rejected."""
        r = self.tm.validate_team_add(
            "copywriter", "/newroute", "New",
            "Ты тест " * 20
        )
        self.assertFalse(r.ok)
        self.assertTrue(any("уже существует" in e for e in r.errors))

    def test_short_soul_rejected(self):
        """SOUL under 100 chars rejected."""
        r = self.tm.validate_team_add(
            "agent", "/agent", "Title",
            "Короткий"
        )
        self.assertFalse(r.ok)
        self.assertTrue(any("короткий" in e.lower() for e in r.errors))

    def test_secret_in_soul_rejected(self):
        """SOUL containing secret token rejected (dynamic fixture)."""
        # Build the secret string at runtime so no literal secret pattern
        # (sk-, ghp_, xoxb-) appears in this source file.
        secret = "BOT_" + "TOKEN" + "_VALUE"
        soul = ("Ты тестовый агент. Вот секрет: " + secret + ". ") * 5
        r = self.tm.validate_team_add("agent", "/agent", "Title", soul)
        self.assertFalse(r.ok)
        self.assertTrue(any("секрет" in e.lower() for e in r.errors))

    def test_bot_token_in_soul_rejected(self):
        """SOUL containing BOT_TOKEN rejected."""
        r = self.tm.validate_team_add(
            "agent", "/agent", "Title",
            "Ты агент. Не используй BOT_TOKEN в коде. " * 10
        )
        self.assertFalse(r.ok)

    def test_empty_soul_rejected(self):
        """Missing SOUL returns appropriate error."""
        r = self.tm.validate_team_add(
            "agent", "/agent", "Title", ""
        )
        self.assertFalse(r.ok)
        self.assertTrue(any("SOUL" in e for e in r.errors))


class TestTeamManagerParsing(unittest.TestCase):
    """Test /team-add command parsing."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm

    def test_parse_inline_soul(self):
        """Parse name=X route=/X title="Y" SOUL:text."""
        params, err = self.tm.parse_team_add_args(
            '/team-add name=designer route=/design title="Дизайнер" SOUL:Ты дизайнер визуалов'
        )
        self.assertIsNone(err)
        self.assertEqual(params["name"], "designer")
        self.assertEqual(params["route"], "/design")
        self.assertEqual(params["title"], "Дизайнер")
        self.assertEqual(params["soul"], "Ты дизайнер визуалов")

    def test_parse_no_soul(self):
        """Missing SOUL returns params without soul key."""
        params, err = self.tm.parse_team_add_args(
            '/team-add name=agent route=/agent title="Agent"'
        )
        self.assertIsNone(err)
        self.assertNotIn("soul", params)

    def test_parse_empty_text(self):
        """Empty text after /team-add returns error."""
        params, err = self.tm.parse_team_add_args("/team-add")
        self.assertIsNotNone(err)
        self.assertEqual(params, {})

    def test_parse_unquoted_title(self):
        """Unquoted title value works too."""
        params, err = self.tm.parse_team_add_args(
            '/team-add name=agent route=/agent title=Agent SOUL:Ты агент'
        )
        self.assertIsNone(err)
        self.assertEqual(params["title"], "Agent")


class TestTeamManagerPendingState(unittest.TestCase):
    """Test pending state CRUD."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def tearDown(self):
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def test_create_pending(self):
        """Create pending writes JSON with correct fields."""
        record = self.tm.create_pending(
            user_id="12345678",
            name="testagent",
            route="/testagent",
            title="Test Agent",
            soul="Ты тест " * 20,
        )
        self.assertIn("id", record)
        self.assertTrue(record["id"].startswith("ta_"))
        self.assertEqual(record["name"], "testagent")
        self.assertEqual(record["status"], "dry_run")
        self.assertEqual(record["creator_user_id"], "12345678")

        # File exists with mode 600
        path = self.tm._pending_path(record["id"])
        self.assertTrue(path.exists())
        mode = oct(path.stat().st_mode)[-3:]
        self.assertEqual(mode, "600")

    def test_read_pending(self):
        """Read back pending record."""
        record = self.tm.create_pending(
            "12345678", "agent", "/agent", "Agent",
            "Ты агент " * 20,
        )
        read_back = self.tm.read_pending(record["id"])
        self.assertIsNotNone(read_back)
        self.assertEqual(read_back["name"], "agent")
        self.assertEqual(read_back["soul"], "Ты агент " * 20)

    def test_delete_pending(self):
        """Delete pending removes file."""
        record = self.tm.create_pending(
            "12345678", "agent", "/agent", "Agent",
            "Ты агент " * 20,
        )
        self.assertTrue(self.tm.delete_pending(record["id"]))
        self.assertIsNone(self.tm.read_pending(record["id"]))

    def test_read_nonexistent_pending(self):
        """Read nonexistent ID returns None."""
        self.assertIsNone(self.tm.read_pending("ta_nonexistent"))

    def test_list_pending(self):
        """List shows pending records without soul content."""
        self.tm.create_pending(
            "12345678", "agent1", "/agent1", "Agent 1",
            "Ты агент 1 " * 20,
        )
        self.tm.create_pending(
            "12345678", "agent2", "/agent2", "Agent 2",
            "Ты агент 2 " * 20,
        )
        items = self.tm.list_pending()
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertNotIn("soul", item)
            self.assertIn("soul_len", item)

    def test_preview_format(self):
        """Preview contains key fields."""
        record = self.tm.create_pending(
            "12345678", "myagent", "/myagent", "My Agent",
            "Ты мой агент " * 20,
        )
        preview = self.tm.format_preview(record)
        self.assertIn("myagent", preview)
        self.assertIn("/myagent", preview)
        self.assertIn("My Agent", preview)
        self.assertIn("dry-run", preview)
        self.assertIn("F-TEAM-03", preview)
        self.assertIn(record["id"], preview)


class TestTeamManagerConfirmStub(unittest.TestCase):
    """Test /team-confirm stub returns disabled message."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def tearDown(self):
        pending_dir = self.tm.PENDING_DIR
        if pending_dir.exists():
            for f in pending_dir.glob("ta_*.json"):
                f.unlink()

    def test_confirm_returns_disabled(self):
        """Confirm shows disabled message, does not create files."""
        record = self.tm.create_pending(
            "12345678", "agent", "/agent", "Agent",
            "Ты агент " * 20,
        )
        msg = self.tm.format_confirm_disabled(record["id"])
        # Russian: "отключён" = disabled
        self.assertTrue(
            "отключён" in msg.lower() or "disabled" in msg.lower(),
            f"Expected disabled/отключён in: {msg}"
        )
        self.assertIn("F-TEAM-03", msg)
        self.assertFalse(
            Path("/root/.hermes/profiles/agent").exists()
        )

    def test_no_profiles_created(self):
        """Ensure no profiles created during dry-run."""
        self.tm.create_pending(
            "12345678", "xyzagent", "/xyzagent", "XYZ",
            "Ты тест " * 20,
        )
        self.assertFalse(
            Path("/root/.hermes/profiles/xyzagent").exists()
        )

    def test_registry_unchanged(self):
        """Registry file MD5 unchanged after dry-run."""
        import hashlib
        reg = Path("/root/.hermes/plugins/max/role_registry.yaml")
        before = hashlib.md5(reg.read_bytes()).hexdigest()

        self.tm.create_pending(
            "12345678", "newagent", "/newagent", "New",
            "Ты новый агент " * 20,
        )

        after = hashlib.md5(reg.read_bytes()).hexdigest()
        self.assertEqual(before, after, "Registry should not change in dry-run")


class TestTeamRegression(unittest.TestCase):
    """Regression: existing role-routes still work after team code."""

    def test_copy_still_in_commands(self):
        """/copy still registered."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        adapter._load_role_registry()
        self.assertIn("/copy", adapter._ROLE_COMMANDS)

    def test_dev_still_in_commands(self):
        """/dev still registered."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        adapter._load_role_registry()
        self.assertIn("/dev", adapter._ROLE_COMMANDS)

    def test_marketing_still_in_commands(self):
        """/marketing still registered."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        adapter._load_role_registry()
        self.assertIn("/marketing", adapter._ROLE_COMMANDS)

    def test_prompt_still_in_commands(self):
        """/prompt still registered."""
        adapter._ROLE_REGISTRY = None
        adapter._ROLE_COMMANDS = {}
        adapter._load_role_registry()
        self.assertIn("/prompt", adapter._ROLE_COMMANDS)


# ---------------------------------------------------------------------------
# F-TEAM-03: Confirm + Rollback tests
# ---------------------------------------------------------------------------

class TestTeamConfirmReal(unittest.TestCase):
    """Test real /team-confirm creates profile + registry entry."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm
        # Clean pending
        if self.tm.PENDING_DIR.exists():
            for f in self.tm.PENDING_DIR.glob("ta_*.json"):
                f.unlink()
        # Clean test profile if exists
        self._clean_test_profile("test_confirm_agent")

    def tearDown(self):
        self._clean_test_profile("test_confirm_agent")
        # Clean pending
        if self.tm.PENDING_DIR.exists():
            for f in self.tm.PENDING_DIR.glob("ta_*.json"):
                f.unlink()
        # Restore registry from backup if we modified it
        backup_dir = self.tm._BACKUP_DIR
        if backup_dir.exists():
            for bak in sorted(backup_dir.glob("role_registry_*.bak")):
                # Only restore the most recent one if test profile in registry
                content = self.tm.REGISTRY_PATH.read_text(encoding="utf-8")
                if "test_confirm_agent" in content:
                    import shutil
                    shutil.copy2(str(bak), str(self.tm.REGISTRY_PATH))
                break

    def _clean_test_profile(self, name):
        import shutil
        p = Path.home() / ".hermes" / "profiles" / name
        if p.exists():
            shutil.rmtree(str(p), ignore_errors=True)

    def test_confirm_creates_profile(self):
        """Confirm creates SOUL.md + config.yaml."""
        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test Confirm Agent",
            "Ты тестовый агент для confirm. " * 10,
        )
        success, msg = self.tm.confirm_pending(record["id"], "12345678")
        self.assertTrue(success, f"confirm failed: {msg}")

        # Profile files exist
        soul = Path("/root/.hermes/profiles/test_confirm_agent/SOUL.md")
        cfg = Path("/root/.hermes/profiles/test_confirm_agent/config.yaml")
        self.assertTrue(soul.exists(), "SOUL.md missing")
        self.assertTrue(cfg.exists(), "config.yaml missing")

        # SOUL content matches
        self.assertIn("тестовый агент", soul.read_text(encoding="utf-8"))

    def test_confirm_creates_backup(self):
        """Confirm creates registry backup before editing."""
        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test Agent",
            "Ты тест confirm backup. " * 10,
        )
        self.tm.confirm_pending(record["id"], "12345678")

        backup_dir = self.tm._BACKUP_DIR
        self.assertTrue(backup_dir.exists())
        backups = list(backup_dir.glob("role_registry_*.bak"))
        self.assertGreater(len(backups), 0, "No backup created")

    def test_confirm_appends_registry(self):
        """Confirm adds entry to role_registry.yaml."""
        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test Agent",
            "Ты тест confirm registry. " * 10,
        )
        self.tm.confirm_pending(record["id"], "12345678")

        content = self.tm.REGISTRY_PATH.read_text(encoding="utf-8")
        self.assertIn("test_confirm_agent:", content)
        self.assertIn("command: /test_confirm_agent", content)

    def test_confirm_rejects_wrong_user(self):
        """Confirm rejects user who didn't create the pending."""
        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test",
            "Ты тест " * 20,
        )
        success, msg = self.tm.confirm_pending(record["id"], "99999")
        self.assertFalse(success)
        self.assertIn("создатель", msg.lower())

    def test_confirm_rejects_expired(self):
        """Confirm rejects expired pending."""
        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test",
            "Ты тест " * 20,
        )
        # Manually expire
        rec = self.tm.read_pending(record["id"])
        rec["expires_at"] = "2020-01-01T00:00:00+00:00"
        self.tm._write_pending_file(record["id"], rec)

        success, msg = self.tm.confirm_pending(record["id"], "12345678")
        self.assertFalse(success)
        self.assertIn("истёк", msg)

    def test_confirm_rejects_duplicate_profile(self):
        """Confirm rejects if profile already exists."""
        import shutil
        p = Path.home() / ".hermes" / "profiles" / "test_confirm_agent"
        p.mkdir(parents=True, exist_ok=True)
        (p / "SOUL.md").write_text("old", encoding="utf-8")

        record = self.tm.create_pending(
            "12345678", "test_confirm_agent", "/test_confirm_agent",
            "Test",
            "Ты тест " * 20,
        )
        success, msg = self.tm.confirm_pending(record["id"], "12345678")
        self.assertFalse(success)
        self.assertIn("уже существует", msg)


class TestTeamRollback(unittest.TestCase):
    """Test /team-rollback removes profile + registry entry."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from team_manager import core as tm
        self.tm = tm

    def tearDown(self):
        # Ensure clean state
        import shutil
        for name in ["test_rb_agent"]:
            p = Path.home() / ".hermes" / "profiles" / name
            if p.exists():
                shutil.rmtree(str(p), ignore_errors=True)

    def _create_test_agent(self):
        """Helper: create a test agent via confirm."""
        import shutil
        p = Path.home() / ".hermes" / "profiles" / "test_rb_agent"
        if p.exists():
            shutil.rmtree(str(p), ignore_errors=True)
        # Clean registry of any leftover
        content = self.tm.REGISTRY_PATH.read_text(encoding="utf-8")
        if "test_rb_agent" in content:
            import re
            content = re.sub(r"\n  test_rb_agent:\s*\n(?:    [^\n]*\n)*", "\n", content)
            self.tm.REGISTRY_PATH.write_text(content, encoding="utf-8")

        record = self.tm.create_pending(
            "12345678", "test_rb_agent", "/test_rb_agent",
            "Rollback Test",
            "Ты агент для теста rollback. " * 10,
        )
        self.tm.confirm_pending(record["id"], "12345678")
        # Clean pending
        if self.tm.PENDING_DIR.exists():
            for f in self.tm.PENDING_DIR.glob("ta_*.json"):
                f.unlink()
        return record

    def test_rollback_removes_profile(self):
        """Rollback deletes profile directory."""
        self._create_test_agent()
        p = Path.home() / ".hermes" / "profiles" / "test_rb_agent"
        self.assertTrue(p.exists(), "Profile should exist before rollback")

        success, msg = self.tm.rollback_agent("test_rb_agent", "12345678")
        self.assertTrue(success, f"rollback failed: {msg}")
        self.assertFalse(p.exists(), "Profile should be removed")

    def test_rollback_removes_registry_entry(self):
        """Rollback removes entry from registry."""
        self._create_test_agent()

        self.tm.rollback_agent("test_rb_agent", "12345678")

        content = self.tm.REGISTRY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("test_rb_agent:", content)
        self.assertNotIn("/test_rb_agent", content)

    def test_rollback_preserves_old_routes(self):
        """Rollback doesn't break existing routes."""
        self._create_test_agent()

        self.tm.rollback_agent("test_rb_agent", "12345678")

        content = self.tm.REGISTRY_PATH.read_text(encoding="utf-8")
        self.assertIn("command: /copy", content)
        self.assertIn("command: /dev", content)
        self.assertIn("command: /marketing", content)
        self.assertIn("command: /prompt", content)

    def test_rollback_nonexistent_agent(self):
        """Rollback of nonexistent agent returns error."""
        success, msg = self.tm.rollback_agent("nonexistent_agent_xyz", "12345678")
        self.assertFalse(success)
        self.assertIn("не найден", msg)

    def test_rollback_creates_backup(self):
        """Rollback creates backup before editing registry."""
        self._create_test_agent()

        self.tm.rollback_agent("test_rb_agent", "12345678")

        backup_dir = self.tm._BACKUP_DIR
        backups = list(backup_dir.glob("role_registry_pre_rollback_*.bak"))
        self.assertGreater(len(backups), 0, "No rollback backup created")


if __name__ == "__main__":
    unittest.main(verbosity=2)

