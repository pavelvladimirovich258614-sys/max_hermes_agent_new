# Docker (Experimental)

## Limitations

Docker mode is **experimental** and has significant limitations:

- The Docker image only contains plugin files
- Hermes Gateway must be installed and running on the host
- Secrets must be mounted at runtime, not baked into the image
- Persistent state (profiles, registry) must be volume-mounted

## Usage

```bash
# Clone and build
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new

# Copy and edit env
cp .env.example .env
nano .env

# Build
docker compose build

# Run
docker compose up -d
```

## Volume Mounts

For the plugin to work, the container needs access to:
- `~/.hermes/plugins/max/` — plugin files
- `~/.hermes/.env` — secrets (read-only)
- `~/.hermes/profiles/` — agent profiles
- `~/.hermes/state/` — pending state and backups

## Recommendation

For production, install the plugin natively (see [INSTALL.md](INSTALL.md)).
Docker mode is best for testing and CI pipelines.
