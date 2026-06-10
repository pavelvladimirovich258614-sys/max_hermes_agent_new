# Cron and Telegram Isolation

## Isolation Guarantee

MAX and Telegram are **completely separate** channels in Hermes Gateway:

- Separate adapters (MaxAdapter vs TelegramAdapter)
- Separate configs (MAX_BOT_TOKEN vs TELEGRAM_BOT_TOKEN)
- Separate home channels
- Separate delivery targets

## Cron Tasks

- **By default**: MAX has NO cron delivery targets
- Telegram cron tasks (e.g., daily digests) continue to deliver to Telegram channels
- Cron tasks do NOT auto-route to MAX
- To enable MAX cron delivery, you must explicitly configure `MAX_HOME_CHANNEL`

## Checking Isolation

```bash
# List cron jobs
hermes cron list

# Verify no MAX targets
# MAX cron delivery is opt-in, not automatic
```

## Enabling MAX Cron (Optional, Future)

If you want cron digests delivered to MAX:

1. Set in `~/.hermes/.env`:
   ```env
   MAX_HOME_CHANNEL=user:YOUR_MAX_USER_ID
   ```

2. Create a cron job with MAX delivery target

3. MAX cron delivery is a separate feature from the plugin itself

## Cross-Channel Safety

- Telegram bot cannot send to MAX users
- MAX bot cannot send to Telegram chats
- No shared session state between platforms
- No shared conversation history
