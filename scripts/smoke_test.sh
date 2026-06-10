#!/usr/bin/env bash
# Local smoke test (no real MAX token needed)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== MAX Hermes Agent Smoke Test ==="
echo ""

PASS=0
FAIL=0

# Check plugin files exist
echo "1. Plugin files..."
for f in plugin/max/__init__.py plugin/max/adapter.py plugin/max/plugin.yaml plugin/max/team_manager/core.py; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        echo "   OK: $f"
    else
        echo "   MISSING: $f"
        FAIL=$((FAIL + 1))
    fi
done

# Check tests exist
echo "2. Tests..."
if [ -f "$SCRIPT_DIR/plugin/max/tests/test_adapter.py" ]; then
    echo "   OK: test_adapter.py exists"
else
    echo "   MISSING: test_adapter.py"
    FAIL=$((FAIL + 1))
fi

# Run tests
echo "3. Running tests..."
cd "$SCRIPT_DIR/plugin/max"
if python3 -m unittest tests.test_adapter 2>&1 | tail -3; then
    echo "   Tests passed."
    PASS=$((PASS + 1))
else
    echo "   Tests FAILED."
    FAIL=$((FAIL + 1))
fi

# Secrets check
echo "4. Secrets scan..."
if bash "$SCRIPT_DIR/scripts/check_secrets.sh"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
fi

# Check .env not tracked
echo "5. .env not in repo..."
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "   FAIL: .env exists in repo!"
    FAIL=$((FAIL + 1))
else
    echo "   OK: no .env file"
    PASS=$((PASS + 1))
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
