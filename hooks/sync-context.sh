#!/bin/bash
# Quite Frankly — manual personal-context sync
#
# Runs the same copy as the pre-commit hook, but on demand.
# Useful when you want to update the project copy without making another commit
# yet (e.g., previewing the change locally before staging).
#
# Usage:
#   bash hooks/sync-context.sh

set -e

CANONICAL="$HOME/Claude/About Me/personal-context.md"
REPO_ROOT="$(git rev-parse --show-toplevel)"
LOCAL="$REPO_ROOT/personal-context.md"

if [ ! -f "$CANONICAL" ]; then
    echo "Error: canonical context file not found at $CANONICAL"
    exit 1
fi

if cmp -s "$CANONICAL" "$LOCAL" 2>/dev/null; then
    echo "personal-context.md is already in sync with canonical."
    exit 0
fi

cp "$CANONICAL" "$LOCAL"
echo "Synced personal-context.md from canonical:"
echo "  source: $CANONICAL"
echo "  target: $LOCAL"
echo
echo "When ready to ship: git add personal-context.md && git commit"
