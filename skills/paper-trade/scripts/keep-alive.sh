#!/usr/bin/env bash
# keep-alive.sh — Install launchd agents to keep dashboard + tunnel alive.
#
# Survives Mac sleep, lid close, and reboots. No auth or tokens needed.
#
# Usage:
#   bash scripts/keep-alive.sh           # install and start
#   bash scripts/keep-alive.sh stop      # unload agents
#   bash scripts/keep-alive.sh status    # check status + current URL
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
PORT=8888
TUNNEL_URL_FILE="$SCRIPT_DIR/.tunnel_url"
TUNNEL_CONFIG="$HOME/.alpaca-cli/tunnel.json"
LABEL_DASH="com.openclaw.dashboard"
LABEL_TUNNEL="com.openclaw.tunnel"
PLIST_DASH="$HOME/Library/LaunchAgents/${LABEL_DASH}.plist"
PLIST_TUNNEL="$HOME/Library/LaunchAgents/${LABEL_TUNNEL}.plist"
CLOUDFLARED="$(command -v cloudflared 2>/dev/null || echo /opt/homebrew/bin/cloudflared)"
NGROK="$(command -v ngrok 2>/dev/null || echo /opt/homebrew/bin/ngrok)"

# Detect tunnel provider
TUNNEL_PROVIDER="cloudflared"
NGROK_DOMAIN=""
if [[ -f "$TUNNEL_CONFIG" ]]; then
  TUNNEL_PROVIDER=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('provider','cloudflared'))" 2>/dev/null || echo "cloudflared")
  NGROK_DOMAIN=$(python3 -c "import json; print(json.load(open('$TUNNEL_CONFIG')).get('domain',''))" 2>/dev/null || echo "")
fi

# ── Commands ──────────────────────────────────────────────

if [[ "${1:-}" == "stop" ]]; then
  echo "Stopping dashboard and tunnel..."
  launchctl unload "$PLIST_DASH" 2>/dev/null
  launchctl unload "$PLIST_TUNNEL" 2>/dev/null
  rm -f "$PLIST_DASH" "$PLIST_TUNNEL" "$TUNNEL_URL_FILE"
  echo "Done."
  exit 0
fi

if [[ "${1:-}" == "status" ]]; then
  echo ""
  # Dashboard
  if launchctl list "$LABEL_DASH" &>/dev/null; then
    echo "  Dashboard: RUNNING (port $PORT)"
  else
    echo "  Dashboard: STOPPED"
  fi
  # Tunnel
  if launchctl list "$LABEL_TUNNEL" &>/dev/null; then
    if [[ -f "$TUNNEL_URL_FILE" ]]; then
      echo "  Tunnel:    RUNNING ($TUNNEL_PROVIDER)"
      URL="$(cat "$TUNNEL_URL_FILE")"
      echo "  Public:    $URL"
      if [[ "$TUNNEL_PROVIDER" == "ngrok" ]]; then
        echo "  Type:      permanent (never changes)"
      else
        echo "  Type:      temporary (changes on restart)"
      fi
    else
      echo "  Tunnel:    STARTING (URL not yet captured)"
    fi
  else
    echo "  Tunnel:    STOPPED"
  fi
  echo ""
  exit 0
fi

# ── Preflight ─────────────────────────────────────────────

if [[ ! -f "$VENV_PYTHON" ]]; then
  echo "❌ Virtual env not found at $SCRIPT_DIR/.venv"
  exit 1
fi

if [[ "$TUNNEL_PROVIDER" == "ngrok" ]]; then
  if [[ ! -f "$NGROK" ]] && ! command -v ngrok &>/dev/null; then
    echo "❌ ngrok not found. Install: brew install ngrok"
    echo "   Or run: bash scripts/setup-link.sh"
    exit 1
  fi
elif [[ ! -f "$CLOUDFLARED" ]] && ! command -v cloudflared &>/dev/null; then
  echo "❌ cloudflared not found. Install: brew install cloudflared"
  echo "   For a permanent link instead: bash scripts/setup-link.sh"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# ── Unload old agents if present ──────────────────────────

launchctl unload "$PLIST_DASH" 2>/dev/null
launchctl unload "$PLIST_TUNNEL" 2>/dev/null

