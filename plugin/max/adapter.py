"""MAX platform adapter — MVP step 2 (F-04.5 + F-05a).

Steps implemented in this file:
  F-02 — plugin.yaml manifest
  F-03 — MaxAdapter class wrapping BasePlatformAdapter (lazy import)
  F-04 — connect() does GET /me to validate the token
  F-04.5 — long-polling loop via GET /updates
  F-05a — receive updates, log metadata only (NO handle_message, NO send)

Steps NOT yet implemented (intentionally):
  F-05b — call self.handle_message(event) when an update is received
  F-06   — POST /messages for replies
  F-07   — slash-command passthrough (commands pass through to gateway already)
  F-08   — allowlist enforcement
  F-09   — standalone_sender_fn for cron

References (do not edit, do not import secrets here):
  - ~/.hermes/skills/devops/messenger-max/SKILL.md
  - ~/.hermes/skills/devops/messenger-max/references/max-publish-quickref.md
  - /usr/local/lib/hermes-agent/gateway/platforms/ADDING_A_PLATFORM.md
  - /usr/local/lib/hermes-agent/hermes_cli/plugins.py::PluginContext.register_platform
  - /usr/local/lib/hermes-agent/gateway/platform_registry.py::PlatformEntry
"""

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Direct imports — only valid when the gateway runtime is importable
# (i.e. ``sys.path`` includes ``/usr/local/lib/hermes-agent``). The
# bundled plugin examples (ntfy/irc/line) follow the same pattern.
from gateway.platforms.base import (  # type: ignore
    BasePlatformAdapter,
    MessageEvent,        # noqa: F401 — used in F-05b
    MessageType,         # noqa: F401 — used in F-05b
    SendResult,          # noqa: F401 — used in F-06
)
from gateway.config import Platform  # type: ignore

logger = logging.getLogger(__name__)

MAX_API_BASE_DEFAULT = "https://platform-api.max.ru"

# Long-poll tunables (env-overridable)
MAX_POLL_TIMEOUT_SECONDS = int(os.environ.get("MAX_POLL_TIMEOUT", "30"))
MAX_POLL_TYPES = os.environ.get(
    "MAX_POLL_TYPES",
    "message_created,bot_started,message_callback,bot_added",
)
MAX_MARKER_PATH = Path(
    os.environ.get(
        "MAX_MARKER_PATH",
        str(Path.home() / ".hermes" / "state" / "max_poll_marker"),
    )
)
MAX_DEDUP_MAX_SIZE = 500
MAX_DEDUP_TTL_SECONDS = 300  # 5 min
POLL_BACKOFF = (2, 5, 10, 30, 60)

# F-06a tunables
MAX_SEND_CHUNK_SIZE = 3900  # safely under MAX 4000-char limit


def _mask(token: Optional[str]) -> str:
    """Return a non-reversible placeholder for a token (length only)."""
    if not token:
        return "<missing>"
    return f"<token len={len(token)}>"


def _get_token() -> str:
    """Read MAX_BOT_TOKEN from environment only.

    Do NOT read ~/.hermes/.env here — the gateway runtime already loads
    it into os.environ before plugin discovery. Reading the file directly
    risks double-loading and bypasses profile-scoped .env.
    """
    return os.environ.get("MAX_BOT_TOKEN", "").strip()


def _api_base() -> str:
    base = os.environ.get("MAX_API_BASE", "").strip()
    return base.rstrip("/") or MAX_API_BASE_DEFAULT


# ---------------------------------------------------------------------------
# check_fn / validate_config / is_connected — used by plugin_registry
# ---------------------------------------------------------------------------

def check_requirements() -> bool:
    """Return True iff MAX_BOT_TOKEN is present in the environment.

    Called by ``gateway/run.py::_create_adapter`` before instantiating
    the adapter. Returning False logs a warning and the adapter is skipped.
    """
    return bool(_get_token())


def validate_config(config) -> bool:
    """Return True iff the platform config is usable.

    For MVP we only need the token; chat_id / polling interval come in
    later steps (F-04+).
    """
    return bool(_get_token())


def is_connected(config) -> bool:
    """Lightweight probe so ``hermes gateway status`` can show MAX as configured."""
    return bool(_get_token())


def _env_enablement() -> Optional[Dict[str, Any]]:
    """Seed ``PlatformConfig.extra`` from env vars before adapter construction.

    Without this hook, env-only setups do not show up in
    ``hermes gateway status`` or ``get_connected_platforms()`` until the
    adapter actually instantiates. The ``home_channel`` special key is
    promoted to a proper ``HomeChannel`` by the core loader.
    """
    if not _get_token():
        return None
    seed: Dict[str, Any] = {
        "api_base": _api_base(),
        "poll_timeout": MAX_POLL_TIMEOUT_SECONDS,
        "poll_types": MAX_POLL_TYPES,
    }
    home = os.environ.get("MAX_HOME_CHANNEL", "").strip()
    if home:
        seed["home_channel"] = {"chat_id": home, "name": "MAX home"}
    return seed


# ---------------------------------------------------------------------------
# Marker persistence
# ---------------------------------------------------------------------------

def _load_marker() -> Optional[int]:
    """Read the last successful marker from disk; None if absent/invalid."""
    try:
        if not MAX_MARKER_PATH.exists():
            return None
        raw = MAX_MARKER_PATH.read_text().strip()
        return int(raw)
    except (ValueError, OSError) as e:
        logger.warning("[MAX] marker file unreadable: %s", e)
        return None


def _save_marker(marker: int) -> None:
    """Persist the latest marker so a restart resumes cleanly."""
    try:
        MAX_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to .tmp then rename, so a crash mid-write
        # does not leave a zero-byte marker (which would rewind the
        # cursor and replay old updates).
        tmp = MAX_MARKER_PATH.with_suffix(MAX_MARKER_PATH.suffix + ".tmp")
        tmp.write_text(str(marker))
        tmp.replace(MAX_MARKER_PATH)
    except OSError as e:
        logger.warning("[MAX] marker save failed: %s", e)


# ---------------------------------------------------------------------------
# F-07b: Russian help-text helpers (adapter-level, not core)
# ---------------------------------------------------------------------------
# We do NOT override core's /help or /commands — core already registers them
# (see hermes_cli/commands.py:201, 199 and base.py:3516 bypass list). We add
# /menu and /roles which core does NOT know about — adapter intercepts them
# in _handle_update BEFORE MessageEvent dispatch, responds with Russian text
# via self.send(), and never reaches the gateway runner.
#
# Source of truth: ru help text lives here, not in core.

_HELP_RU = (
    "🤖 Hermes в MAX — шпаргалка команд\n"
    "\n"
    "📋 Основное:\n"
    "• /status — статус Hermes Gateway\n"
    "• /model — текущая модель\n"
    "• /new — начать новую сессию\n"
    "• /reset — сбросить контекст\n"
    "• /stop — остановить текущую задачу\n"
    "• /retry — повторить последний запрос\n"
    "• /undo — откатить последнее сообщение\n"
    "\n"
    "📬 MAX:\n"
    "• /sethome — сделать этот чат домашним каналом для cron, отчётов и уведомлений\n"
    "  ⚠️ Лучше отправлять, когда агент не выполняет задачу. Если пишет "
    "«Agent is running», сначала /stop или дождись ответа.\n"
    "\n"
    "🔮 Будущие роли (этап F-NEXT-AGENT-MESH):\n"
    "• /dev — кодер\n"
    "• /copy — копирайтер\n"
    "• /marketing — маркетолог\n"
    "• /crypto — криптоментор\n"
    "• /prompt — промт-инженер\n"
    "• /flora — креативщица Флора\n"
    "• /cron — задачи по расписанию\n"
    "• /pm — планирование и отчёты\n"
    "\n"
    "ℹ️ Также доступны: /menu (короткая справка), /roles (список ролей), "
    "/help и /commands — полный список от Hermes.\n"
    "\n"
    "✍️ Напиши обычную задачу текстом — Hermes выполнит её как агент. "
    "Для инструментов ты увидишь progress-сообщения, например 💻 terminal."
)


