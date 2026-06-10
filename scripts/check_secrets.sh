#!/usr/bin/env bash
# Scan tracked repository files for potential secrets before commit.
# Only files known to git are scanned, so .venv/, .git/, __pycache__/ and
# other untracked local files never produce false positives.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "=== Secrets Scan (tracked files only): $REPO_DIR ==="
echo ""

FOUND=0

tracked_list="$(mktemp)"
source_list="$(mktemp)"
trap 'rm -f "$tracked_list" "$source_list"' EXIT

git ls-files > "$tracked_list"

# Source files to scan for secret patterns, excluding test fixtures,
# examples, the env template and this script itself.
grep -E '\.(py|yaml|yml|toml|md|sh)$' "$tracked_list" \
    | grep -vE '(^examples/|example|test_adapter\.py|check_secrets\.sh|\.env\.example)' \
    > "$source_list" || true

echo "Checking for secret patterns in tracked source files..."
echo "(excluding test fixtures, examples and this script)"
echo ""

# pattern label pairs; scan_pattern returns 0 if any match is found
scan_pattern() {
    local pattern="$1" label="$2"
    local hits=""
    if [ -s "$source_list" ]; then
        hits="$(xargs -a "$source_list" grep -lE "$pattern" 2>/dev/null || true)"
    fi
    if [ -n "$hits" ]; then
        echo "FOUND: $label"
        printf '%s\n' "$hits" | sed 's/^/    /'
        FOUND=$((FOUND + 1))
    fi
}

scan_pattern 'ghp_[a-zA-Z0-9]{30,}'  'GitHub PAT (ghp_)'
scan_pattern 'sk-[a-zA-Z0-9]{20,}'   'OpenAI-style key (sk-)'
scan_pattern 'xoxb-'                 'Slack bot token (xoxb-)'
scan_pattern 'BEGIN PRIVATE KEY'     'Private key material'
# Real-looking token assignment; placeholder values (PASTE..., your_token...,
# <token>, ${VAR}) are fine
token_hits=""
if [ -s "$source_list" ]; then
    token_hits="$(xargs -a "$source_list" grep -nE 'MAX_BOT_TOKEN=[A-Za-z0-9_/+-]{16,}' 2>/dev/null \
        | grep -viE 'PASTE|your_|placeholder|<.*>|\$\{' || true)"
fi
if [ -n "$token_hits" ]; then
    echo "FOUND: Real-looking MAX_BOT_TOKEN assignment"
    printf '%s\n' "$token_hits" | sed 's/^/    /'
    FOUND=$((FOUND + 1))
fi

# Tracked key/certificate files must not exist
key_files="$(grep -E '\.(pem|key|crt|cert|p12|pfx)$' "$tracked_list" || true)"
if [ -n "$key_files" ]; then
    echo "FOUND: Tracked key/certificate files"
    printf '%s\n' "$key_files" | sed 's/^/    /'
    FOUND=$((FOUND + 1))
fi

# .env must not exist in the repo root
if [ -f "$REPO_DIR/.env" ]; then
    echo "ERROR: .env file in repo root!"
    FOUND=$((FOUND + 1))
fi

# .env.example must contain only placeholders
if [ -f "$REPO_DIR/.env.example" ]; then
    if grep -E '=(sk-|ghp_|xoxb-)' "$REPO_DIR/.env.example" | grep -v PASTE | grep -q .; then
        echo "ERROR: Real-looking tokens in .env.example!"
        FOUND=$((FOUND + 1))
    fi
fi

echo ""
if [ "$FOUND" -eq 0 ]; then
    echo "CLEAN — No secrets detected. Safe to commit."
    exit 0
else
    echo "FOUND $FOUND potential issue(s). Review before committing."
    exit 1
fi