# Kill any existing processes on the port
lsof -ti :$PORT | xargs kill 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
pkill -f "ngrok http" 2>/dev/null
sleep 1

# ── Create tunnel wrapper script ─────────────────────────
# This script starts cloudflared, captures the URL, writes it to a file,
# and also updates the dashboard so it can display the link.

TUNNEL_WRAPPER="$SCRIPT_DIR/scripts/.tunnel-wrapper.sh"

if [[ "$TUNNEL_PROVIDER" == "ngrok" ]] && [[ -n "$NGROK_DOMAIN" ]]; then
  # ngrok permanent tunnel wrapper
  cat > "$TUNNEL_WRAPPER" << WRAPPER
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "\$0")/.." && pwd)"
PORT=8888
URL_FILE="\$SCRIPT_DIR/.tunnel_url"
DOMAIN="$NGROK_DOMAIN"

echo "https://\$DOMAIN" > "\$URL_FILE"

# Start ngrok with permanent static domain
ngrok http "\$PORT" --url="\$DOMAIN" --log=stdout --log-format=json > /tmp/ngrok-dashboard.log 2>&1
WRAPPER
else
  # cloudflared temporary tunnel wrapper
  cat > "$TUNNEL_WRAPPER" << 'WRAPPER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8888
URL_FILE="$SCRIPT_DIR/.tunnel_url"
LOG_FILE="/tmp/cloudflared-tunnel.log"

rm -f "$URL_FILE"

cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>"$LOG_FILE" &
CF_PID=$!

for i in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -1 || true)
  if [[ -n "$URL" ]]; then
    echo "$URL" > "$URL_FILE"
    break
  fi
  sleep 0.5
done

wait $CF_PID
WRAPPER
fi
chmod +x "$TUNNEL_WRAPPER"

# ── Dashboard plist ───────────────────────────────────────

cat > "$PLIST_DASH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL_DASH}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${SCRIPT_DIR}/web_dashboard.py</string>
    <string>--port</string>
    <string>${PORT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/openclaw-dashboard.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/openclaw-dashboard.log</string>
  <key>ThrottleInterval</key>
  <integer>5</integer>
</dict>
</plist>
EOF

# ── Tunnel plist ──────────────────────────────────────────

cat > "$PLIST_TUNNEL" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL_TUNNEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${TUNNEL_WRAPPER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/openclaw-tunnel.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/openclaw-tunnel.log</string>
  <key>ThrottleInterval</key>
  <integer>10</integer>
</dict>
</plist>
EOF

# ── Load agents ───────────────────────────────────────────

launchctl load "$PLIST_DASH"
launchctl load "$PLIST_TUNNEL"

echo ""
echo "  ✅ Dashboard and tunnel installed as launchd agents"
echo "  ────────────────────────────────────────────────────"
echo "  Dashboard: http://127.0.0.1:$PORT"
echo "  Provider:  $TUNNEL_PROVIDER"

if [[ "$TUNNEL_PROVIDER" == "ngrok" ]] && [[ -n "$NGROK_DOMAIN" ]]; then
  echo "  🌐 Public: https://$NGROK_DOMAIN  (permanent)"
  echo ""
  echo "  This link never changes. Share it anywhere."
else
  echo "  Tunnel URL will appear in a few seconds..."
fi
echo ""
echo "  Check status:  bash scripts/keep-alive.sh status"
echo "  Stop:          bash scripts/keep-alive.sh stop"
echo ""

if [[ "$TUNNEL_PROVIDER" != "ngrok" ]]; then
  # Wait for cloudflared URL
  for i in $(seq 1 20); do
    if [[ -f "$TUNNEL_URL_FILE" ]]; then
      echo "  🌐 Public: $(cat "$TUNNEL_URL_FILE")"
      echo "  ⚠️  This URL changes on restart. For a permanent link: bash scripts/setup-link.sh"
      echo ""
      break
    fi
    sleep 1
  done

  if [[ ! -f "$TUNNEL_URL_FILE" ]]; then
    echo "  ⏳ Tunnel still starting. Run: bash scripts/keep-alive.sh status"
  fi
fi
