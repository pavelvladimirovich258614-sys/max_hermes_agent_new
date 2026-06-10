# Disclaimer

> **Кратко по-русски:** это интеграция, поддерживаемая сообществом, а не официальный продукт MAX (VK) или Nous Research. Вы сами отвечаете за токен бота, безопасность сервера и контроль доступа. Инструменты (terminal, browser, write_file) могут выполнять команды на вашем сервере — ограничивайте их конфигурацией Hermes. ПО предоставляется «как есть», без гарантий.

## Community Integration

This is a **community-maintained integration** between MAX Messenger and Hermes Agent.
It is not an official product of MAX (VK), Hermes Agent (Nous Research), or any other company.

## User Responsibilities

By using this software, you agree that:

1. **You are responsible** for your own MAX bot token, server security, and access control.
2. **Never store secrets** in public repositories, shared drives, or unencrypted storage.
3. **Tools** (terminal, browser, write_file) can execute commands on your server if Hermes has access.
   You control what Hermes can do through its configuration.
4. **For production**, use allowlists, systemd, monitoring, and regular backups.
5. **Long polling** is convenient for development and testing. For production, consider webhook-based setup.
6. **No warranty** — this software is provided "as is" without any guarantees.

## Safety Features

This integration includes:
- User allowlist (only specified MAX users can interact)
- Secret detection in SOUL.md files
- Route validation (no system command override)
- Rollback capability for all team-add operations
- Registry backup before any mutation
- Atomic file writes for pending state

## Use at Your Own Risk
