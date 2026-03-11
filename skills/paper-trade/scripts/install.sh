#!/usr/bin/env bash
# Install the Alpaca Paper Trading CLI skill for Claude Code
#
# Usage:
#   bash scripts/install.sh
#
# What it does:
#   1. Creates a symlink in ~/.claude/skills/alpaca-papertrading
#   2. Installs Python dependencies
#   3. Installs the CLI as an editable package

set -e

SKILL_DIR="$HOME/.claude/skills/alpaca-papertrading"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing Alpaca Paper Trading CLI skill..."

# 1. Symlink into Claude Code skills directory
mkdir -p "$HOME/.claude/skills"
if [ -L "$SKILL_DIR" ]; then
    rm "$SKILL_DIR"
fi
if [ -d "$SKILL_DIR" ]; then
    echo "Warning: $SKILL_DIR already exists as a directory. Skipping symlink."
else
    ln -s "$REPO_DIR" "$SKILL_DIR"
    echo "  Linked $REPO_DIR -> $SKILL_DIR"
fi

# 2. Install Python dependencies
echo "  Installing Python dependencies..."
pip install -e "$REPO_DIR" --quiet

# 3. Verify
if command -v alpaca &> /dev/null; then
    echo ""
    echo "Installation complete!"
    echo "  Run 'alpaca configure init' to set up your API keys."
    echo "  Run 'alpaca --help' to see all commands."
else
    echo ""
    echo "Package installed but 'alpaca' not on PATH."
    echo "  Try: pip install -e $REPO_DIR"
fi
