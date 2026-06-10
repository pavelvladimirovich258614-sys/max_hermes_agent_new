# Пример: домашний канал MAX

Этот файл показывает, как настроить MAX как цель доставки для cron-задач.

## Настройка

В `~/.hermes/.env`:

```env
MAX_HOME_CHANNEL=user:YOUR_MAX_USER_ID
```

## Использование

При создании cron-задачи можно указать доставку в домашний канал MAX:

```bash
hermes cron create --deliver max --prompt "Daily AI news digest" --schedule "0 9 * * *"
```

## Важно

- Доставка cron в MAX включается явно, она не автоматическая
- Cron-задачи Telegram НЕ перенаправляются в MAX автоматически
- См. [docs/CRON_AND_TELEGRAM_ISOLATION.md](../docs/CRON_AND_TELEGRAM_ISOLATION.md)
