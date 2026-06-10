#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/max"

echo "=== Uninstall MAX Hermes Agent Plugin ==="
echo "Removes: $PLUGIN_DIR"
echo "Keeps:   .env, profiles/, state/"
read -p "Continue? (yes/no): " confirm
[ "$confirm" = "yes" ] || { echo "Cancelled."; exit 0; }

[ -d "$PLUGIN_DIR" ] && rm -rf "$PLUGIN_DIR" && echo "Removed." || echo "Not found."
