# Руководство по установке

## Требования

- Установленный и работающий [Hermes Agent](https://hermes-agent.nousresearch.com/docs)
- Python 3.11+
- Токен бота MAX (см. [MAX_BOT_SETUP.md](MAX_BOT_SETUP.md))

---

## Вариант A — установка в существующий Hermes (рекомендуется)

### 1. Склонируйте репозиторий

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
```

### 2. Запустите скрипт установки

```bash
bash scripts/install_plugin.sh
```

Скрипт копирует файлы plugin в `~/.hermes/plugins/max/`, не трогая вашу существующую конфигурацию.

### 3. Настройте окружение

```bash
cp .env.example ~/.hermes/.env.max.example
```

Отредактируйте свой `~/.hermes/.env` и добавьте:

```env
MAX_BOT_TOKEN=your_real_token_here
MAX_ALLOWED_USERS=your_max_user_id
MAX_PROGRESS_APPEND=1
MAX_POLLING_TIMEOUT=30
```

### 4. Проверьте токен

```bash
python3 scripts/verify_max_token.py
```

Скрипт вызывает endpoint `/me` MAX Bot API и выводит информацию о боте (сам токен никогда не печатается).

### 5. Перезапустите gateway

```bash
systemctl --user restart hermes-gateway
# или: hermes gateway restart
```

### 6. Проверьте из MAX

Откройте MAX, найдите своего бота и отправьте:

```
/status
```

Затем попробуйте ролевой маршрут:

```
/dev скажи коротко, ты работаешь?
```

---

## Вариант B — ручная установка

1. Скопируйте `plugin/max/` в `~/.hermes/plugins/max/`:

```bash
cp -r plugin/max ~/.hermes/plugins/max
```

2. Скопируйте примеры профилей (опционально):

```bash
cp -r examples/profiles ~/.hermes/profiles
```

3. Скопируйте пример реестра ролей (опционально, создаёт примеры ролей):

```bash
cp examples/role_registry.yaml ~/.hermes/plugins/max/role_registry.yaml
```

4. Отредактируйте `~/.hermes/.env`, указав свой реальный токен и user ID.

5. Перезапустите gateway.

**Важно:** никогда не копируйте реальные файлы `.env`. Никогда не копируйте логи, состояние, сессии и бэкапы.

---

## Вариант C — Docker (экспериментально)

См. [DOCKER.md](DOCKER.md).

Ограничения:
- Docker-режим предоставляет только файлы plugin
- Сам Hermes Gateway работает на хосте
- Секреты должны монтироваться во время запуска, а не зашиваться в образ
- Для продакшена используйте нативную установку

---

## Вариант D — режим разработки

```bash
# Склонировать репозиторий и перейти в него
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new

# Создать venv
python3 -m venv .venv
source .venv/bin/activate

# Запустить тесты (реальный токен не нужен)
cd plugin/max
python3 -m unittest tests.test_adapter -v

# Запустить smoke-проверки
bash ../../scripts/smoke_test.sh
```

---

## Проверка установки

```bash
bash scripts/doctor.sh
```

Скрипт проверяет:
- Файлы plugin на месте
- В файлах репозитория нет реальных секретов
- Тесты проходят
- Gateway запущен (если применимо)
