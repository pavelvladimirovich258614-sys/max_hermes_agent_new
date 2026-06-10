# MAX Bot Setup

## Creating a MAX Bot

1. Open MAX messenger
2. Find @mail_bot (official MAX bot for creating bots)
3. Send `/newbot`
4. Choose a name for your bot (e.g., "My Hermes Agent")
5. Choose a username (e.g., "my_hermes_agent_bot")
6. You will receive a bot token — **save it securely**

## Token Security

- **Never** share your bot token
- **Never** commit it to any repository
- **Never** send it in public chats
- Store it only in `~/.hermes/.env` with mode 600

## Verifying Your Token

```bash
python3 scripts/verify_max_token.py
```

This calls `GET https://platform-api.max.ru/me` and shows:
- Bot ID
- Bot name
- Bot username
- Is bot: true

The token itself is **never** printed.

## Finding Your User ID

Send `/start` to your own bot while it is running with `MAX_ALLOW_ALL_USERS=1` (temporarily).
Check the gateway log for the incoming user ID.

**Important:** After finding your ID, immediately set `MAX_ALLOW_ALL_USERS=0` and add your ID to `MAX_ALLOWED_USERS`.

## Long Polling vs Webhook

This plugin uses **long polling** by default.

- Long polling: simple, no public endpoint needed, good for dev/test
- Webhook: requires a public HTTPS endpoint, better for production

If a webhook is already set on the bot, polling may not receive updates.
To switch to polling, you may need to delete the webhook first via MAX Bot API.

## Groups and Channels

- In **DM**: messages are addressed by `user_id`
- In **groups/channels**: bot must be added as admin, messages use `chat_id`
- The `Unknown recipient` error occurs when sending to an invalid chat_id format

## Allowlist

The allowlist (`MAX_ALLOWED_USERS`) is critical for security:

- Only listed user IDs can send commands to Hermes
- Without the allowlist, anyone who finds your bot can control your server
- **Never** set `MAX_ALLOW_ALL_USERS=1` in production
