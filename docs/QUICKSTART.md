# Quick Start (5 minutes)

## 1. Get a MAX bot token

Open MAX, find @mail_bot, send `/newbot`, follow instructions.
See [MAX_BOT_SETUP.md](MAX_BOT_SETUP.md) for details.

## 2. Install

```bash
git clone https://github.com/pavelvladimirovich258614-sys/max_hermes_agent_new.git
cd max_hermes_agent_new
bash scripts/install_plugin.sh
```

## 3. Configure

Edit `~/.hermes/.env`:

```env
MAX_BOT_TOKEN=your_token_here
MAX_ALLOWED_USERS=your_user_id
MAX_PROGRESS_APPEND=1
```

## 4. Start

```bash
systemctl --user restart hermes-gateway
```

## 5. Test

From MAX, send: `/status`

Then: `/dev скажи "hello"`

Done!

## Next Steps

- [Add roles](ROLE_ROUTES.md) — copywriter, marketer, coder, etc.
- [Create custom agents](TEAM_ADD.md) — from MAX chat
- [Use tools](TOOLS_AND_PROGRESS.md) — terminal, browser, write_file