_MENU_RU = (
    "🤖 Hermes — меню\n"
    "\n"
    "📋 Команды:\n"
    "• /status, /model, /new, /reset, /stop, /retry, /undo\n"
    "• /menu, /roles, /help, /commands\n"
    "• /sethome — домашний канал для cron и отчётов\n"
    "\n"
    "🔮 Роли (скоро):\n"
    "/dev, /copy, /marketing, /crypto, /prompt, /flora, /cron, /pm\n"
    "\n"
    "✍️ Любой текст — задача агенту. Сложные задачи покажут progress: "
    "💻 terminal, 🔍 search, 📝 write_file, ⏳ Working."
)


_ROLES_RU = (
    "🔮 Hermes-роли (будут подключены на этапе F-NEXT-AGENT-MESH)\n"
    "\n"
    "• /dev — кодер\n"
    "• /copy — копирайтер\n"
    "• /marketing — маркетолог\n"
    "• /crypto — криптоментор\n"
    "• /prompt — промт-инженер\n"
    "• /flora — креативщица Флора\n"
    "• /cron — задачи по расписанию\n"
    "• /pm — планирование и отчёты\n"
    "\n"
    "Сейчас все эти роли уже работают в виде отдельных Hermes-профилей "
    "в /root/.hermes/profiles/ — MAX будет маршрутизировать в них "
    "команды после закрытия F-NEXT-AGENT-MESH."
)


# adapter-level intercept table: text -> (Russian response, requires_chat_id)
# Use a tuple to keep ordering stable and lookup fast. Only commands core
# does NOT know about belong here. /help and /commands belong to core.
_ADAPTER_HELP_COMMANDS: Dict[str, str] = {
    "/menu": _MENU_RU,
    "/roles": _ROLES_RU,
}

# F-TEAM-02: team management commands (intercepted before role dispatch)
_TEAM_COMMANDS = {"/team-add", "/team-cancel", "/team-confirm", "/team-list", "/team-rollback"}


# ---------------------------------------------------------------------------
# F-NEXT-03: Role registry — /copy → copywriter profile via channel_prompt
# ---------------------------------------------------------------------------
# Adapter-level intercept for role commands. When a user sends /copy <task>,
# we read the copywriter's SOUL.md, inject it as channel_prompt on the
# MessageEvent, and dispatch normally. The gateway runner creates an agent
# with the SOUL.md as ephemeral system prompt — no delegate_task needed,
# no core changes, no subprocess overhead.
#
# channel_prompt is merged into combined_ephemeral in run.py:~16940 and
# applied at API call time (never persisted to transcript). This is the
# same mechanism used by Discord channel_prompts and Telegram group context.

_ROLE_REGISTRY_PATH = Path(__file__).parent / "role_registry.yaml"
_ROLE_REGISTRY: Optional[Dict[str, Dict[str, Any]]] = None
_ROLE_COMMANDS: Dict[str, Dict[str, Any]] = {}  # command -> role entry


