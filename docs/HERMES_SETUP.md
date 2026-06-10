# Настройка Hermes Agent

## Установка Hermes Agent

Следуйте официальному руководству: https://hermes-agent.nousresearch.com/docs

```bash
# Установить Hermes Agent
pip install hermes-agent

# Инициализировать
hermes init

# Настроить провайдера модели
hermes config set model.provider your_provider
hermes config set model.default your_model
```

## Проверка работы Hermes

```bash
# Запустить gateway
hermes gateway start

# Проверить из CLI
hermes chat "Hello, are you working?"
```

## Затем установите MAX plugin

Когда Hermes работает, установите MAX plugin:

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
bash scripts/install_plugin.sh
```

Полная инструкция — в [INSTALL.md](INSTALL.md).
