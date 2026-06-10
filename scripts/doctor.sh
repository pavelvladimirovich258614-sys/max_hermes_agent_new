#!/usr/bin/env bash
# Diagnose MAX Hermes Agent setup
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
echo "=== MAX Hermes Agent Doctor ==="
echo ""

echo "1. Hermes home: $HERMES_HOME"
[ -d "$HERMES_HOME" ] && echo "   Exists: yes" || echo "   Exists: no"

echo "2. Plugin directory:"
[ -d "$HERMES_HOME/plugins/max" ] && echo "   $HERMES_HOME/plugins/max exists" || echo "   MISSING"

echo "3. Key files:"
for f in adapter.py plugin.yaml team_manager/core.py; do
    [ -f "$HERMES_HOME/plugins/max/$f" ] && echo "   OK: $f" || echo "   MISSING: $f"
done

echo "4. Role registry:"
[ -f "$HERMES_HOME/plugins/max/role_registry.yaml" ] && echo "   Found" || echo "   Not found"

echo "5. Environment:"
[ -f "$HERMES_HOME/.env" ] && echo "   .env exists" || echo "   .env MISSING"
grep -q "MAX_BOT_TOKEN" "$HERMES_HOME/.env" 2>/dev/null && echo "   MAX_BOT_TOKEN: configured" || echo "   MAX_BOT_TOKEN: not set"
grep -q "MAX_ALLOWED_USERS" "$HERMES_HOME/.env" 2>/dev/null && echo "   MAX_ALLOWED_USERS: configured" || echo "   MAX_ALLOWED_USERS: not set"

echo "6. Gateway:"
systemctl --user is-active hermes-gateway 2>/dev/null && echo "   Active" || echo "   Not active / not installed"

echo "7. Profiles:"
for p in copywriter prompt marketer coder; do
    [ -f "$HERMES_HOME/profiles/$p/SOUL.md" ] && echo "   OK: $p" || echo "   MISSING: $p"
done

echo ""
echo "Doctor complete. Fix any MISSING items above."
