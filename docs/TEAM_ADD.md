# Team Add — Create Agents from MAX

The team management system lets you create, preview, confirm, and rollback agent profiles directly from MAX chat.

## Workflow

```mermaid
flowchart TD
    A[/team-add] --> B[Validate 13 checks]
    B --> C[Create Pending State]
    C --> D[Show Preview]
    D --> E{User decides}
    E -->|/team-confirm id| F[Create Profile Files]
    F --> G[Update Registry]
    G --> H[Restart Gateway]
    H --> I[New route works]
    E -->|/team-cancel id| J[Delete Pending]
    I -->|/team-rollback name| K[Remove Profile + Registry]
    K --> L[Restart Gateway]
```

## Step 1: Preview (/team-add)

```text
/team-add name=designer route=/design title="Дизайнер" SOUL:Ты дизайнер визуалов, аватаров, баннеров и промо-картинок. Работаешь кратко, структурно, задаёшь 1 уточняющий вопрос только если без него нельзя. Даёшь промпты для изображений, ТЗ дизайнеру и чеклист качества. Не читаешь секреты, не просишь токены, не меняешь файлы без подтверждения.
```

**What happens:**
- 13 validations run (see below)
- Pending state created with 10-minute TTL
- Preview displayed (name, route, title, soul_len, soul_hash, pending ID)
- **No files created yet**

**Parameters:**
- `name` — Agent identifier: `[a-z0-9_-]{2,32}`
- `route` — Slash command: `/[a-z0-9_-]{2,32}`
- `title` — Display name: 1-64 characters
- `SOUL:` — Agent instructions: 100-12000 characters

## Step 2: Confirm (/team-confirm)

```text
/team-confirm ta_20250610_140535_d90b27
```

**What happens:**
- Re-validates all checks
- Creates `~/.hermes/profiles/<name>/SOUL.md`
- Creates `~/.hermes/profiles/<name>/config.yaml` (minimal)
- Appends entry to `role_registry.yaml`
- Creates backup of registry
- Marks pending as confirmed

**⚠️ Requires gateway restart.**

## Step 3: Test

```text
/design Сделай промпт для яркого аватара AI-агента
```

## Step 4: Rollback (optional)

```text
/team-rollback designer
```

**What happens:**
- Creates backup of registry
- Removes profile directory
- Removes registry entry
- Cleans up any pending state

**⚠️ Requires gateway restart.**

## 13 Validations

1. User is in allowlist
2. Name matches regex `[a-z0-9_-]{2,32}`
3. Route matches regex `/[a-z0-9_-]{2,32}`
4. Title length 1-64 chars
5. SOUL length 100-12000 chars
6. Route is not a system command (`/status`, `/model`, etc.)
7. Route is not already registered
8. Name/profile does not already exist
9. SOUL does not contain secret patterns (ghp_, sk-, BOT_TOKEN)
10. SOUL does not contain security bypass patterns
11. Pending ID exists and not expired
12. Only creator can confirm
13. Route and name still available at confirm time

## Backup and Safety

- Registry is backed up before every mutation (confirm and rollback)
- Backups stored in `~/.hermes/state/team_add_backups/`
- Profile files use mode 600
- Pending state has 10-minute TTL
- All writes are atomic (write to .tmp, then rename)

## Security

- Only allowlisted users can use team commands
- SOUL content is scanned for secrets
- System routes cannot be overridden
- Confirm requires the same user who created the pending
