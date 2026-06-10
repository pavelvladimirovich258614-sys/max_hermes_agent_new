#!/usr/bin/env bash
# Restart Hermes Gateway
set -euo pipefail

echo "Restarting Hermes Gateway..."

if systemctl --user restart hermes-gateway 2>/dev/null; then
    echo "Waiting for startup..."
    sleep 15
    if systemctl --user is-active hermes-gateway >/dev/null 2>&1; then
        echo "Gateway is active."
        grep "max connected" ~/.hermes/logs/gateway.log 2>/dev/null | tail -1 || true
    else
        echo "WARNING: Gateway not active after restart."
        systemctl --user status hermes-gateway 2>/dev/null || true
    fi
elif command -v hermes >/dev/null 2>&1; then
    hermes gateway restart
    echo "Gateway restarted via hermes CLI."
else
    echo "ERROR: Cannot restart gateway. Use systemctl or hermes CLI."
    exit 1
fi
