# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately.
Do not open a public issue for security problems.

## Secrets Handling

- **NEVER** commit real tokens, API keys, or passwords to this repository.
- Use `.env.example` as a template. Fill in real values locally only.
- Run `scripts/check_secrets.sh` before every commit.

## Checklist

- [ ] `.env` is in `.gitignore`
- [ ] No real tokens in any file
- [ ] No real user IDs in any file
- [ ] `scripts/check_secrets.sh` passes clean
- [ ] No log files committed
- [ ] No state/session/backup files committed
- [ ] Pending files use mode 600
- [ ] `MAX_ALLOW_ALL_USERS` is NOT set to 1 in production
- [ ] Only allowed users can control Hermes via MAX
- [ ] SOUL.md files do not contain secrets
- [ ] Route validation prevents system command override
- [ ] Rollback is available for any team-add operation
