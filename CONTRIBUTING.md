# Contributing

> **Кратко по-русски:** как внести вклад — сделайте fork, создайте ветку, внесите изменения, прогоните `bash scripts/check_secrets.sh` и тесты (`cd plugin/max && python3 -m unittest tests.test_adapter -v`), затем откройте Pull Request. Никогда не включайте в код и issue реальные токены, user ID и chat ID — только placeholders.

Thank you for your interest in improving MAX Hermes Agent!

## How to Contribute

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Make your changes.
4. **Run secrets check**: `bash scripts/check_secrets.sh`.
5. **Run tests**: `cd plugin/max && python3 -m unittest tests.test_adapter -v`.
6. Commit with a clear message.
7. Open a Pull Request.

## Security Rules

- **NEVER** include real tokens, API keys, user IDs, or chat IDs.
- **NEVER** include log files, state files, or session data.
- Use placeholder values in examples and tests.
- Run `scripts/check_secrets.sh` before every push.

## Code Style

- Python 3.11+
- Type hints where practical
- Docstrings for public functions
- Unit tests for new features

## Reporting Issues

- Use GitHub Issues.
- Do NOT include real tokens or IDs in issue reports.
- Describe the problem, expected behavior, and steps to reproduce.
