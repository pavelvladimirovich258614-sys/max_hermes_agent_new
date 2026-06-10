# MAX Home Channel Example

This file shows how to configure MAX as a delivery target for cron tasks.

## Configuration

In `~/.hermes/.env`:

```env
MAX_HOME_CHANNEL=user:YOUR_MAX_USER_ID
```

## Usage

When creating a cron job, you can set delivery to the MAX home channel:

```bash
hermes cron create --deliver max --prompt "Daily AI news digest" --schedule "0 9 * * *"
```

## Important

- MAX cron delivery is opt-in, not automatic
- Telegram cron tasks do NOT auto-route to MAX
- See [docs/CRON_AND_TELEGRAM_ISOLATION.md](../docs/CRON_AND_TELEGRAM_ISOLATION.md)
