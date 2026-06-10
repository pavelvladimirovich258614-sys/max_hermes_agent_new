# Docker (экспериментально)

## Ограничения

Режим Docker — **экспериментальный** и имеет существенные ограничения:

- Docker-образ содержит только файлы plugin
- Hermes Gateway должен быть установлен и запущен на хосте
- Секреты нужно монтировать при запуске, а не вшивать в образ
- Постоянное состояние (профили, реестр) должно монтироваться как volume

## Использование

```bash
# Клонировать и собрать
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new

# Скопировать и отредактировать env
cp .env.example .env
nano .env

# Сборка
docker compose build

# Запуск
docker compose up -d
```

## Монтирование volume

Чтобы plugin работал, контейнеру нужен доступ к:
- `~/.hermes/plugins/max/` — файлы plugin
- `~/.hermes/.env` — секреты (только чтение)
- `~/.hermes/profiles/` — профили агентов
- `~/.hermes/state/` — pending-состояния и резервные копии

## Рекомендация

Для production устанавливайте plugin нативно (см. [INSTALL.md](INSTALL.md)).
Режим Docker лучше подходит для тестирования и CI-пайплайнов.
