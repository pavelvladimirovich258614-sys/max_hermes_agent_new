# Security Checklist

## Before Every Commit

- [ ] Run `bash scripts/check_secrets.sh` — must pass clean
- [ ] No real tokens in any file
- [ ] No real user IDs in any file
- [ ] `.env` is in `.gitignore` and not tracked
- [ ] No log files committed
- [ ] No state/session/backup files committed

## Production Setup

- [ ] `MAX_ALLOWED_USERS` set to specific user IDs (not empty, not allow-all)
- [ ] `MAX_ALLOW_ALL_USERS=0` (or not set)
- [ ] `MAX_BOT_TOKEN` stored only in `~/.hermes/.env` with mode 600
- [ ] Gateway runs under systemd with user-level isolation
- [ ] Pending files use mode 600
- [ ] Registry backups are stored in a secure directory
- [ ] SOUL.md files do not contain secrets or API keys
- [ ] Route validation prevents system command override
- [ ] Rollback is tested and available

## Never Do

- [ ] Never commit real tokens, API keys, or passwords
- [ ] Never set `MAX_ALLOW_ALL_USERS=1` in production
- [ ] Never share your bot token in public chats
- [ ] Never log full message text with personal data
- [ ] Never bake secrets into Docker images
- [ ] Never disable the allowlist

## Regular Maintenance

- [ ] Rotate bot tokens periodically
- [ ] Review allowlist for stale entries
- [ ] Check logs for unauthorized access attempts
- [ ] Update Hermes Agent regularly
- [ ] Review SOUL.md files for accidentally included secrets
