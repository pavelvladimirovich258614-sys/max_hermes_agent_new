#!/usr/bin/env bash
# Scan repository for potential secrets before commit
# Test files with fake fixtures are excluded
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== Secrets Scan: $REPO_DIR ==="
echo ""

FOUND=0

# Files to always skip (test fixtures, examples, this script)
SKIP_FILES=(
    "check_secrets.sh"
    ".env.example"
    "test_adapter.py"
)

skip_pattern=""
for f in "${SKIP_FILES[@]}"; do
    skip_pattern="${skip_pattern} -e ${f}"
done

echo "Checking for secret patterns in source files..."
echo "(excluding test fixtures and examples)"
echo ""

# Check for high-risk patterns
if find "$REPO_DIR" \( -name "*.py" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" \) \
    | grep -v ${skip_pattern} \
    | xargs grep -lE 'ghp_[a-zA-Z0-9]{30,}' 2>/dev/null | head -5 | grep -q .; then
    echo "FOUND: GitHub PAT (ghp_)"
    FOUND=$((FOUND + 1))
fi

if find "$REPO_DIR" \( -name "*.py" -o -name "*.yaml" -o -name "*.yml" \) \
    | grep -v ${skip_pattern} \
    | xargs grep -lE 'sk-[a-zA-Z0-9]{20,}' 2>/dev/null | head -5 | grep -q .; then
    echo "FOUND: OpenAI-style key (sk-)"
    FOUND=$((FOUND + 1))
fi

# Check for key files
if find "$REPO_DIR" \( -name "*.pem" -o -name "*.key" -o -name "*.cert" -o -name "*.p12" \) | head -1 | grep -q .; then
    echo "FOUND: Key/certificate files"
    FOUND=$((FOUND + 1))
fi

# Check .env not tracked
if [ -f "$REPO_DIR/.env" ]; then
    echo "ERROR: .env file in repo root!"
    FOUND=$((FOUND + 1))
fi

# Check .env.example has only placeholders
if grep -E '=sk-|=ghp_|=xoxb-' "$REPO_DIR/.env.example" 2>/dev/null | grep -v PASTE | grep -q .; then
    echo "ERROR: Real-looking tokens in .env.example!"
    FOUND=$((FOUND + 1))
fi

# Check for long numeric IDs in yaml (excluding examples)
id_files=$(find "$REPO_DIR" -name "*.yaml" -o -name "*.yml" \
    | grep -v example \
    | grep -v ${skip_pattern} \
    | xargs grep -n '[0-9]\{9,\}' 2>/dev/null | head -5)
if [ -n "$id_files" ]; then
    echo "WARNING: Long numeric IDs found in YAML:"
    echo "$id_files"
    FOUND=$((FOUND + 1))
fi

echo ""
if [ "$FOUND" -eq 0 ]; then
    echo "CLEAN — No secrets detected. Safe to commit."
    exit 0
else
    echo "FOUND $FOUND potential issue(s). Review before committing."
    exit 1
fi
