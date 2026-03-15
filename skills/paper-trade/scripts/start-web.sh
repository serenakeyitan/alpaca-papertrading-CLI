#!/usr/bin/env bash
# start-web.sh — Launch the Alpaca web dashboard locally.
#
# Usage:
#   bash scripts/start-web.sh              # default port 8888
#   bash scripts/start-web.sh --port 9000  # custom port
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
PORT=8888

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --port) PORT="$2"; shift 2 ;;
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

echo ""
echo "  📊 Alpaca Paper Trading — Web Dashboard"
echo "  ────────────────────────────────────────"

"$VENV_PYTHON" "$SCRIPT_DIR/web_dashboard.py" --port "$PORT" --reload &
DASH_PID=$!
sleep 1.5

if ! kill -0 "$DASH_PID" 2>/dev/null; then
  echo "  ❌ Dashboard failed to start. Check logs above."
  exit 1
fi

echo "  ✅ Local:   http://127.0.0.1:$PORT"
echo ""
echo "  For a permanent public URL, deploy to Render (see README)."
echo ""
echo "  Press Ctrl+C to stop."
echo ""

cleanup() {
  echo ""
  echo "  Shutting down..."
  kill "$DASH_PID" 2>/dev/null
  wait 2>/dev/null
  echo "  Done."
}
trap cleanup EXIT INT TERM

wait "$DASH_PID"
