# Устранение неполадок

## «Unauthorized user: XXXXXXX on max»

**Причина:** `MAX_ALLOWED_USERS` пуст или не содержит ваш user ID.

**Решение:**
```bash
grep MAX_ALLOWED_USERS ~/.hermes/.env
# Должен содержать ваш числовой user ID
# Если его нет — добавьте и перезапустите gateway
```

## «HTTP 400 Unknown recipient»

**Причина:** неверный формат chat_id в send().

**Решение:** adapter должен использовать числовой chat_id (int), а не строки с префиксом вида `user:XXXXXXX`.
Проверьте `adapter.py:_send_one` — там префикс отрезается.

## «No module named 'team_manager'»

**Причина:** не разрешается относительный импорт.

**Решение:** adapter использует try/except для импортов:
```python
try:
    from .team_manager import core as tm_core
except ImportError:
    from team_manager import core as tm_core
```
Убедитесь, что директория `team_manager/` лежит рядом с `adapter.py`.

## Gateway не запускается

**Проверьте логи:**
```bash
tail -30 ~/.hermes/logs/gateway.log
```

Типичные проблемы:
- Неверный MAX_BOT_TOKEN
- Сеть недоступна (platform-api.max.ru)
- Тот же токен бота используется другим процессом (конфликт с webhook)

## Бот MAX не отвечает

1. Проверьте, что gateway работает: `systemctl --user is-active hermes-gateway`
2. Проверьте подключение MAX в логах: `grep "max connected" ~/.hermes/logs/gateway.log`
3. Проверьте, что ваш user ID есть в allowlist (белом списке)
4. Сначала попробуйте `/status` (самая простая команда)

## Не отображаются сообщения о прогрессе

**Причина:** не задана переменная `MAX_PROGRESS_APPEND=1`.

**Решение:**
```bash
grep MAX_PROGRESS_APPEND ~/.hermes/.env
# Должно быть: MAX_PROGRESS_APPEND=1
```

## Ролевой маршрут не работает

**Причина:** реестр не загружен или маршрут не зарегистрирован.

**Решение:**
1. Проверьте, что маршрут есть в `~/.hermes/plugins/max/role_registry.yaml`
2. Проверьте, что у роли стоит `enabled: true`
3. Перезапустите gateway (горячая перезагрузка реестра не поддерживается)

## Ошибки инструментов из MAX

**Причина:** инструменты Hermes зависят от окружения сервера.

**Решение:**
1. Проверьте, что инструмент доступен: terminal, browser, write_file
2. Проверьте права пользователя, под которым работает процесс Hermes
3. Проверьте конфигурацию конкретного инструмента в профиле Hermes

## Ошибки Telegram Forbidden

**Причина:** это проблема Telegram adapter, к MAX она не относится.

Telegram adapter может выдавать ошибки `Forbidden: bot can't initiate conversation` для старых сообщений из очереди. На работу MAX это НЕ влияет. MAX и Telegram изолированы друг от друга.

## Режим отладки

Для подробного логирования задайте в `~/.hermes/.env`:
```env
LOG_LEVEL=DEBUG
```
Затем перезапустите gateway. Не забудьте вернуть INFO для продакшена.
