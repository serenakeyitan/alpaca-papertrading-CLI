#!/usr/bin/env bash
# deploy.sh — Deploy the dashboard to Render or show existing deployment URL.
#
# Usage:
#   bash scripts/deploy.sh              # deploy or show link
#   bash scripts/deploy.sh status       # show saved URL
#   bash scripts/deploy.sh set <url>    # save your Render URL
#   bash scripts/deploy.sh reset        # clear saved URL
set -uo pipefail

CONFIG_DIR="$HOME/.alpaca-cli"
DEPLOY_CONFIG="$CONFIG_DIR/deploy.json"
REPO_URL="https://github.com/serenakeyitan/alpaca-papertrading-CLI"
RENDER_DEPLOY_URL="https://render.com/deploy?repo=${REPO_URL}"

# ── Helpers ──────────────────────────────────────────────

_read_url() {
  if [[ -f "$DEPLOY_CONFIG" ]]; then
    python3 -c "import json; print(json.load(open('$DEPLOY_CONFIG')).get('url',''))" 2>/dev/null || echo ""
  fi
}

_save_url() {
  mkdir -p "$CONFIG_DIR"
  python3 -c "
import json
config = {'provider': 'render', 'url': '$1'}
with open('$DEPLOY_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
"
  echo "  ✅ Saved: $1"
}

_open_url() {
  if command -v open &>/dev/null; then
    open "$1"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$1"
  else
    echo "  Open this URL in your browser:"
    echo "  $1"
  fi
}

# ── Commands ─────────────────────────────────────────────

# Status: show saved URL
if [[ "${1:-}" == "status" ]]; then
  echo ""
  URL=$(_read_url)
  if [[ -n "$URL" ]]; then
    echo "  📊 Dashboard: $URL"
    echo "  Provider:    Render"
  else
    echo "  No deployment configured."
    echo "  Run: bash scripts/deploy.sh"
  fi
  echo ""
  exit 0
fi

# Set: save a Render URL
if [[ "${1:-}" == "set" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "  Usage: bash scripts/deploy.sh set https://your-app.onrender.com"
    exit 1
  fi
  URL="$2"
  # Strip trailing slash
  URL="${URL%/}"
  _save_url "$URL"
  exit 0
fi

# Reset: clear saved URL
if [[ "${1:-}" == "reset" ]]; then
  rm -f "$DEPLOY_CONFIG"
  echo "  Deployment config cleared."
  exit 0
fi

# ── Main: Deploy or show link ────────────────────────────

echo ""
echo "  📊 Alpaca Dashboard — Render Deployment"
echo "  ────────────────────────────────────────"
echo ""

URL=$(_read_url)

if [[ -n "$URL" ]]; then
  echo "  ✅ Your dashboard is live at:"
  echo ""
  echo "     $URL"
  echo ""
  echo "  Opening in browser..."
  _open_url "$URL"
  echo ""
  echo "  Commands:"
  echo "    bash scripts/deploy.sh status   Show this info"
  echo "    bash scripts/deploy.sh reset    Clear and redeploy"
  echo ""
  exit 0
fi

# No saved URL — guide user through Render deployment
echo "  No deployment found. Let's set one up!"
echo ""
echo "  Render gives you a free, permanent dashboard URL that"
echo "  auto-deploys on every git push. Takes ~2 minutes."
echo ""
echo "  ── Step 1: Deploy to Render ──"
echo ""
echo "  Opening the Render deploy page..."
echo ""
_open_url "$RENDER_DEPLOY_URL"
echo ""
echo "  If the browser didn't open, go to:"
echo "  $RENDER_DEPLOY_URL"
echo ""
echo "  ── Step 2: Configure ──"
echo ""
echo "  When prompted, set these environment variables:"
echo "    ALPACA_API_KEY      — your Alpaca paper trading API key"
echo "    ALPACA_SECRET_KEY   — your Alpaca paper trading secret key"
echo ""
echo "  Then click 'Apply' and wait for the deploy to finish."
echo ""
echo "  ── Step 3: Save your URL ──"
echo ""
echo "  Once deployed, your URL will look like:"
echo "    https://alpaca-dashboard-xxxx.onrender.com"
echo ""
read -p "  Paste your Render URL here (or press Enter to skip): " USER_URL

if [[ -n "$USER_URL" ]]; then
  # Clean up input
  USER_URL="${USER_URL%/}"
  USER_URL=$(echo "$USER_URL" | sed 's|^[[:space:]]*||;s|[[:space:]]*$||')
  _save_url "$USER_URL"
  echo ""
  echo "  🎉 All set! Your dashboard is live at:"
  echo "     $USER_URL"
  echo ""
  echo "  Every 'git push' auto-deploys the latest code."
  echo "  Run 'bash scripts/deploy.sh' anytime to open it."
else
  echo ""
  echo "  No URL saved. Run this again after deploying:"
  echo "    bash scripts/deploy.sh set https://your-app.onrender.com"
fi
echo ""
