![MAX Hermes Agent](assets/cover.svg)

# MAX Hermes Agent — канал MAX для Hermes Gateway

Это не отдельный чат-бот, а **platform plugin**, который подключает мессенджер [MAX](https://max.ru) как полноценный канал [Hermes Gateway](https://hermes-agent.nousresearch.com). Все возможности агента — рассуждения, инструменты, роли, профили — доступны прямо из чата MAX.

Путь сообщения:

```
MAX → MAX plugin → Hermes Gateway → Hermes Agent → tools/roles/profiles → ответ в MAX
```

## Возможности

| Возможность | Описание |
|-------------|----------|
| **Slash-команды Hermes** | `/status`, `/model`, `/new`, `/reset` и другие — прямо из MAX |
| **Роли** | `/copy`, `/prompt`, `/marketing`, `/dev` и собственные роли |
| **Allowlist** | Отвечает только пользователям из `MAX_ALLOWED_USERS` |
| **Long polling** | Получение обновлений через MAX Bot API, webhook не требуется |
| **Инструменты** | terminal, browser/search, write_file — из чата MAX |
| **Прогресс** | Сообщения о ходе выполнения инструментов в реальном времени |
| **Team Add** | Создание новых агентов из MAX с предпросмотром и откатом |
| **Изоляция** | Никаких пересечений с Telegram-каналами и cron |
| **Скрипты** | systemd/restart, smoke, doctor, check_secrets |

## Быстрый старт

```bash
# 1. Склонировать репозиторий
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new

# 2. Убедиться, что в репозитории нет секретов
bash scripts/check_secrets.sh

# 3. Установить plugin в ~/.hermes/plugins/max
bash scripts/install_plugin.sh

# 4. Настроить ~/.hermes/.env (токен и allowlist)
nano ~/.hermes/.env
# MAX_BOT_TOKEN=PASTE_YOUR_MAX_BOT_TOKEN_HERE
# MAX_ALLOWED_USERS=YOUR_MAX_USER_ID

# 5. Проверить токен (сам токен не печатается)
python3 scripts/verify_max_token.py

# 6. Проверить установку
bash scripts/doctor.sh

# 7. Перезапустить gateway
systemctl --user restart hermes-gateway
# или: hermes gateway restart

# 8. Проверить из MAX
# /status
# /dev скажи коротко, ты работаешь?
```

Подробнее: [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Архитектура

```mermaid
flowchart LR
    U[Пользователь MAX] --> M[MAX Bot API]
    M --> A[MaxAdapter]
    A --> G[Hermes Gateway Runner]
    G --> R[Role Router]
    R --> P[Профили / SOUL.md]
    G --> T[Tools / Skills / Browser / Terminal]
    T --> G
    G --> A
    A --> M
    M --> U
```

### Изоляция от Telegram

```mermaid
flowchart TB
    TG[Telegram Adapter / Cron] -. изолированы .- MAX[MAX Adapter]
    TG --> TGCron[Cron-задачи Telegram]
    MAX --> MAXUser[Пользователь/канал MAX]
    TGCron -. нет авто-маршрута в MAX .- MAXUser
```

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CRON_AND_TELEGRAM_ISOLATION.md](docs/CRON_AND_TELEGRAM_ISOLATION.md).

## Команды

### Базовые команды Hermes
`/status` `/model` `/new` `/reset` `/stop` `/retry` `/undo` `/commands`

### Роли
| Команда | Роль | Для чего |
|---------|------|----------|
| `/copy` | Копирайтер | Тексты, посты, сценарии, лендинги |
| `/prompt` | Промпт-инженер | Промпты, SOUL.md, AGENTS.md |
| `/marketing` | Маркетолог | Аудитория, офферы, стратегия, аналитика |
| `/dev` | Разработчик | Код, сервер, отладка, API |

### Управление командой агентов
| Команда | Описание |
|---------|----------|
| `/team-add` | Предпросмотр нового агента (dry-run) |
| `/team-confirm <id>` | Реальное создание агента |
| `/team-cancel <id>` | Отмена ожидающего создания |
| `/team-rollback <name>` | Удаление агента с откатом |
| `/team-list` | Список ожидающих запросов |

### Примеры
```
/copy Напиши продающий пост про AI-бота
/prompt Сделай промпт для рекламного видео
/marketing Придумай стратегию продвижения на 7 дней
/dev Проверь версию Python на сервере
```

Полный справочник: [docs/COMMANDS.md](docs/COMMANDS.md).

## Установка

Подробные инструкции — в [docs/INSTALL.md](docs/INSTALL.md):
- **Вариант A** — установка в существующий Hermes (рекомендуется)
- **Вариант B** — ручное копирование
- **Вариант C** — Docker (экспериментально)
- **Вариант D** — режим разработки

## Безопасность

- **Токен хранится только в `~/.hermes/.env`** — никогда не коммитьте `.env`; в репозитории лежит только шаблон `.env.example` с placeholders.
- **`MAX_ALLOWED_USERS` обязателен** — без allowlist бот не должен работать в продакшене.
- **`MAX_ALLOW_ALL_USERS` не использовать в проде** — только для локальной отладки.
- **Скан секретов** — `bash scripts/check_secrets.sh` перед каждым коммитом/пушем.
- **Откат** — каждое создание агента через team-add можно отменить.

Подробнее: [SECURITY.md](SECURITY.md) и [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md).

## Что не входит в scope

- **Webhook пока не включаем** — работает только long polling.
- **Core Hermes не патчим** — plugin ставится в `~/.hermes/plugins/max`, ядро Hermes (`/usr/local/lib/hermes-agent`) не изменяется.
- **Production-секреты не хранятся в репозитории** — только placeholders и шаблоны.

## Запуск тестов

```bash
cd plugin/max
python3 -m unittest tests.test_adapter -v
```

Тесты используют mock HTTP-ответы — реальный токен MAX не нужен.

## Документация

| Документ | Описание |
|----------|----------|
| [INSTALL.md](docs/INSTALL.md) | Установка (все варианты) |
| [QUICKSTART.md](docs/QUICKSTART.md) | Запуск за 5 минут |
| [MAX_BOT_SETUP.md](docs/MAX_BOT_SETUP.md) | Как получить токен бота MAX |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Как это устроено внутри |
| [COMMANDS.md](docs/COMMANDS.md) | Справочник всех команд |
| [ROLE_ROUTES.md](docs/ROLE_ROUTES.md) | Система ролевых маршрутов |
| [TEAM_ADD.md](docs/TEAM_ADD.md) | Создание агентов из MAX |
| [TOOLS_AND_PROGRESS.md](docs/TOOLS_AND_PROGRESS.md) | Инструменты через MAX |
| [CRON_AND_TELEGRAM_ISOLATION.md](docs/CRON_AND_TELEGRAM_ISOLATION.md) | Гарантии изоляции |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Типовые проблемы |
| [SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md) | Чек-лист безопасности |
| [DOCKER.md](docs/DOCKER.md) | Использование Docker |
| [SYSTEMD.md](docs/SYSTEMD.md) | Сервис systemd |

## Отказ от ответственности

Это интеграция, поддерживаемая сообществом. См. [DISCLAIMER.md](DISCLAIMER.md).

## Лицензия

MIT — см. [LICENSE](LICENSE).
