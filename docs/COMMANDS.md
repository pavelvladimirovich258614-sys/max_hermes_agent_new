# Commands Reference

## Hermes Core Commands

| Command | Description |
|---------|-------------|
| `/status` | Show agent status and config |
| `/model` | Show or change model |
| `/new` | Start new conversation |
| `/reset` | Reset current session |
| `/stop` | Stop current generation |
| `/retry` | Retry last response |
| `/undo` | Undo last exchange |
| `/commands` | List available commands |

## Role Route Commands

Each role route activates a specialized agent profile:

| Command | Role | Profile | Description |
|---------|------|---------|-------------|
| `/copy` | Copywriter | copywriter | Texts, posts, scripts, landing pages |
| `/prompt` | Prompt Engineer | prompt | Prompts, SOUL.md, AGENTS.md |
| `/marketing` | Marketer | marketer | Audience, offers, strategy |
| `/dev` | Coder | coder | Code, server, debugging, API |

**Usage:** Send command followed by your request:
```
/copy Напиши продающий пост про AI-бота
```

The rest of the message becomes the task for the role.

## Team Management Commands

| Command | Description |
|---------|-------------|
| `/team-add` | Preview new agent (dry-run) |
| `/team-confirm <id>` | Create agent for real |
| `/team-cancel <id>` | Cancel pending creation |
| `/team-rollback <name>` | Remove agent + rollback registry |
| `/team-list` | List pending requests |

### /team-add

```text
/team-add name=designer route=/design title="Дизайнер" SOUL:Ты дизайнер визуалов...
```

**Parameters:**
- `name` — Agent identifier (lowercase, 2-32 chars)
- `route` — Slash command (e.g., `/design`)
- `title` — Display name (1-64 chars)
- `SOUL:` — Agent instructions (100-12000 chars, rest of message)

**Validations:**
- Name: `[a-z0-9_-]{2,32}`
- Route: `/[a-z0-9_-]{2,32}`
- No system route override (`/status`, `/model`, etc.)
- No duplicate routes or profiles
- No secrets in SOUL (ghp_, sk-, BOT_TOKEN patterns)

### /team-confirm

```text
/team-confirm ta_20250610_140535_d90b27
```

Creates:
- `~/.hermes/profiles/<name>/SOUL.md`
- `~/.hermes/profiles/<name>/config.yaml`
- Registry entry in `role_registry.yaml`
- Backup of registry before edit

**Requires gateway restart after confirm.**

### /team-rollback

```text
/team-rollback designer
```

Removes:
- Profile directory
- Registry entry
- Any pending state for this name

**Requires gateway restart after rollback.**

## Custom Routes

You can add any role via `/team-add`. Examples:

```text
/team-add name=analyst route=/analyst title="Аналитик" SOUL:Ты аналитик данных. Анализируешь метрики, строишь графики, делаешь выводы на основе данных. Работаешь с Python, pandas, matplotlib. Не меняешь файлы без подтверждения.

/team-add name=support route=/support title="Поддержка" SOUL:Ты специалист технической поддержки. Помогаешь пользователям решать проблемы. Спрашиваешь детали, даёшь пошаговые инструкции. Не читаешь секреты.
```
