# Сервис systemd

Hermes Gateway обычно работает как пользовательский (user-level) сервис systemd.

## Проверка статуса

```bash
systemctl --user is-active hermes-gateway
```

## Перезапуск

```bash
systemctl --user restart hermes-gateway
```

## Просмотр логов

```bash
tail -50 ~/.hermes/logs/gateway.log
```

## После изменения plugin

После установки или обновления MAX plugin:

1. Перезапустите gateway: `systemctl --user restart hermes-gateway`
2. Подождите ~15 секунд, пока сервис запустится
3. Проверьте: `grep "max connected" ~/.hermes/logs/gateway.log | tail -1`
4. Протестируйте из MAX: `/status`

## После /team-confirm

Изменения реестра требуют перезапуска gateway:

```bash
systemctl --user restart hermes-gateway
```

## Устранение неполадок

Если gateway не запускается:
```bash
systemctl --user reset-failed hermes-gateway
systemctl --user start hermes-gateway
```
