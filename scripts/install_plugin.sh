#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/max"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== MAX Hermes Agent Plugin Installer ==="
echo "Hermes home: $HERMES_HOME"
echo "Source:       $SCRIPT_DIR/plugin/max"
echo "Target:       $PLUGIN_DIR"

if [ ! -d "$SCRIPT_DIR/plugin/max" ]; then
    echo "ERROR: plugin/max not found. Run from repo root."
    exit 1
fi

mkdir -p "$PLUGIN_DIR/team_manager" "$PLUGIN_DIR/tests"

for f in __init__.py adapter.py plugin.yaml; do
    [ -f "$SCRIPT_DIR/plugin/max/$f" ] && cp "$SCRIPT_DIR/plugin/max/$f" "$PLUGIN_DIR/$f" && echo "  copied: $f"
done

for f in __init__.py core.py; do
    [ -f "$SCRIPT_DIR/plugin/max/team_manager/$f" ] && cp "$SCRIPT_DIR/plugin/max/team_manager/$f" "$PLUGIN_DIR/team_manager/$f" && echo "  copied: team_manager/$f"
done

[ -f "$SCRIPT_DIR/plugin/max/tests/test_adapter.py" ] && cp "$SCRIPT_DIR/plugin/max/tests/test_adapter.py" "$PLUGIN_DIR/tests/test_adapter.py" && echo "  copied: tests/test_adapter.py"

if [ ! -f "$PLUGIN_DIR/role_registry.yaml" ]; then
    [ -f "$SCRIPT_DIR/plugin/max/role_registry.example.yaml" ] && cp "$SCRIPT_DIR/plugin/max/role_registry.example.yaml" "$PLUGIN_DIR/role_registry.yaml" && echo "  copied: role_registry.yaml (example)"
else
    echo "  skipped: role_registry.yaml (exists)"
fi

echo ""
echo "Next steps:"
echo "  1. Edit ~/.hermes/.env with your MAX_BOT_TOKEN and MAX_ALLOWED_USERS"
echo "  2. python3 scripts/verify_max_token.py"
echo "  3. systemctl --user restart hermes-gateway"
echo "  4. /status from MAX"
