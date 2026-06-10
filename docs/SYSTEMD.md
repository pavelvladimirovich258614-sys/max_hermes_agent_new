# Systemd Service

Hermes Gateway typically runs as a user-level systemd service.

## Check Status

```bash
systemctl --user is-active hermes-gateway
```

## Restart

```bash
systemctl --user restart hermes-gateway
```

## View Logs

```bash
tail -50 ~/.hermes/logs/gateway.log
```

## After Plugin Changes

After installing or updating the MAX plugin:

1. Restart gateway: `systemctl --user restart hermes-gateway`
2. Wait ~15 seconds for startup
3. Verify: `grep "max connected" ~/.hermes/logs/gateway.log | tail -1`
4. Test from MAX: `/status`

## After /team-confirm

Registry changes require a gateway restart:

```bash
systemctl --user restart hermes-gateway
```

## Troubleshooting

If gateway fails to start:
```bash
systemctl --user reset-failed hermes-gateway
systemctl --user start hermes-gateway
```
