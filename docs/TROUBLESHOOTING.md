# Troubleshooting

## "Unauthorized user: XXXXXXX on max"

**Cause:** `MAX_ALLOWED_USERS` is empty or does not include your user ID.

**Fix:**
```bash
grep MAX_ALLOWED_USERS ~/.hermes/.env
# Should contain your numeric user ID
# If not, add it and restart gateway
```

## "HTTP 400 Unknown recipient"

**Cause:** Incorrect chat_id format in send().

**Fix:** The adapter should use numeric chat_id (int), not tagged strings like `user:XXXXXXX`.
Check `adapter.py:_send_one` — it strips the prefix.

## "No module named 'team_manager'"

**Cause:** Relative import not resolving.

**Fix:** The adapter uses a try/except for imports:
```python
try:
    from .team_manager import core as tm_core
except ImportError:
    from team_manager import core as tm_core
```
Make sure `team_manager/` is in the same directory as `adapter.py`.

## Gateway Fails to Start

**Check logs:**
```bash
tail -30 ~/.hermes/logs/gateway.log
```

Common issues:
- Invalid MAX_BOT_TOKEN
- Network unreachable (platform-api.max.ru)
- Another process using the same bot token (webhook conflict)

## MAX Bot Not Responding

1. Check gateway is running: `systemctl --user is-active hermes-gateway`
2. Check MAX connected in logs: `grep "max connected" ~/.hermes/logs/gateway.log`
3. Check your user ID is in allowlist
4. Try `/status` first (simplest command)

## Progress Messages Not Showing

**Cause:** `MAX_PROGRESS_APPEND=1` not set.

**Fix:**
```bash
grep MAX_PROGRESS_APPEND ~/.hermes/.env
# Should be: MAX_PROGRESS_APPEND=1
```

## Role Route Not Working

**Cause:** Registry not loaded or route not registered.

**Fix:**
1. Check `~/.hermes/plugins/max/role_registry.yaml` has the route
2. Check `enabled: true` for the role
3. Restart gateway (no hot-reload for registry)

## Tool Errors from MAX

**Cause:** Hermes tools depend on server environment.

**Fix:**
1. Check the tool is available: terminal, browser, write_file
2. Check permissions of the Hermes process user
3. Check tool-specific config in Hermes profile

## Telegram Forbidden Errors

**Cause:** This is a Telegram adapter issue, not related to MAX.

The Telegram adapter may show `Forbidden: bot can't initiate conversation` errors for old queued messages. This does NOT affect MAX operation. MAX and Telegram are isolated.

## Debug Mode

For verbose logging, set in `~/.hermes/.env`:
```env
LOG_LEVEL=DEBUG
```
Then restart gateway. Remember to set back to INFO for production.
