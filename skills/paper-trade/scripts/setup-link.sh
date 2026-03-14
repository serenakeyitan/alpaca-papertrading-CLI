#!/usr/bin/env bash
# setup-link.sh — Set up a permanent public link for your dashboard.
#
# Uses ngrok's free static domain (1 per account, never changes).
# One-time setup: ~2 minutes, no credit card required.
#
# Usage:
#   bash scripts/setup-link.sh          # interactive setup
#   bash scripts/setup-link.sh status   # show current config
#   bash scripts/setup-link.sh reset    # remove saved config
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$HOME/.alpaca-cli"
TUNNEL_CONFIG="$CONFIG_DIR/tunnel.json"

# ── Status ────────────────────────────────────────────────

if [[ "${1:-}" == "status" ]]; then
  echo ""
  if [[ -f "$TUNNEL_CONFIG" ]]; then
    PROVIDER=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('provider','?'))" 2>/dev/null)
    DOMAIN=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('domain','?'))" 2>/dev/null)
    echo "  Tunnel provider: $PROVIDER"
    echo "  Permanent URL:   https://$DOMAIN"
  else
    echo "  No permanent link configured."
    echo "  Run: bash scripts/setup-link.sh"
  fi
  echo ""
  exit 0
fi

# ── Reset ─────────────────────────────────────────────────

if [[ "${1:-}" == "reset" ]]; then
  rm -f "$TUNNEL_CONFIG"
  echo "  Tunnel config removed. Falling back to temporary Cloudflare URLs."
  exit 0
fi

# ── Interactive Setup ─────────────────────────────────────

echo ""
echo "  🔗 Permanent Dashboard Link Setup"
echo "  ──────────────────────────────────"
echo ""
echo "  This gives your dashboard a permanent URL that never changes,"
echo "  even across restarts and reboots. Free, takes ~2 minutes."
echo ""

# Check if already configured
if [[ -f "$TUNNEL_CONFIG" ]]; then
  DOMAIN=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('domain',''))" 2>/dev/null)
  if [[ -n "$DOMAIN" ]]; then
    echo "  You already have a permanent link: https://$DOMAIN"
    echo ""
    read -p "  Reconfigure? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      exit 0
    fi
  fi
fi

# Step 1: Install ngrok
echo "  Step 1: Install ngrok"
echo "  ─────────────────────"
if command -v ngrok &>/dev/null; then
  echo "  ✅ ngrok is installed."
else
  echo "  ngrok not found. Installing via Homebrew..."
  if command -v brew &>/dev/null; then
    brew install ngrok 2>&1 | tail -1
    if command -v ngrok &>/dev/null; then
      echo "  ✅ ngrok installed."
    else
      echo "  ❌ Install failed. Try manually: brew install ngrok"
      exit 1
    fi
  else
    echo "  ❌ Homebrew not found. Install ngrok manually:"
    echo "     https://ngrok.com/download"
    exit 1
  fi
fi
echo ""

# Step 2: Auth token
echo "  Step 2: Connect your (free) ngrok account"
echo "  ──────────────────────────────────────────"

# Check if already authed
if ngrok config check &>/dev/null 2>&1; then
  EXISTING_TOKEN=$(ngrok config check 2>&1 | grep -c "valid" || true)
fi

# Check if authtoken is already set by trying to look at the config
NGROK_CONFIG_FILE=$(ngrok config check 2>&1 | grep -oE '/[^ ]+ngrok[^ ]*' | head -1 || true)
HAS_TOKEN=false
if [[ -n "$NGROK_CONFIG_FILE" ]] && [[ -f "$NGROK_CONFIG_FILE" ]]; then
  if grep -q "authtoken:" "$NGROK_CONFIG_FILE" 2>/dev/null; then
    HAS_TOKEN=true
  fi
fi

if $HAS_TOKEN; then
  echo "  ✅ ngrok authtoken already configured."
else
  echo ""
  echo "  1. Sign up (free) at: https://dashboard.ngrok.com/signup"
  echo "     (GitHub / Google SSO works)"
  echo ""
  echo "  2. Copy your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken"
  echo ""
  read -p "  Paste your authtoken here: " AUTHTOKEN
  if [[ -z "$AUTHTOKEN" ]]; then
    echo "  ❌ No token provided."
    exit 1
  fi
  ngrok config add-authtoken "$AUTHTOKEN" 2>&1
  echo "  ✅ Authtoken saved."
fi
echo ""

# Step 3: Claim static domain
echo "  Step 3: Claim your free static domain"
echo "  ─────────────────────────────────────"
echo ""
echo "  1. Go to: https://dashboard.ngrok.com/domains"
echo "  2. Click 'Create Domain' (free — 1 per account)"
echo "  3. You'll get a domain like: your-name-here.ngrok-free.app"
echo ""
read -p "  Paste your static domain here: " STATIC_DOMAIN

# Clean up input — strip protocol and trailing slashes
STATIC_DOMAIN=$(echo "$STATIC_DOMAIN" | sed 's|^https\?://||' | sed 's|/.*||')

if [[ -z "$STATIC_DOMAIN" ]]; then
  echo "  ❌ No domain provided."
  exit 1
fi

# Validate it looks right
if [[ ! "$STATIC_DOMAIN" == *".ngrok"* ]] && [[ ! "$STATIC_DOMAIN" == *".app"* ]]; then
  echo "  ⚠️  That doesn't look like an ngrok domain."
  read -p "  Use it anyway? (y/N) " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

# Save config
mkdir -p "$CONFIG_DIR"
python3 -c "
import json
config = {'provider': 'ngrok', 'domain': '$STATIC_DOMAIN'}
with open('$TUNNEL_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
"

echo ""
echo "  ✅ Permanent link configured!"
echo "  ──────────────────────────────────────"
echo "  URL: https://$STATIC_DOMAIN"
echo ""
echo "  Your dashboard will always be available at this URL."
echo "  Start it with:  bash scripts/start-web.sh"
echo "  Keep it alive:  bash scripts/keep-alive.sh"
echo ""
