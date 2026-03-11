#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Alpaca Paper Trading — tmux Trading Workspace
# ──────────────────────────────────────────────────────────────────────
# Creates a multi-pane tmux session for paper trading:
#
#   ┌─────────────────────┬─────────────────────┐
#   │                     │                     │
#   │   PORTFOLIO         │   WATCHLIST          │
#   │   (auto-refresh)    │   (live quotes)      │
#   │                     │                     │
#   ├─────────────────────┼─────────────────────┤
#   │                     │                     │
#   │   TRADING SHELL     │   ORDERS / LOGS      │
#   │   (input commands)  │   (open orders)      │
#   │                     │                     │
#   └─────────────────────┴─────────────────────┘
#
# Usage:
#   bash scripts/tmux-trading.sh                    # Default layout
#   bash scripts/tmux-trading.sh --session myname   # Custom session name
#   bash scripts/tmux-trading.sh --watchlist "AAPL MSFT TSLA BTC/USD"
#   bash scripts/tmux-trading.sh --no-attach        # Create but don't attach
#
# Requirements: tmux, alpaca CLI (pip install -e .)
# ──────────────────────────────────────────────────────────────────────

set -e

# ── Defaults ──────────────────────────────────────────────────────────

SESSION_NAME="paper-trade"
WATCHLIST_SYMBOLS="AAPL MSFT TSLA NVDA AMZN GOOGL BTC/USD ETH/USD"
REFRESH_INTERVAL=30
NO_ATTACH=false

# ── Parse arguments ──────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session|-s)
            SESSION_NAME="$2"
            shift 2
            ;;
        --watchlist|-w)
            WATCHLIST_SYMBOLS="$2"
            shift 2
            ;;
        --refresh|-r)
            REFRESH_INTERVAL="$2"
            shift 2
            ;;
        --no-attach)
            NO_ATTACH=true
            shift
            ;;
        --help|-h)
            echo "Usage: bash scripts/tmux-trading.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --session, -s NAME      Session name (default: paper-trade)"
            echo "  --watchlist, -w SYMBOLS  Space-separated symbols (default: AAPL MSFT TSLA ...)"
            echo "  --refresh, -r SECONDS   Auto-refresh interval (default: 30)"
            echo "  --no-attach             Create session without attaching"
            echo "  --help, -h              Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ── Preflight checks ─────────────────────────────────────────────────

if ! command -v tmux &> /dev/null; then
    echo "Error: tmux is not installed."
    echo "  Run: bash scripts/setup-deps.sh"
    exit 1
fi

if ! command -v alpaca &> /dev/null; then
    echo "Error: alpaca CLI is not installed."
    echo "  Run: pip install -e . && alpaca configure init"
    exit 1
fi

# ── Kill existing session if running ──────────────────────────────────

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists. Attaching..."
    if [ "$NO_ATTACH" = false ]; then
        tmux attach-session -t "$SESSION_NAME"
    fi
    exit 0
fi

# ── Build the auto-refresh commands ───────────────────────────────────

# Top-left: Portfolio + Positions (auto-refresh)
PORTFOLIO_CMD="watch -n $REFRESH_INTERVAL -c 'echo \"=== ACCOUNT ===\"; alpaca account summary 2>/dev/null; echo \"\"; echo \"=== POSITIONS ===\"; alpaca positions list 2>/dev/null'"

# Top-right: Live quotes for watchlist (auto-refresh)
QUOTE_CMD="watch -n $REFRESH_INTERVAL -c 'alpaca market quote $WATCHLIST_SYMBOLS 2>/dev/null'"

# Bottom-left: Interactive shell for trading
TRADE_CMD="echo '╔══════════════════════════════════════════════╗'; echo '║   Alpaca Paper Trading — Command Pane       ║'; echo '║                                              ║'; echo '║   Examples:                                  ║'; echo '║     alpaca orders market AAPL 10 --side buy  ║'; echo '║     alpaca market indicators BTC/USD          ║'; echo '║     alpaca positions close TSLA --pct 50      ║'; echo '║     alpaca strategy run dca -p symbol=SPY     ║'; echo '║                                              ║'; echo '╚══════════════════════════════════════════════╝'; exec \$SHELL"

# Bottom-right: Open orders (auto-refresh)
ORDERS_CMD="watch -n $REFRESH_INTERVAL -c 'echo \"=== OPEN ORDERS ===\"; alpaca orders list --status open 2>/dev/null; echo \"\"; echo \"=== ANALYTICS ===\"; alpaca analytics stats --days 7 2>/dev/null'"

# ── Create tmux session ──────────────────────────────────────────────

echo "Creating trading workspace: $SESSION_NAME"
echo "  Symbols: $WATCHLIST_SYMBOLS"
echo "  Refresh: ${REFRESH_INTERVAL}s"

# Create session with first pane (top-left: portfolio)
tmux new-session -d -s "$SESSION_NAME" -n "trading" "$PORTFOLIO_CMD"

# Split right for watchlist quotes (top-right)
tmux split-window -h -t "$SESSION_NAME:trading" "$QUOTE_CMD"

# Split bottom-left (below portfolio)
tmux select-pane -t "$SESSION_NAME:trading.0"
tmux split-window -v -t "$SESSION_NAME:trading.0" "$TRADE_CMD"

# Split bottom-right (below quotes)
tmux select-pane -t "$SESSION_NAME:trading.2"
tmux split-window -v -t "$SESSION_NAME:trading.2" "$ORDERS_CMD"

# Focus on the trading input pane (bottom-left)
tmux select-pane -t "$SESSION_NAME:trading.2"

# ── Optional: Create a second window for market data ──────────────────

tmux new-window -t "$SESSION_NAME" -n "market" "watch -n 60 -c 'echo \"=== MARKET INDICATORS ===\"; for sym in $WATCHLIST_SYMBOLS; do echo \"\"; echo \"--- \$sym ---\"; alpaca market indicators \$sym --type all --days 30 2>/dev/null; done'"

# Go back to trading window
tmux select-window -t "$SESSION_NAME:trading"

# ── Attach ────────────────────────────────────────────────────────────

echo ""
echo "Workspace ready!"
echo "  Detach:  Ctrl+B, then D"
echo "  Reattach: tmux attach -t $SESSION_NAME"
echo "  Kill:    tmux kill-session -t $SESSION_NAME"
echo ""

if [ "$NO_ATTACH" = false ]; then
    tmux attach-session -t "$SESSION_NAME"
fi
