# Tests

Tests are located in `plugin/max/tests/test_adapter.py`.

## Running

```bash
cd plugin/max
python3 -m unittest tests.test_adapter -v
```

## What's Tested

- Message parsing and routing
- User authentication and allowlist
- Role route intercept and dispatch
- Team add/confirm/cancel/rollback
- Progress message append
- Send chunking
- No secrets in any test data (all IDs are placeholders)

## No Real Token Needed

All tests use mock HTTP responses. No real MAX bot token or network access required.
