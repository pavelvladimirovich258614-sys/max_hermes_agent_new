# Hermes Agent Setup

## Installing Hermes Agent

Follow the official guide: https://hermes-agent.nousresearch.com/docs

```bash
# Install Hermes Agent
pip install hermes-agent

# Initialize
hermes init

# Configure your model provider
hermes config set model.provider your_provider
hermes config set model.default your_model
```

## Verify Hermes Works

```bash
# Start gateway
hermes gateway start

# Test from CLI
hermes chat "Hello, are you working?"
```

## Then Install MAX Plugin

After Hermes is working, install the MAX plugin:

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
bash scripts/install_plugin.sh
```

See [INSTALL.md](INSTALL.md) for full instructions.
