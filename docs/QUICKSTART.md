# Быстрый старт (5 минут)

## 1. Получите токен бота MAX

Откройте MAX, найдите @mail_bot, отправьте `/newbot`, следуйте инструкциям.
Подробнее — в [MAX_BOT_SETUP.md](MAX_BOT_SETUP.md).

## 2. Установите plugin

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
bash scripts/install_plugin.sh
```

## 3. Настройте

Отредактируйте `~/.hermes/.env`:

```env
MAX_BOT_TOKEN=your_token_here
MAX_ALLOWED_USERS=your_user_id
MAX_PROGRESS_APPEND=1
```

## 4. Запустите

```bash
systemctl --user restart hermes-gateway
```

## 5. Проверьте

Из MAX отправьте: `/status`

Затем: `/dev скажи "hello"`

Готово!

## Что дальше

- [Добавить роли](ROLE_ROUTES.md) — копирайтер, маркетолог, кодер и т.д.
- [Создать своих агентов](TEAM_ADD.md) — прямо из чата MAX
- [Использовать инструменты](TOOLS_AND_PROGRESS.md) — терминал, браузер, write_file
