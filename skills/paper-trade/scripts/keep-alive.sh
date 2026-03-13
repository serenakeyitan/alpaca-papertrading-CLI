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
LABEL_DASH="com.openclaw.dashboard"
LABEL_TUNNEL="com.openclaw.tunnel"
PLIST_DASH="$HOME/Library/LaunchAgents/${LABEL_DASH}.plist"
PLIST_TUNNEL="$HOME/Library/LaunchAgents/${LABEL_TUNNEL}.plist"
CLOUDFLARED="$(command -v cloudflared 2>/dev/null || echo /opt/homebrew/bin/cloudflared)"

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
      echo "  Tunnel:    RUNNING"
      echo "  Public:    $(cat "$TUNNEL_URL_FILE")"
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

if [[ ! -f "$CLOUDFLARED" ]]; then
  echo "❌ cloudflared not found. Install: brew install cloudflared"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# ── Unload old agents if present ──────────────────────────

launchctl unload "$PLIST_DASH" 2>/dev/null
launchctl unload "$PLIST_TUNNEL" 2>/dev/null

# Kill any existing processes on the port
lsof -ti :$PORT | xargs kill 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 1

# ── Create tunnel wrapper script ─────────────────────────
# This script starts cloudflared, captures the URL, writes it to a file,
# and also updates the dashboard so it can display the link.

TUNNEL_WRAPPER="$SCRIPT_DIR/scripts/.tunnel-wrapper.sh"
cat > "$TUNNEL_WRAPPER" << 'WRAPPER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8888
URL_FILE="$SCRIPT_DIR/.tunnel_url"
LOG_FILE="/tmp/cloudflared-tunnel.log"

rm -f "$URL_FILE"

# Start cloudflared, tee stderr to log
cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>"$LOG_FILE" &
CF_PID=$!

# Wait for URL to appear (up to 30s)
for i in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -1 || true)
  if [[ -n "$URL" ]]; then
    echo "$URL" > "$URL_FILE"
    break
  fi
  sleep 0.5
done

# Wait for cloudflared to exit (launchd will restart it)
wait $CF_PID
WRAPPER
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
echo "  Tunnel URL will appear in a few seconds..."
echo ""
echo "  Check status:  bash scripts/keep-alive.sh status"
echo "  Stop:          bash scripts/keep-alive.sh stop"
echo ""

# Wait for tunnel URL
for i in $(seq 1 20); do
  if [[ -f "$TUNNEL_URL_FILE" ]]; then
    echo "  🌐 Public: $(cat "$TUNNEL_URL_FILE")"
    echo ""
    break
  fi
  sleep 1
done

if [[ ! -f "$TUNNEL_URL_FILE" ]]; then
  echo "  ⏳ Tunnel still starting. Run: bash scripts/keep-alive.sh status"
fi
