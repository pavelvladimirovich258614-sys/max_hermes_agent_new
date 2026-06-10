# Installation Guide

## Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs) installed and working
- Python 3.11+
- A MAX bot token (see [MAX_BOT_SETUP.md](MAX_BOT_SETUP.md))

---

## Option A — Existing Hermes Install (Recommended)

### 1. Clone the repository

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
```

### 2. Run the install script

```bash
bash scripts/install_plugin.sh
```

This copies plugin files to `~/.hermes/plugins/max/` without touching your existing config.

### 3. Configure environment

```bash
cp .env.example ~/.hermes/.env.max.example
```

Edit your `~/.hermes/.env` and add:

```env
MAX_BOT_TOKEN=your_real_token_here
MAX_ALLOWED_USERS=your_max_user_id
MAX_PROGRESS_APPEND=1
MAX_POLLING_TIMEOUT=30
```

### 4. Verify token

```bash
python3 scripts/verify_max_token.py
```

This calls MAX Bot API `/me` endpoint and prints bot info (never the token itself).

### 5. Restart gateway

```bash
systemctl --user restart hermes-gateway
# or: hermes gateway restart
```

### 6. Test from MAX

Open MAX, find your bot, and send:

```
/status
```

Then try a role route:

```
/dev скажи коротко, ты работаешь?
```

---

## Option B — Manual Install

1. Copy `plugin/max/` to `~/.hermes/plugins/max/`:

```bash
cp -r plugin/max ~/.hermes/plugins/max
```

2. Copy example profiles (optional):

```bash
cp -r examples/profiles ~/.hermes/profiles
```

3. Copy example role registry (optional, creates example roles):

```bash
cp examples/role_registry.yaml ~/.hermes/plugins/max/role_registry.yaml
```

4. Edit `~/.hermes/.env` with your real token and user ID.

5. Restart gateway.

**Important:** Never copy real `.env` files. Never copy logs, state, sessions, or backups.

---

## Option C — Docker (Experimental)

See [DOCKER.md](DOCKER.md).

Limitations:
- Docker mode provides plugin files only
- Hermes Gateway itself runs on the host
- Secrets must be mounted at runtime, not baked into the image
- For production, use native install

---

## Option D — Development Mode

```bash
# Clone and enter repo
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Run tests (no real token needed)
cd plugin/max
python3 -m unittest tests.test_adapter -v

# Run smoke checks
bash ../../scripts/smoke_test.sh
```

---

## Verify Installation

```bash
bash scripts/doctor.sh
```

This checks:
- Plugin files exist
- No real secrets in repo files
- Tests pass
- Gateway is running (if applicable)
