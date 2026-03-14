#!/usr/bin/env bash
# start-web.sh — Launch the Alpaca web dashboard with optional Cloudflare tunnel.
#
# Usage:
#   bash scripts/start-web.sh              # default port 8888
#   bash scripts/start-web.sh --port 9000  # custom port
#   bash scripts/start-web.sh --no-tunnel  # skip tunnel, localhost only
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
PORT=8888
TUNNEL=true
TUNNEL_CONFIG="$HOME/.alpaca-cli/tunnel.json"
TUNNEL_URL_FILE="$SCRIPT_DIR/.tunnel_url"

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --port) PORT="$2"; shift 2 ;;
    --no-tunnel) TUNNEL=false; shift ;;
    *) shift ;;
  esac
done

# Preflight checks
if [[ ! -f "$VENV_PYTHON" ]]; then
  echo "❌ Virtual env not found. Run: cd $SCRIPT_DIR && python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

if [[ ! -f "$HOME/.alpaca-cli/config.json" ]] && [[ ! -f "$SCRIPT_DIR/config.json" ]]; then
  echo "❌ No Alpaca config found. Run: alpaca configure init"
  exit 1
fi

cleanup() {
  echo ""
  echo "  Shutting down..."
  [[ -n "${TUNNEL_PID:-}" ]] && kill "$TUNNEL_PID" 2>/dev/null
  [[ -n "${DASH_PID:-}" ]] && kill "$DASH_PID" 2>/dev/null
  wait 2>/dev/null
  echo "  Done."
}
trap cleanup EXIT INT TERM

# Start dashboard
echo ""
echo "  📊 Alpaca Paper Trading — Web Dashboard"
echo "  ────────────────────────────────────────"
"$VENV_PYTHON" "$SCRIPT_DIR/web_dashboard.py" --port "$PORT" --reload &
DASH_PID=$!
sleep 1.5

# Check it started
if ! kill -0 "$DASH_PID" 2>/dev/null; then
  echo "  ❌ Dashboard failed to start. Check logs above."
  exit 1
fi

echo "  ✅ Local:   http://127.0.0.1:$PORT"

# Start tunnel
if $TUNNEL; then
  # Check for permanent ngrok link first
  if [[ -f "$TUNNEL_CONFIG" ]]; then
    PROVIDER=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('provider',''))" 2>/dev/null)
    DOMAIN=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('domain',''))" 2>/dev/null)
  fi

  if [[ "${PROVIDER:-}" == "ngrok" ]] && [[ -n "${DOMAIN:-}" ]] && command -v ngrok &>/dev/null; then
    echo "  ⏳ Starting ngrok tunnel (permanent link)..."
    ngrok http "$PORT" --url="$DOMAIN" --log=stdout --log-format=json >/tmp/ngrok-dashboard.log 2>&1 &
    TUNNEL_PID=$!

    # Wait for tunnel to be ready (up to 15s)
    for i in $(seq 1 30); do
      if curl -s "http://127.0.0.1:4040/api/tunnels" 2>/dev/null | grep -q "$DOMAIN"; then
        TUNNEL_URL="https://$DOMAIN"
        echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
        echo "  🌐 Public:  $TUNNEL_URL  (permanent)"
        echo ""
        echo "  This link never changes. Share it anywhere."
        echo "  Dashboard auto-refreshes every 5 seconds."
        break
      fi
      sleep 0.5
    done

    if [[ -z "${TUNNEL_URL:-}" ]]; then
      if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "  ⚠️  ngrok failed to start. Check: cat /tmp/ngrok-dashboard.log"
        echo "     Falling back to Cloudflare quick tunnel..."
        PROVIDER=""  # fall through to cloudflared
      else
        echo "  ⚠️  ngrok started but couldn't confirm URL."
        echo "     Your link should still work: https://$DOMAIN"
        echo "$DOMAIN" > "$TUNNEL_URL_FILE"
      fi
    fi
  fi

  # Fallback: cloudflared quick tunnel (temporary URL)
  if [[ "${PROVIDER:-}" != "ngrok" ]] || [[ -z "${DOMAIN:-}" ]]; then
    if command -v cloudflared &>/dev/null; then
      echo "  ⏳ Starting Cloudflare tunnel (temporary link)..."
      TUNNEL_LOG=$(mktemp)
      cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>"$TUNNEL_LOG" &
      TUNNEL_PID=$!

      for i in $(seq 1 30); do
        TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
        if [[ -n "$TUNNEL_URL" ]]; then
          echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
          echo "  🌐 Public:  $TUNNEL_URL"
          echo ""
          echo "  ⚠️  This URL changes each restart."
          echo "  For a permanent link: bash scripts/setup-link.sh"
          echo "  Dashboard auto-refreshes every 5 seconds."
          break
        fi
        sleep 0.5
      done

      if [[ -z "${TUNNEL_URL:-}" ]]; then
        echo "  ⚠️  Tunnel started but couldn't detect URL."
        echo "     Check: cat $TUNNEL_LOG"
      fi
      rm -f "$TUNNEL_LOG"
    else
      echo ""
      echo "  ℹ️  No tunnel provider found."
      echo "     For a permanent link: bash scripts/setup-link.sh"
      echo "     For a temporary link:  brew install cloudflared"
    fi
  fi
else
  echo ""
  echo "  Tunnel skipped (--no-tunnel)."
fi

echo ""
echo "  Press Ctrl+C to stop."
echo ""

# Wait for dashboard process
wait "$DASH_PID"