def _load_role_registry() -> None:
    """Load role_registry.yaml once. Only enabled roles are indexed."""
    global _ROLE_REGISTRY, _ROLE_COMMANDS
    if _ROLE_REGISTRY is not None:
        return
    try:
        import yaml  # type: ignore
        with open(_ROLE_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _ROLE_REGISTRY = data.get("roles", {}) if data else {}
        for _key, entry in (_ROLE_REGISTRY or {}).items():
            if entry.get("enabled") and entry.get("command"):
                _ROLE_COMMANDS[entry["command"].lower()] = entry
        logger.info(
            "[MAX] role registry loaded: %d enabled roles: %s",
            len(_ROLE_COMMANDS),
            list(_ROLE_COMMANDS.keys()),
        )
    except Exception as exc:
        logger.warning("[MAX] role registry load failed: %s", exc)
        _ROLE_REGISTRY = {}
        _ROLE_COMMANDS = {}


def _get_soul_content(soul_path: str) -> Optional[str]:
    """Read SOUL.md content for a role. Returns None on failure."""
    try:
        p = Path(soul_path).expanduser()
        if not p.exists():
            logger.warning("[MAX] SOUL.md not found: %s", soul_path)
            return None
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return None
        return content
    except Exception as exc:
        logger.warning("[MAX] failed to read SOUL.md %s: %s", soul_path, exc)
        return None


def _build_role_no_task_response(role: Dict[str, Any]) -> str:
    """Russian response when user sends /copy without a task."""
    emoji = role.get("emoji", "🤖")
    name = role.get("display_name", "Агент")
    cmd = role.get("command", "/role")
    desc = role.get("description", "")
    return (
        f"{emoji} {name}\n\n"
        f"Напиши задачу после команды.\n\n"
        f"Пример: {cmd} {desc.lower()[:40]}"
    )


# ---------------------------------------------------------------------------
# F-09: standalone_sender_fn — cron deliver=max support
# ---------------------------------------------------------------------------
# This module-level function is registered as ``standalone_sender_fn`` in
# ``register()`` below. It is called by core's
# ``tools/send_message_tool._send_via_adapter`` (and the discord-style chunked
# path) when the gateway runner is not in the same process as the caller
# (e.g. ``hermes cron`` runs separately from ``hermes gateway``). Without
# this hook, ``deliver=max`` cron jobs fail with
# "No live adapter for platform 'max'".
#
# Contract (verified against send_message_tool.py:530-561 and 660-684):
#   async (pconfig, chat_id, message, *,
#          thread_id=None, media_files=None, force_document=False) -> dict
#   Returns: {"success": True, "platform": "max", "chat_id": str,
#             "message_id": str, "message_ids": list[str]} | {"error": str}
#
# Notes on MAX:
#   - No Bearer prefix on Authorization (verified 2026-06-02).
#   - DM: ?user_id=<id>; channel/group: ?chat_id=<id>
#     (probe 2026-06-10: ?user= returns 400 "Unknown recipient").
#   - No native thread/attachment primitives — we accept thread_id and
#     media_files for signature parity but ignore them (MAX attachments
#     require a two-step upload — out of scope for F-09).
#   - We DO split into MAX_SEND_CHUNK_SIZE chunks ourselves because the
#     discord-style branch (send_message_tool.py:660) does not pre-chunk
#     before calling standalone_sender_fn. Defensive split keeps us
#     safe in both call paths.


def _standalone_post_one(
    *,
    api_base: str,
    token: str,
    route_kind: str,
    route_id: str,
    content: str,
    force_plain: bool = False,
) -> Dict[str, Any]:
    """Single ``POST /messages?<route>=<id>`` call. Returns a dict
    matching the standalone_sender_fn contract.

    Synchronous — call via ``asyncio.to_thread`` from the async wrapper
    to avoid blocking the event loop (same pattern as
    ``_post_action``/``_post_one`` in the adapter).
    """
    if route_kind == "user":
        param_name = "user_id"
    elif route_kind == "chat":
        param_name = "chat_id"
    else:
        return {"error": f"unknown route_kind {route_kind!r} (expected user|chat)"}

    payload: Dict[str, Any] = {"text": content, "notify": True}
    if not force_plain:
        payload["format"] = "markdown"

    url = f"{api_base}/messages?{param_name}={route_id}"
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HermesAgent/1.0 (max-platform-plugin/0.5.0/standalone)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                return {"error": f"HTTP {resp.status}: {raw[:200]}"}
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                return {"error": f"non-JSON response: {e}"}
            mid = (
                (data.get("message") or {})
                .get("body", {})
                .get("mid")
            )
            return {
                "success": True,
                "platform": "max",
                "chat_id": f"{route_kind}:{route_id}",
                "message_id": mid,
                "raw_response": data,
            }
    except urllib.error.HTTPError as e:
        err_body = (
            e.read().decode("utf-8", errors="replace")
            if e.fp is not None else ""
        )
        return {"error": f"HTTP {e.code}: {err_body[:200]}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"error": f"transport error: {e}"}
    except Exception as e:  # pragma: no cover — defensive
        return {"error": f"unexpected: {type(e).__name__}: {e}"}


async def _standalone_send(
    pconfig: Any,
    chat_id: str,
    message: str,
    *,
    thread_id: Optional[str] = None,
    media_files: Optional[List[str]] = None,
    force_document: bool = False,
) -> Dict[str, Any]:
    """Out-of-process MAX delivery — used by ``deliver=max`` cron jobs and
    the cross-platform ``send_message`` tool when no live adapter exists
    in this process.

    Thread_id and media_files are accepted for signature parity with the
    plugin spec but ignored on MAX (no native thread/attachment
    primitives; MAX attachments would need a separate two-step upload
    flow that is out of scope for F-09).

    Failure modes (all return ``{"error": str}`` — never raise):

    * Token missing (``MAX_BOT_TOKEN`` not set) → safe error, no leak
    * chat_id empty or unparseable → safe error
    * Transport / HTTP error → wrapped with status code, body truncated
    """
    if media_files:
        logger.info(
            "[MAX] standalone send: media_files not supported, dropping %d files",
            len(media_files),
        )
    if thread_id:
        logger.debug(
            "[MAX] standalone send: thread_id=%s (ignored on MAX)",
            thread_id,
        )

    token = _get_token()
    if not token:
        return {"error": "MAX_BOT_TOKEN not set in environment"}

    if not chat_id:
        return {"error": "chat_id is required for MAX standalone send"}

    # Use _parse_route so tagged "user:123" / "chat:456" / bare ids work
    # the same way as the live adapter (F-07a.1 fix).
    route_kind, route_id = _parse_route(chat_id)
    if not route_id:
        return {
            "error": f"could not resolve route from chat_id={chat_id!r}"
        }

    api_base = _api_base()
    chunks = _split_for_send(message or "", MAX_SEND_CHUNK_SIZE)
    sent_ids: List[Optional[str]] = []
    last_error: Optional[str] = None

    for idx, chunk in enumerate(chunks):
        result = await asyncio.to_thread(
            _standalone_post_one,
            api_base=api_base,
            token=token,
            route_kind=route_kind,
            route_id=route_id,
            content=chunk,
        )
        if "error" in result:
            # Markdown rejection → retry as plain text (F-06a behaviour)
            if "format" in str(result["error"]).lower():
                logger.info(
                    "[MAX] standalone chunk %d/%d: markdown rejected, retrying plain",
                    idx + 1, len(chunks),
                )
                result = await asyncio.to_thread(
                    _standalone_post_one,
                    api_base=api_base,
                    token=token,
                    route_kind=route_kind,
                    route_id=route_id,
                    content=chunk,
                    force_plain=True,
                )
                if "error" in result:
                    last_error = result["error"]
                    logger.warning(
                        "[MAX] standalone chunk %d/%d plain-retry failed: %s",
                        idx + 1, len(chunks), last_error,
                    )
                    return {
                        "error": f"chunk {idx+1}/{len(chunks)} plain-retry failed: {last_error}"
                    }
            else:
                # Non-markdown error → bail
                last_error = result["error"]
                logger.warning(
                    "[MAX] standalone chunk %d/%d failed: route=%s:%s err=%s",
                    idx + 1, len(chunks), route_kind, route_id, last_error,
                )
                return {"error": f"chunk {idx+1}/{len(chunks)} failed: {last_error}"}

        sent_ids.append(result.get("message_id"))
        logger.info(
            "[MAX] standalone sent: route=%s:%s chunk=%d/%d mid=%s text_len=%d",
            route_kind, route_id, idx + 1, len(chunks),
            _mask_id(result.get("message_id") or ""), len(chunk),
        )

    return {
        "success": True,
        "platform": "max",
        "chat_id": f"{route_kind}:{route_id}",
        "message_id": sent_ids[-1] if sent_ids else None,
        "message_ids": [m for m in sent_ids if m],
    }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class MaxAdapter(BasePlatformAdapter):
    """MAX platform adapter — polling, send, typing, progress append.

    Inherits ``BasePlatformAdapter`` directly so the gateway sees a
    well-formed adapter and we get ``_mark_connected``,
    ``_set_fatal_error``, ``_mark_disconnected``, ``is_connected`` and
    the busy/active-session bookkeeping for free.
    """  # end docstring

    # F-08b.1: tell core's progress_queue dispatcher (run.py:16513)
    # that we DO support message editing — even though MAX API has no
    # real edit endpoint.  Without this flag the core silently discards
    # all tool/progress messages for our platform.  Our ``edit_message``
    # override (below) falls back to plain ``send`` with anti-spam
    # guards.
    wants_progress_append: bool = True

    def __init__(self, config: Any) -> None:
        super().__init__(config=config, platform=Platform("max"))

        self._token: str = _get_token()
        self._api_base: str = _api_base()
        self._bot_id: Optional[int] = None
        self._bot_name: Optional[str] = None
        # Polling state (F-04.5)
        self._poll_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        # In-memory dedup (F-05a): update_id -> timestamp
        self._seen_updates: Dict[str, float] = {}
        # Resume marker (loaded on connect, updated on each successful poll)
        self._marker: Optional[int] = _load_marker()
        # F-07c: cache of numeric MAX chat_id per SessionSource chat_id
        # (SessionSource.chat_id is tagged "user:<id>" or "chat:<id>" but the
        # /chats/{chatId}/actions endpoint requires the raw numeric chat_id).
        # Populated on every dispatch; consumed by send_typing() when core's
        # _keep_typing loop calls us with the tagged chat_id only.
        self._last_typing_chat: Dict[str, int] = {}
        # F-NEXT-03: per-message role channel_prompt (one-shot)
        self._role_channel_prompt: Optional[str] = None
        # Rate-limit guard: log "typing unsupported" only once per recipient
        # so a 400-loop doesn't spam the log.
        self._typing_unsupported_logged: Set[str] = set()
        # F-08b.1: rate-limit progress messages (1 per chat per 3s)
        self._last_progress_sent: Dict[str, float] = {}

    # -- F-TEAM-02: Team command handler ----------------------------------

    async def _handle_team_command(
        self,
        cmd: str,
        full_text: str,
        sender: Dict[str, Any],
    ) -> str:
        """Handle /team-add, /team-cancel, /team-confirm, /team-list.

        Returns response text to send back to user.
        """
        try:
            from .team_manager import core as tm_core  # type: ignore
        except ImportError:
            from team_manager import core as tm_core  # type: ignore

        user_id = str(sender.get("user_id", ""))

        # Security: only allowed users
        allowed = os.environ.get("MAX_ALLOWED_USERS", "")
        if user_id not in allowed.split(","):
            return "⚠️ Команда доступна только авторизованным пользователям."

        if cmd == "/team-add":
            return self._team_add(full_text, user_id, tm_core)
        elif cmd == "/team-cancel":
            return self._team_cancel(full_text, user_id, tm_core)
        elif cmd == "/team-confirm":
            return self._team_confirm(full_text, user_id, tm_core)
        elif cmd == "/team-list":
            return self._team_list(tm_core)
        elif cmd == "/team-rollback":
            return self._team_rollback(full_text, user_id, tm_core)
        else:
            return f"⚠️ Неизвестная команда: {cmd}"

    def _team_add(self, text: str, user_id: str, tm) -> str:
        """Parse, validate, create pending state, return preview."""
        params, parse_err = tm.parse_team_add_args(text)
        if parse_err:
            return tm.format_parse_error(parse_err)

        name = params.get("name", "")
        route = params.get("route", "")
        title = params.get("title", "")
        soul = params.get("soul", "")

        if not soul:
            return tm.format_parse_error(
                "SOUL отсутствует. Добавь SOUL:текст_инструкции в конец команды.\n\n"
                "Пример:\n/team-add name=designer route=/design "
                "title=\"Дизайнер\" SOUL:Ты дизайнер визуалов..."
            )

        result = tm.validate_team_add(name, route, title, soul)
        if not result.ok:
            return tm.format_validation_errors(result.errors)

        # Create pending state
        try:
            record = tm.create_pending(
                user_id=user_id,
                name=result.fields["name"],
                route=result.fields["route"],
                title=result.fields["title"],
                soul=result.fields["soul"],
            )
            return tm.format_preview(record)
        except Exception as e:
            return f"❌ Ошибка создания pending: {e}"

    def _team_cancel(self, text: str, user_id: str, tm) -> str:
        """Cancel and delete pending state."""
        parts = text.strip().split(maxsplit=1)
        pending_id = parts[1].strip() if len(parts) > 1 else ""

        if not pending_id:
            return "⚠️ Формат: /team-cancel <pending_id>"

        record = tm.read_pending(pending_id)
        if not record:
            return tm.format_cancel_not_found(pending_id)

        # Verify creator
        if record.get("creator_user_id") != user_id:
            return "⚠️ Можно отменить только свои запросы."

        tm.delete_pending(pending_id)
        return tm.format_cancel_ok(pending_id)

    def _team_confirm(self, text: str, user_id: str, tm) -> str:
        """F-TEAM-03: Real confirm — creates profile + registry entry."""
        parts = text.strip().split(maxsplit=1)
        pending_id = parts[1].strip() if len(parts) > 1 else ""

        if not pending_id:
            return "⚠️ Формат: /team-confirm <pending_id>"

        success, msg = tm.confirm_pending(pending_id, user_id)
        return msg

    def _team_rollback(self, text: str, user_id: str, tm) -> str:
        """F-TEAM-03: Rollback — removes profile + registry entry."""
        parts = text.strip().split(maxsplit=1)
        name = parts[1].strip() if len(parts) > 1 else ""

        if not name:
            return "⚠️ Формат: /team-rollback <agent_name>"

        success, msg = tm.rollback_agent(name, user_id)
        return msg

    def _team_list(self, tm) -> str:
        """List all pending requests."""
        pending = tm.list_pending()
        if not pending:
            return tm.format_no_pending()

        lines = ["📋 Pending запросы:", ""]
        for r in pending:
            lines.append(
                f"  • {r['id']}  {r['route']} → {r['title']} "
                f"(soul={r.get('soul_len', '?')} by user {r.get('creator_user_id', '?')})"
            )
        lines.append("")
        lines.append("/team-cancel <id> для отмены")
        return "\n".join(lines)

    # -- Stub abstract methods (required by BasePlatformAdapter ABC) ----
    # Full implementations land in F-05b (handle_message via real event
    # dispatch) and F-06 (POST /messages). For step 2 we only need the
    # class to be instantiable so the gateway can call connect()/disconnect().

    # -- Send (F-06a) -----------------------------------------------------

    async def send(  # type: ignore[override]
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SendResult":
        """Send a text message to a MAX recipient via ``POST /messages``.

        Chunking: any message over ``MAX_SEND_CHUNK_SIZE`` (3900 chars)
        is split on paragraph boundaries, then word boundaries, then
        hard-cut. Each chunk is a separate ``POST /messages`` call.

        Format: tries ``format=markdown`` first. If MAX rejects the
        body (HTTP 400 mentioning format/markdown), the chunk is
        resent as plain text. The first chunk's ``message_id`` is
        returned so callers can edit it; subsequent chunks are
        recorded in ``continuation_message_ids`` for the gateway
        base-class retry/edit machinery.

        Routing: ``chat_id`` may be a bare integer (a MAX chat_id or
        user_id) or a ``"user:<id>"`` / ``"chat:<id>"`` tagged string
        (preferred — set by ``_handle_update`` so DM goes via
        ``?user_id=`` and group/channel via ``?chat_id=``). When
        ``metadata`` carries ``{"max_route_kind": "user"|"chat",
        "max_route_id": "..."}`` those override the chat_id string
        parsing. Verified 2026-06-10: both query params return 200
        for the same DM recipient, but using the wrong one is fragile
        (MAX may reject with ``Unknown recipient`` on some recipient
        types — confirmed pre-fix).

        Auth header: ``Authorization: <token>`` (no Bearer prefix —
        verified 2026-06-02 in skill `devops/messenger-max`).
        """
        if not chat_id:
            return SendResult(success=False, error="send() called with empty chat_id")
        if not content:
            return SendResult(success=False, error="send() called with empty content")

        route_kind, route_id = _parse_route(chat_id, metadata)
        if not route_id:
            return SendResult(
                success=False,
                error=f"send() could not resolve route from chat_id={chat_id!r}",
            )

        chunks = _split_for_send(content, MAX_SEND_CHUNK_SIZE)
        sent_ids: list = []
        last_error: Optional[str] = None

        for idx, chunk in enumerate(chunks):
            result = await self._post_one(
                route_kind=route_kind, route_id=route_id, content=chunk,
            )
            if not result.success and result.error and "format" in result.error.lower():
                # markdown was rejected — retry as plain text
                logger.info(
                    "[MAX] outbound chunk %d/%d: markdown rejected, retrying as plain",
                    idx + 1, len(chunks),
                )
                result = await self._post_one(
                    route_kind=route_kind, route_id=route_id,
                    content=chunk, force_plain=True,
                )
            if not result.success:
                last_error = result.error
                logger.warning(
                    "[MAX] outbound chunk %d/%d failed: %s (route=%s:%s, chunk_len=%d)",
                    idx + 1, len(chunks), result.error, route_kind, route_id, len(chunk),
                )
                return SendResult(
                    success=False,
                    error=f"chunk {idx+1}/{len(chunks)} failed: {last_error}",
                )
            if result.message_id:
                sent_ids.append(result.message_id)
            logger.info(
                "[MAX] outbound sent: route=%s:%s chunk=%d/%d mid=%s text_len=%d",
                route_kind, route_id, idx + 1, len(chunks),
                _mask_id(result.message_id or ""), len(chunk),
            )

        return SendResult(
            success=True,
            message_id=sent_ids[-1] if sent_ids else None,
            continuation_message_ids=tuple(sent_ids[:-1]),
        )

    async def _post_one(
        self,
        *,
        route_kind: str,
        route_id: str,
        content: str,
        force_plain: bool = False,
    ) -> "SendResult":
        """Single ``POST /messages?<route_kind>=<route_id>`` call.

        ``route_kind`` is ``"user"`` for DM (recipient is a user_id)
        or ``"chat"`` for group/channel (recipient is a chat_id).
        Verified 2026-06-10: both produce 200 OK on the same DM
        recipient, but only the right one is reliable across all
        recipient types (the wrong one returns ``400 Unknown
        recipient``).

        Returns ``SendResult`` with ``success`` and (on 2xx) the
        ``message.body.mid`` as ``message_id``. Body shape::

            {"text": ..., "format": "markdown"|None, "notify": true}

        No Bearer prefix, no ``payload`` wrapper — raw body, route
        in the query string only (verified 2026-06-02 / 2026-06-10).
        """
        payload: Dict[str, Any] = {
            "text": content,
            "notify": True,
        }
        if not force_plain:
            payload["format"] = "markdown"

        # F-07a.1 fix: explicit param-name mapping. Earlier revisions
        # used ``f"?{route_kind}={route_id}"`` which produced
        # ``?user=<id>`` — MAX does NOT recognise ``user=`` and
        # returned 400 "Unknown recipient" (verified 2026-06-10).
        # The correct query param names are ``user_id`` (DM) and
        # ``chat_id`` (group/channel). Probe 2026-06-10 confirmed
        # MAX accepts ``?user_id=`` for a dialog recipient and
        # ``?chat_id=`` for a chat/group recipient.
        if route_kind == "user":
            param_name = "user_id"
        elif route_kind == "chat":
            param_name = "chat_id"
        else:
            return SendResult(
                success=False,
                error=f"unknown route_kind {route_kind!r} (expected 'user' or 'chat')",
            )

        url = f"{self._api_base}/messages?{param_name}={route_id}"
        logger.info(
            "[MAX] outbound route=%s param=%s text_len=%d",
            f"{route_kind}:{route_id}", param_name, len(content),
        )
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            method="POST",
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HermesAgent/1.0 (max-platform-plugin/0.3.1)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if resp.status >= 400:
                    return SendResult(
                        success=False, error=f"HTTP {resp.status}: {raw[:200]}",
                    )
                data = json.loads(raw)
                mid = (
                    (data.get("message") or {})
                    .get("body", {})
                    .get("mid")
                )
                return SendResult(success=True, message_id=mid, raw_response=data)
        except urllib.error.HTTPError as e:
            err_body = (
                e.read().decode("utf-8", errors="replace")
                if e.fp is not None else ""
            )
            return SendResult(
                success=False,
                error=f"HTTP {e.code}: {err_body[:200]}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return SendResult(
                success=False, error=f"{type(e).__name__}: {e}",
            )
        except Exception as e:  # pragma: no cover — defensive
            return SendResult(
                success=False, error=f"{type(e).__name__}: {e}",
            )

    async def _post_action(self, *, chat_id: int, action: str) -> bool:
        """Fire-and-forget ``POST /chats/{chatId}/actions`` for typing/etc.

        Returns True on 2xx, False on any error. Never raises — the caller
        (``send_typing``) is in the core agent-typing loop and exceptions
        here would propagate into the gateway event loop.

        ``chat_id`` MUST be a numeric MAX chat_id (DM or channel). Tagged
        ``"user:<id>"`` / ``"chat:<id>"`` strings are NOT valid for this
        endpoint — the resolver lives in ``send_typing`` via
        ``self._last_typing_chat``.
        """
        url = f"{self._api_base}/chats/{int(chat_id)}/actions"
        body_bytes = json.dumps({"action": action}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            method="POST",
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HermesAgent/1.0 (max-platform-plugin/0.4.0)",
            },
        )

        def _do_post() -> int:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                resp.read()  # drain
                return int(resp.status)

        try:
            status = await asyncio.to_thread(_do_post)
            if status >= 400:
                logger.debug(
                    "[MAX] typing action HTTP %s for chat_id=%s action=%s",
                    status, chat_id, action,
                )
                return False
            return True
        except urllib.error.HTTPError as e:
            err_body = (
                e.read().decode("utf-8", errors="replace")
                if e.fp is not None else ""
            )
            logger.debug(
                "[MAX] typing action HTTP %s chat_id=%s: %s",
                e.code, chat_id, err_body[:120],
            )
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.debug(
                "[MAX] typing action transport error chat_id=%s: %s",
                chat_id, e,
            )
            return False
        except Exception as e:  # pragma: no cover — defensive
            logger.debug(
                "[MAX] typing action unexpected error chat_id=%s: %s",
                chat_id, e,
            )
            return False

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """F-05b placeholder. Return a minimal chat dict so the gateway
        does not crash if a session is constructed for this chat."""
        return {"name": str(chat_id), "type": "dm", "chat_id": str(chat_id)}

    async def send_typing(  # type: ignore[override]
        self, chat_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a "typing…" indicator via ``POST /chats/{chatId}/actions``.

        Invoked by ``BasePlatformAdapter._keep_typing`` (base.py:2752) every
        ~2s while the agent is thinking. ``chat_id`` is the SessionSource
        chat_id (tagged — ``"user:12345678"`` for DM, ``"chat:-XXX"`` for
        groups/channels), but MAX's actions endpoint requires the raw
        numeric ``chat_id`` (verified 2026-06-10: both ``?user_id=`` and
        ``?chat_id=`` rejected for actions; only ``/chats/<numeric>`` works).

        We resolve the numeric via the per-adapter cache populated in
        ``_handle_update``. On a cache miss (synthetic event, restart with
        no fresh incoming update) we no-op + DEBUG-log — never crash the
        typing loop.
        """
        # Resolve numeric MAX chat_id for the /chats/{chatId}/actions call
        numeric = self._last_typing_chat.get(str(chat_id))
        if numeric is None:
            logger.debug(
                "[MAX] typing skipped: no cached numeric chat_id for %r",
                chat_id,
            )
            return None

        try:
            await self._post_action(chat_id=int(numeric), action="typing_on")
        except Exception as e:  # defensive — never break the agent loop
            key = f"{chat_id}:{type(e).__name__}"
            if key not in self._typing_unsupported_logged:
                self._typing_unsupported_logged.add(key)
                logger.debug(
                    "[MAX] typing action failed (suppressing further): %s",
                    e,
                )
            return None

    # -- F-08b.1: progress append (edit_message fallback) ----------------

    async def edit_message(  # type: ignore[override]
        self,
        chat_id: str,
        message_id: Any,
        content: str,
        finalize: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Progress-append fallback for tool/activity messages.

        MAX API has no edit endpoint, so we override ``edit_message`` to
        prevent core from silently discarding progress_queue items
        (run.py:16513).  Instead of editing, we *append* the progress
        line as a new message — with anti-spam guards:

        * Feature flag: ``MAX_PROGRESS_APPEND=1`` must be set in .env.
        * ``finalize=True`` → no-op (core already sends the final
          response separately; we avoid a duplicate).
        * Empty / whitespace-only content → no-op.
        * ``len(content) > 240`` → no-op (only short tool previews).
        * Rate-limit: max 1 progress message per chat_id per 3 seconds.
        """
        # --- feature flag gate ---
        if os.environ.get("MAX_PROGRESS_APPEND") != "1":
            return SendResult(success=True)  # silent no-op

        # --- content guards ---
        if finalize:
            logger.debug("[MAX] edit_message: finalize=True, skip")
            return SendResult(success=True)  # core sends final answer itself
        if not content or not content.strip():
            return SendResult(success=True)
        if len(content) > 240:
            logger.debug("[MAX] edit_message: too long (%d), skip", len(content))
            return SendResult(success=True)  # too long for a progress bubble

        # --- rate-limit: 1 per chat per 3 seconds ---
        now = time.monotonic()
        last_ts = self._last_progress_sent.get(chat_id, 0.0)
        if (now - last_ts) < 3.0:
            logger.debug("[MAX] edit_message: rate-limited (%.1fs), skip", now - last_ts)
            return SendResult(success=True)  # suppressed by rate-limit
        self._last_progress_sent[chat_id] = now

        # --- append as new message ---
        logger.info("[MAX] edit_message: sending progress route=%s len=%d", chat_id, len(content))
        try:
            result = await self.send(chat_id, content, metadata=metadata)
            if result.success:
                logger.info(
                    "[MAX] progress append sent route=%s len=%d",
                    chat_id, len(content),
                )
            return result
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("[MAX] progress append failed: %s", e)
            return SendResult(success=True)  # don't break the agent loop

    # -- Connection lifecycle (F-04 + F-04.5) ----------------------------

    async def connect(self) -> bool:
        """Validate token via GET /me, then start the polling task."""
        url = f"{self._api_base}/me"
        logger.info("[MAX] connecting: GET %s (token=%s)", url, _mask(self._token))
        try:
            data = await asyncio.to_thread(
                _http_get_json, url, self._token, timeout=15.0
            )
        except _AuthError as e:
            self._set_fatal_error(  # type: ignore[attr-defined]
                "max_unauthorized",
                f"MAX rejected the token (HTTP {e.status}). Check MAX_BOT_TOKEN.",
                retryable=False,
            )
            logger.error(
                "[MAX] auth failed: HTTP %s — token rejected. Check MAX_BOT_TOKEN.",
                e.status,
            )
            return False
        except _TransportError as e:
            self._set_fatal_error(  # type: ignore[attr-defined]
                "max_transport_error",
                f"MAX /me transport error: {e}",
                retryable=True,
            )
            logger.warning("[MAX] /me transport error (retryable): %s", e)
            return False
        except Exception as e:  # pragma: no cover — defensive
            self._set_fatal_error(  # type: ignore[attr-defined]
                "max_unexpected",
                f"MAX /me unexpected error: {type(e).__name__}: {e}",
                retryable=False,
            )
            logger.exception("[MAX] /me unexpected error")
            return False

        self._bot_id = data.get("user_id")
        self._bot_name = data.get("first_name") or data.get("name") or "unknown"
        is_bot = data.get("is_bot", True)
        logger.info(
            "[MAX] /me ok: bot_id=%s bot_name=%s is_bot=%s (marker resume=%s)",
            self._bot_id, self._bot_name, is_bot, self._marker,
        )

        # Start polling task (F-04.5)
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="max-poll-loop"
        )

        self._mark_connected()  # type: ignore[attr-defined]
        return True

    async def disconnect(self) -> None:
        """Stop the polling task and mark disconnected."""
        logger.info("[MAX] disconnect: stopping polling task")
        self._stop_event.set()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("[MAX] poll task exited with error: %s", e)
        self._poll_task = None
        self._seen_updates.clear()
        self._mark_disconnected()  # type: ignore[attr-defined]

    # -- Polling loop (F-04.5) -------------------------------------------

    async def _poll_loop(self) -> None:
        """Long-polling loop with exponential backoff on transport errors.

        Stops cleanly when ``self._stop_event`` is set (gateway shutdown
        or adapter ``disconnect()``). On a fatal auth error, sets
        ``_set_fatal_error(retryable=False)`` and returns.
        """
        backoff_idx = 0
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
                backoff_idx = 0  # reset on a successful round-trip
            except asyncio.CancelledError:
                raise
            except _AuthError as e:
                # Token was working at /me but rejected by /updates. Stop.
                self._set_fatal_error(  # type: ignore[attr-defined]
                    "max_unauthorized",
                    f"MAX /updates auth failed: HTTP {e.status}",
                    retryable=False,
                )
                logger.error("[MAX] /updates auth failed: HTTP %s", e.status)
                return
            except _TransportError as e:
                delay = POLL_BACKOFF[min(backoff_idx, len(POLL_BACKOFF) - 1)]
                logger.warning(
                    "[MAX] /updates transport error: %s — retry in %ds",
                    e, delay,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay
                    )
                    return  # stop_event was set during backoff
                except asyncio.TimeoutError:
                    pass
                backoff_idx += 1
            except Exception as e:  # pragma: no cover — defensive
                logger.exception("[MAX] /updates unexpected error")
                await asyncio.sleep(2)

    async def _poll_once(self) -> None:
        """Perform one long-poll request and dispatch each update.

        F-05a scope: log update metadata only. ``self.handle_message``
        is intentionally NOT called — that lands in F-05b.
        """
        params = f"timeout={MAX_POLL_TIMEOUT_SECONDS}&types={MAX_POLL_TYPES}"
        if self._marker is not None:
            params += f"&marker={self._marker}"
        url = f"{self._api_base}/updates?{params}"

        # Run the blocking urllib call in a thread so the event loop
        # stays responsive to the stop event.
        data = await asyncio.to_thread(
            _http_get_json, url, self._token,
            timeout=MAX_POLL_TIMEOUT_SECONDS + 10.0,
        )

        updates = data.get("updates") or []
        new_marker = data.get("marker")
        if new_marker is not None:
            self._marker = int(new_marker)
            _save_marker(self._marker)

        for upd in updates:
            await self._handle_update(upd)

    async def _handle_update(self, upd: Dict[str, Any]) -> None:
        """Process one update from MAX. F-05a: log only, no dispatch.

        Deduplication strategy:
          - Prefer ``update_id`` (string form, set by MAX).
          - Fallback: hash of ``(timestamp, message_id)`` so we still
            dedup when MAX omits ``update_id`` for older events.
        Echo filter: skip updates whose sender equals our own bot_id.
        """
        update_type = upd.get("update_type") or "unknown"
        update_id = (
            str(upd.get("update_id"))
            if upd.get("update_id") is not None
            else None
        )

        # Dedup
        if update_id is None:
            ts = upd.get("timestamp")
            mid = (upd.get("message") or {}).get("body", {}).get("mid")
            if ts is not None and mid is not None:
                update_id = f"hash:{ts}:{mid}"
            else:
                update_id = f"ts:{upd.get('timestamp', time.time())}"

        if self._is_duplicate(update_id):
            logger.debug(
                "[MAX] duplicate update skipped: type=%s id=%s",
                update_type, _mask_id(update_id),
            )
            return

        # Echo filter — sender == our own bot id (in chat messages)
        if update_type in ("message_created", "message_callback"):
            sender_id = (
                (upd.get("message") or {})
                .get("sender", {})
                .get("user_id")
            )
            if sender_id is not None and sender_id == self._bot_id:
                logger.debug(
                    "[MAX] echo from bot itself skipped: type=%s",
                    update_type,
                )
                return

        # Extract just enough metadata to log — never the full text in
        # case the user pasted a secret. Length only.
        meta = _extract_update_meta(upd, update_type, self._bot_id)

        logger.info(
            "[MAX] received update: type=%s update_id=%s chat_id=%s "
            "user_id=%s message_id=%s text_len=%s marker=%s",
            meta["update_type"],
            _mask_id(update_id),
            meta["chat_id"],
            meta["user_id"],
            meta["message_id"],
            meta["text_len"],
            self._marker,
        )

        # F-05a: log metadata only (text_len, no full text).
        # F-05b: build Hermes MessageEvent and dispatch via
        # self.handle_message(event). The base-class handler routes to
        # the gateway runner, which dispatches slash commands (/status,
        # /model, /new, /reset) directly and runs the agent loop for
        # regular text. We do NOT parse or intercept commands here —
        # they pass through as plain text and the gateway decides.

        # Re-read the body for dispatch. We hold the full text ONLY
        # inside this scope (build MessageEvent) and never log it.
        msg = upd.get("message") or {}
        body = msg.get("body") or {}
        recipient = msg.get("recipient") or {}
        sender = msg.get("sender") or {}
        text = (body.get("text") or "").strip()
        # If the update has no text (e.g. a service notification with
        # only attachments or buttons), we still log but skip dispatch.
        if not text:
            logger.debug(
                "[MAX] skipping dispatch: empty text body (update_type=%s)",
                update_type,
            )
            return

        # F-07b: adapter-level intercept for Russian help commands.
        # We respond BEFORE MessageEvent dispatch so the text never reaches
        # the gateway runner (and never gets logged as user content).
        # Only commands core does NOT know about are intercepted here
        # (e.g. /menu, /roles). Core commands like /help, /commands,
        # /status, /model, /new, /reset, /stop, /retry, /undo pass through
        # unchanged.
        first_token = text.split(maxsplit=1)[0].lower()
        if first_token in _ADAPTER_HELP_COMMANDS:
            response_text = _ADAPTER_HELP_COMMANDS[first_token]
            # Build minimal chat_id/route for self.send()
            # We need route_kind/route_id from recipient info
            rct = recipient.get("chat_type")
            try:
                if rct == "dialog":
                    route_chat_id = f"user:{sender.get('user_id')}"
                else:
                    cid = recipient.get("chat_id")
                    route_chat_id = (
                        f"chat:{cid}" if cid is not None
                        else f"user:{sender.get('user_id')}"
                    )
                logger.info(
                    "[MAX] adapter-help intercept: cmd=%s route=%s len=%d",
                    first_token, route_chat_id, len(response_text),
                )
                await self.send(chat_id=route_chat_id, content=response_text)
            except Exception as e:  # pragma: no cover — defensive
                logger.warning(
                    "[MAX] adapter-help intercept failed: cmd=%s err=%s",
                    first_token, e,
                )
            return  # never dispatch to gateway runner

        # F-TEAM-02: /team-add, /team-cancel, /team-confirm, /team-list
        # Intercepted before role routing. Dry-run only: no profile/registry writes.
        if first_token in _TEAM_COMMANDS:
            try:
                try:
                    from .team_manager import core as tm_core  # type: ignore
                except ImportError:
                    from team_manager import core as tm_core  # type: ignore
                resp_text = await self._handle_team_command(
                    first_token, text, sender
                )
                rct = recipient.get("chat_type")
                if rct == "dialog":
                    rt_chat_id = f"user:{sender.get('user_id')}"
                else:
                    cid = recipient.get("chat_id")
                    rt_chat_id = (
                        f"chat:{cid}" if cid is not None
                        else f"user:{sender.get('user_id')}"
                    )
                await self.send(chat_id=rt_chat_id, content=resp_text)
                logger.info(
                    "[MAX] team intercept: cmd=%s route=%s len=%d",
                    first_token, rt_chat_id, len(resp_text),
                )
            except Exception as e:
                logger.warning(
                    "[MAX] team intercept failed: cmd=%s err=%s",
                    first_token, e,
                )
            return  # never dispatch to gateway runner

        # F-NEXT-03: Role command intercept (/copy → copywriter etc.)
        # After help-command check, before normal dispatch.
        # Reads SOUL.md from the role's profile, injects as channel_prompt
        # on the MessageEvent, and dispatches to gateway runner normally.
        # The runner merges channel_prompt into the agent's ephemeral system
        # prompt — so the agent "becomes" that role for this message only.
        _load_role_registry()
        if first_token in _ROLE_COMMANDS:
            role_entry = _ROLE_COMMANDS[first_token]
            task_text = text[len(first_token):].strip()

            # No task provided → show role-specific help
            if not task_text:
                no_task_resp = _build_role_no_task_response(role_entry)
                try:
                    rct = recipient.get("chat_type")
                    if rct == "dialog":
                        rt_chat_id = f"user:{sender.get('user_id')}"
                    else:
                        cid = recipient.get("chat_id")
                        rt_chat_id = (
                            f"chat:{cid}" if cid is not None
                            else f"user:{sender.get('user_id')}"
                        )
                    await self.send(chat_id=rt_chat_id, content=no_task_resp)
                except Exception as e:
                    logger.warning(
                        "[MAX] role no-task response failed: cmd=%s err=%s",
                        first_token, e,
                    )
                return  # don't dispatch

            # Read SOUL.md for the role
            soul_content = _get_soul_content(role_entry["soul_path"])
            if not soul_content:
                fallback = (
                    f"⚠️ Не удалось загрузить профиль "
                    f"«{role_entry.get('display_name', first_token)}». "
                    f"Задача отправлена обычному агенту."
                )
                try:
                    rct = recipient.get("chat_type")
                    if rct == "dialog":
                        rt_chat_id = f"user:{sender.get('user_id')}"
                    else:
                        cid = recipient.get("chat_id")
                        rt_chat_id = (
                            f"chat:{cid}" if cid is not None
                            else f"user:{sender.get('user_id')}"
                        )
                    await self.send(chat_id=rt_chat_id, content=fallback)
                except Exception:
                    pass
                # Fall through to normal dispatch (no channel_prompt)
            else:
                # Inject role prefix into task text for clarity
                emoji = role_entry.get("emoji", "")
                role_name = role_entry.get("display_name", "")
                role_desc = role_entry.get("description", "")
                enriched_text = (
                    f"{emoji} {role_name}: {task_text}"
                )

                # Log only metadata, not full text
                logger.info(
                    "[MAX] role intercept: cmd=%s role=%s soul_len=%d task_len=%d",
                    first_token, role_entry.get("profile"),
                    len(soul_content), len(task_text),
                )

                # Build MessageEvent with channel_prompt = SOUL.md content
                # and enriched task text. Dispatch to gateway runner below.
                # We modify 'text' so the rest of _handle_update uses it.
                text = enriched_text
                # Store channel_prompt for injection when building event
                self._role_channel_prompt = (
                    f"Ты сейчас выступаешь в роли: {role_name} ({role_desc}).\n\n"
                    f"--- НАЧАЛО SOUL.md ---\n{soul_content}\n--- КОНЕЦ SOUL.md ---\n\n"
                    f"Следуй своей роли. Отвечай в стиле {role_name}."
                )
            # Fall through — normal dispatch continues below with modified text

        mid = body.get("mid")
        ts_ms = msg.get("timestamp")  # MAX uses Unix milliseconds
        try:
            timestamp = (
                datetime.fromtimestamp(int(ts_ms) / 1000.0)
                if ts_ms is not None
                else datetime.now()
            )
        except (ValueError, TypeError, OSError):
            timestamp = datetime.now()

        # chat_id / route resolution for outbound routing. MAX
        # ``recipient.chat_type`` is one of:
        #   "dialog" — DM with the bot (use user_id=<sender.user_id>)
        #   "chat"   — public channel (use chat_id=<recipient.chat_id>)
        #   "group"  — multi-user group (use chat_id=<recipient.chat_id>)
        # F-07a fix: route_kind + route_id are carried in MessageEvent
        # source.metadata so the gateway response goes via the SAME
        # query param shape as the user's incoming path. Verified
        # 2026-06-10: the wrong param returns 400 "Unknown recipient"
        # for some recipient types, even though the bot has access to
        # the underlying chat/user.
        recipient_chat_type = recipient.get("chat_type")
        if recipient_chat_type == "dialog":
            route_kind = "user"
            route_id = str(sender.get("user_id") or "")
            chat_type = "dm"
        elif recipient_chat_type in ("chat", "channel", "group"):
            route_kind = "chat"
            route_id = str(recipient.get("chat_id") or "")
            chat_type = (
                "channel" if recipient_chat_type in ("chat", "channel")
                else "group"
            )
        else:
            # Unknown / missing chat_type — fall back to user_id
            # (more common: DMs without explicit chat_type).
            route_kind = "user"
            route_id = str(sender.get("user_id") or "")
            chat_type = "dm"

        if not route_id:
            logger.warning(
                "[MAX] skipping dispatch: empty route_id "
                "(update_type=%s update_id=%s)",
                update_type, _mask_id(str(upd.get("update_id", ""))),
            )
            return

        # chat_id (used by SessionSource + session_keying) is a
        # route-tagged string so our send() picks the right query
        # param. Bare integers also work via _parse_route's fallback
        # to kind="chat" (legacy), but DM requires user_id, so we
        # always tag explicitly here. _is_user_authorized uses
        # source.user_id (not chat_id), so tagging chat_id does not
        # break auth checks.
        chat_id = f"{route_kind}:{route_id}"

        # chat_name: MAX doesn't give a human-readable chat name in
        # the update. Use sender display name as a stable label.
        chat_name = (
            sender.get("name") or sender.get("username") or str(route_id)
        )

        source = self.build_source(
            chat_id=chat_id,
            chat_name=chat_name,
            chat_type=chat_type,
            user_id=str(sender.get("user_id") or ""),
            user_name=sender.get("name") or sender.get("username"),
            message_id=str(mid) if mid else None,
        )

        logger.debug(
            "[MAX] resolved route: kind=%s id=%s chat_type=%s",
            route_kind, route_id, chat_type,
        )

        event = MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=source,
            message_id=str(mid) if mid else None,
            platform_update_id=(
                int(upd["update_id"]) if isinstance(upd.get("update_id"), int) else None
            ),
            raw_message=upd,
            timestamp=timestamp,
            channel_prompt=getattr(self, "_role_channel_prompt", None),
        )

        # Clear role channel_prompt after use (one-shot, per-message)
        if hasattr(self, "_role_channel_prompt"):
            del self._role_channel_prompt

        logger.info(
            "[MAX] dispatching to gateway: chat_id=%s user_id=%s route=%s:%s "
            "text_len=%s mid=%s marker=%s",
            chat_id, source.user_id, route_kind, route_id, len(text),
            _mask_id(str(mid) if mid else ""), self._marker,
        )
        # F-07c: cache numeric MAX chat_id for the typing-indicator path
        # (core's _keep_typing will call self.send_typing with the tagged
        # chat_id only, so we map it back to the numeric here).
        _rcid = recipient.get("chat_id")
        if _rcid is not None:
            try:
                self._last_typing_chat[chat_id] = int(_rcid)
            except (TypeError, ValueError):
                pass
        await self.handle_message(event)

    # -- Dedup ------------------------------------------------------------

    def _is_duplicate(self, update_id: str) -> bool:
        now = time.time()
        # Prune stale entries opportunistically
        if len(self._seen_updates) > MAX_DEDUP_MAX_SIZE:
            cutoff = now - MAX_DEDUP_TTL_SECONDS
            self._seen_updates = {
                k: v for k, v in self._seen_updates.items() if v > cutoff
            }
        if update_id in self._seen_updates:
            return True
        self._seen_updates[update_id] = now
        return False


# ---------------------------------------------------------------------------
# Minimal stdlib HTTP client — kept across steps; replace with httpx later
# if we need async-native HTTP, but stdlib is fine for one request per
# long-poll cycle.
# ---------------------------------------------------------------------------

class _AuthError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class _TransportError(Exception):
    pass


def _http_get_json(url: str, token: str, *, timeout: float) -> Dict[str, Any]:
    """GET ``url`` with ``Authorization: <token>`` (no Bearer prefix — verified 2026-06-02)."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": token,
            "Accept": "application/json",
            "User-Agent": "HermesAgent/1.0 (max-platform-plugin/0.2.0)",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise _AuthError(resp.status, body)
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp is not None else ""
        raise _AuthError(e.code, body) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _TransportError(f"{type(e).__name__}: {e}") from None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_id(s: str, keep: int = 6) -> str:
    """Show only the first ``keep`` chars of an ID (avoids logging full mid./update_id)."""
    if not s:
        return "<empty>"
    if len(s) <= keep:
        return s
    return f"{s[:keep]}…({len(s)})"


def _parse_route(
    chat_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Resolve MAX routing from ``chat_id`` + ``metadata``.

    Returns ``(route_kind, route_id)`` where ``route_kind`` is one of
    ``"user"`` (DM via ``?user_id=``) or ``"chat"`` (group/channel
    via ``?chat_id=``).  Verified 2026-06-10: MAX accepts both query
    params on a DM recipient, but mixing them up across recipient
    types returns ``400 Unknown recipient`` — so we set them
    explicitly per MAX's own ``recipient.chat_type`` contract.

    Precedence:
      1. ``metadata["max_route_kind"]`` / ``metadata["max_route_id"]``
         — preferred, set by ``_handle_update`` for every incoming
         update so the gateway response targets the same recipient
         shape the user used to reach the bot.
      2. ``chat_id`` parsed as ``"user:<id>"`` / ``"chat:<id>"`` —
         convenience for ad-hoc callers (cron, send_message tool).
      3. ``chat_id`` as bare integer — default to ``"chat:<id>"``
         for backward compatibility with earlier plugin revisions
         that only knew about chat_ids.
    """
    # 1) metadata wins
    if metadata:
        kind = metadata.get("max_route_kind")
        rid = metadata.get("max_route_id")
        if kind in ("user", "chat") and rid:
            return str(kind), str(rid)

    s = str(chat_id or "").strip()
    # 2) tagged string
    if s.startswith("user:"):
        return "user", s[len("user:"):].strip()
    if s.startswith("chat:"):
        return "chat", s[len("chat:"):].strip()

    # 3) bare id — default to "chat" (legacy behaviour; harmless for
    # channels, may 400 for DMs — callers should use the tagged form).
    if s:
        return "chat", s

    return ("chat", "")


def _split_for_send(text: str, limit: int) -> list:
    """Split ``text`` into chunks no longer than ``limit`` chars.

    Strategy: paragraph boundaries (``\\n\\n``) first, then sentence
    boundaries (``\\n``, ``. ``), then word boundaries, then hard cut.
    Always returns at least one chunk; if the input is empty, returns
    ``[""]`` so callers still get a single send call (and the API can
    surface its own validation error).
    """
    if text is None:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list = []
    remaining = text
    while len(remaining) > limit:
        # Try paragraph break
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= limit // 3:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= limit // 3:
            cut = remaining.rfind(". ", 0, limit)
        if cut <= limit // 3:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= limit // 3:
            cut = limit  # hard cut
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks if chunks else [text[:limit]]


def _extract_update_meta(
    upd: Dict[str, Any],
    update_type: str,
    bot_id: Optional[int],
) -> Dict[str, Any]:
    """Pull a small, safe subset of an update for logging.

    We deliberately avoid logging the message body (could contain a
    pasted secret). Only IDs, types, and text length.
    """
    meta: Dict[str, Any] = {
        "update_type": update_type,
        "chat_id": "<n/a>",
        "user_id": "<n/a>",
        "message_id": "<n/a>",
        "text_len": 0,
    }
    msg = upd.get("message") or {}
    body = msg.get("body") or {}
    recipient = msg.get("recipient") or {}
    sender = msg.get("sender") or {}

    if recipient.get("chat_id") is not None:
        meta["chat_id"] = recipient["chat_id"]
    if sender.get("user_id") is not None:
        meta["user_id"] = sender["user_id"]
    if body.get("mid"):
        meta["message_id"] = _mask_id(str(body["mid"]))
    if body.get("text"):
        meta["text_len"] = len(str(body["text"]))

    return meta


# ---------------------------------------------------------------------------
# register() — called by hermes_cli.plugins.PluginManager
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Plugin entry point — registers MAX with the platform registry.

    See hermes_cli/plugins.py::PluginContext.register_platform for the
    full signature and the ADDING_A_PLATFORM.md guide for the rationale
    behind each PlatformEntry field.
    """
    ctx.register_platform(
        name="max",
        label="MAX",
        emoji="💬",
        adapter_factory=lambda cfg: MaxAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["MAX_BOT_TOKEN"],
        install_hint="(no extra deps — uses Python stdlib for MVP step 2)",
        env_enablement_fn=_env_enablement,
        # auth env vars — _is_user_authorized in run.py reads them via
        # PlatformEntry.allowed_users_env / allow_all_env. Active in F-08.
        allowed_users_env="MAX_ALLOWED_USERS",
        allow_all_env="MAX_ALLOW_ALL_USERS",
        # cron deliver=max — wired in F-09 (uses MAX_HOME_CHANNEL)
        cron_deliver_env_var="MAX_HOME_CHANNEL",
        # out-of-process cron sender — F-09: enables `hermes cron` with
        # deliver=max (and cross-platform send_message when no live
        # adapter exists in this process).
        standalone_sender_fn=_standalone_send,
        # keep below Telegram's 4096 to leave headroom; MAX says 4000
        max_message_length=4000,
        pii_safe=False,  # MAX user_ids are public integers, not PII
        allow_update_command=True,
        platform_hint=(
            "You are communicating via Messenger MAX (max.ru). "
            "Use standard Markdown (NOT Telegram MarkdownV2): "
            "**bold**, *italic*, [text](url). No backslash-escaping. "
            "4000 char per-message limit. Authorization: <token> header "
            "without Bearer prefix."
        ),
    )
    logger.debug("[MAX] plugin registered: name=max, label=MAX, kind=platform")
