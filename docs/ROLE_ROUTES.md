# Role Routes

## What Are Role Routes?

Role routes let you switch between specialized agent profiles by sending a slash command in MAX. Each role has its own SOUL.md (system prompt) and toolset configuration.

## How It Works

1. You send `/dev fix the bug in auth.py`
2. The adapter matches `/dev` to the `coder` profile
3. Hermes Gateway loads `coder/SOUL.md` as the channel prompt
4. The agent responds using the coder persona and relevant tools

## Default Roles

### /copy — Copywriter

**Profile:** `copywriter`
**Tools:** terminal, file, web, search
**Scope:** Texts, posts, scripts, landing pages, emails, social media content

### /prompt — Prompt Engineer

**Profile:** `prompt`
**Tools:** terminal, file, web, search
**Scope:** Prompt engineering, SOUL.md authoring, AGENTS.md, system prompts

### /marketing — Marketer

**Profile:** `marketer`
**Tools:** terminal, file, web, search
**Scope:** Target audience, offers, strategy, analytics, campaigns

### /dev — Coder

**Profile:** `coder`
**Tools:** terminal, file, web, search
**Scope:** Code, server, debugging, API, deployment

## Adding Custom Roles

Use `/team-add` to create new roles from MAX chat, or manually:

1. Create profile: `~/.hermes/profiles/myrole/SOUL.md`
2. Add to `~/.hermes/plugins/max/role_registry.yaml`:

```yaml
  myrole:
    enabled: true
    command: /myrole
    profile: myrole
    profile_path: ~/.hermes/profiles/myrole
    soul_path: ~/.hermes/profiles/myrole/SOUL.md
    display_name: "My Role"
    emoji: "🤖"
    description: "Description of my role"
```

3. Restart gateway

## Toolsets

Each role can specify which Hermes tools are available:

```yaml
    toolsets:
      - terminal
      - file
      - web
      - search
```

If no toolsets specified, Hermes defaults apply.
