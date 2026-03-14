---
name: alpaca-papertrading
description: Paper trade stocks and crypto via Alpaca from the terminal. Includes a live web dashboard, 6 built-in strategies with auto-tick, and full CLI for orders, positions, market data, and analytics.
---

# Alpaca Paper Trading Skill

## When to Use This Skill

Use this skill when the user wants to:
- **Trade stocks or crypto** on Alpaca's paper trading platform
- **Check account info** (balance, equity, buying power, P&L)
- **Place orders** (market, limit, stop, stop-limit, trailing stop, bracket)
- **View positions** and unrealized P&L
- **Get market data** (quotes, historical bars, snapshots)
- **Calculate technical indicators** (RSI, SMA, EMA, MACD, Bollinger Bands)
- **Manage watchlists** on Alpaca
- **Run trading strategies** (Grid, DCA, Momentum, Mean Reversion, Dip Buyer, Momentum Scalper)
- **View trading analytics** (win rate, P&L, symbol breakdown)
- **Launch the web dashboard** to monitor everything in a browser
- **Set up auto-tick** so strategies run automatically via cron

## Natural Language Mapping

The user will speak in natural language. Map their intent to actions:

| User says | Action |
|-----------|--------|
| "buy 10 shares of AAPL" | `alpaca orders market AAPL 10 --side buy` |
| "sell 5 TSLA at limit 250" | `alpaca orders limit TSLA 5 250 --side sell` |
| "buy $500 worth of BTC" | `alpaca orders market BTC/USD 0 --side buy --notional 500` |
| "set a stop loss on AAPL at 140" | `alpaca orders stop AAPL <qty> 140 --side sell` |
| "bracket order NVDA, TP 500, SL 400" | `alpaca orders bracket NVDA <qty> --take-profit 500 --stop-loss 400` |
| "trailing stop AAPL 5%" | `alpaca orders trailing-stop AAPL <qty> --trail-percent 5` |
| "show my portfolio" | `alpaca account summary` |
| "what's my buying power" | `alpaca account buying-power` |
| "show my positions" | `alpaca positions list` |
| "close my AAPL position" | `alpaca positions close AAPL` |
| "close half my MSFT" | `alpaca positions close MSFT --pct 50` |
| "what's AAPL trading at" | `alpaca market quote AAPL` |
| "show me BTC chart" | `alpaca market bars BTC/USD --timeframe 1day --days 30` |
| "RSI of AAPL" | `alpaca market indicators AAPL --type rsi` |
| "all indicators for ETH" | `alpaca market indicators ETH/USD --type all` |
| "show my watchlists" | `alpaca watchlist list` |
| "my open orders" | `alpaca orders list --status open` |
| "cancel all orders" | `alpaca orders cancel-all` |
| "how am I doing" | `alpaca analytics stats` |
| "run DCA $200 into SPY" | `alpaca strategy run dca -p symbol=SPY -p amount=200` |
| "rebalance 50% AAPL 50% MSFT" | `alpaca strategy run rebalance -p 'targets={"AAPL":0.5,"MSFT":0.5}'` |
| "open the dashboard" | `bash scripts/start-web.sh` |
| "share dashboard link" | `bash scripts/start-web.sh` (outputs public URL) |
| "get a permanent link" | `bash scripts/setup-link.sh` (free ngrok static domain) |
| "start auto-trading" | Set up cron with `scripts/auto-tick.py` |

## Setup

### Prerequisites
- Python 3.10+
- Alpaca paper trading API keys (free at alpaca.markets)

### Installation
```bash
git clone https://github.com/serenakeyitan/alpaca-papertrading-CLI.git
cd alpaca-papertrading-CLI/skills/paper-trade
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install flask waitress alpaca-trade-api requests
alpaca configure init  # enter API keys
```

### Config
Config lives at `~/.alpaca-cli/config.json` or `skills/paper-trade/config.json`:
```json
{
  "api_key": "YOUR_ALPACA_API_KEY",
  "secret_key": "YOUR_ALPACA_SECRET_KEY"
}
```

## Key Rules

1. **Paper trading ONLY** — hardcoded to Alpaca's paper trading endpoint. No live trading.
2. **No confirmation required** — orders execute immediately. Warn for large orders (100+ units).
3. **Crypto symbols** use slash format: `BTC/USD`, `ETH/USD`, `SOL/USD`
4. **Stock symbols** are uppercase: `AAPL`, `MSFT`, `TSLA`
5. **All CLI output** uses Rich colored formatting with fallback to plain text.
6. **`--json` flag** available on all CLI commands for machine-readable output.
7. **Market hours** — stock strategies show "MKT CLOSED" outside US market hours; crypto trades 24/7.

## Web Dashboard

A Bloomberg-style live dashboard accessible from any browser. Shows account overview, strategies, watchlist, open orders, and trade log — all auto-refreshing every 5 seconds.

### Launch
```bash
bash scripts/setup-link.sh              # one-time: set up permanent public link (free)
bash scripts/start-web.sh              # default port 8888, with tunnel
bash scripts/start-web.sh --port 9000  # custom port
bash scripts/start-web.sh --no-tunnel  # localhost only
```

### Features
- **5 draggable, resizable panels**: Account, Strategies, Watchlist, Open Orders, Trade Log
- **Panel swap**: drag any panel onto another to swap positions (works across rows)
- **Panel resize**: drag dividers to resize horizontally and vertically
- **Layout persistence**: panel positions and sizes saved to localStorage
- **Permanent public link**: run `bash scripts/setup-link.sh` to claim a free static domain via ngrok (never changes)
- **Cloudflare tunnel fallback**: auto-generates a temporary public URL if no permanent link is set up
- **Crypto + stock data**: separate API endpoints for crypto (v1beta3) vs stock (v2) data
- **Local timezone**: all timestamps converted from UTC to user's local time
- **Market status**: shows "MKT CLOSED" for stock strategies when market is closed

### API Endpoints
| Endpoint | Returns |
|----------|---------|
| `GET /` | Full HTML dashboard |
| `GET /api/account` | Account equity, P&L, buying power |
| `GET /api/strategies` | All strategies with status, P&L, fills |
| `GET /api/watchlist` | Watchlist with prices, change %, sparkline data |
| `GET /api/orders` | Open orders |
| `GET /api/tradelog` | Recent trade log entries (last 100) |
| `GET /api/bars/<symbol>` | 1-min OHLCV bars for stocks |
| `GET /api/bars/<path:symbol>` | 1-min OHLCV bars for crypto (e.g., `BTC/USD`) |

## Strategy Framework

### Built-in Strategies

| Type | Description |
|------|-------------|
| `grid` | Grid trading — places buy/sell orders at fixed intervals around a center price |
| `dca` | Dollar-cost averaging — buys a fixed amount at regular intervals |
| `momentum` | Momentum trading — buys on upward trends, sells on reversals |
| `mean_reversion` | Mean reversion — buys when price drops below average, sells above |
| `dip_buyer` | Dip buyer — buys on significant price dips |
| `momentum_scalper` | Momentum scalper — short-term momentum-based entries and exits |

### Strategy Management
Strategies are managed via `StrategyManager` and persisted in `strategies_state.json`.

**Add a strategy** (via code or dashboard):
```python
from strategy_manager import StrategyManager
mgr = StrategyManager()
mgr.add_strategy("grid", "btc-grid", {
    "symbol": "BTC/USD",
    "grid_size": 10,
    "grid_spacing": 100,
    "order_qty": 0.001,
}, capital_allocated=5000)
```

**Auto-tick via cron** (every 30 seconds):
```bash
# Add to crontab:
* * * * * /path/to/.venv/bin/python /path/to/scripts/auto-tick.py
* * * * * sleep 30 && /path/to/.venv/bin/python /path/to/scripts/auto-tick.py
```

### Custom Strategies
Users can create custom strategies in `~/.alpaca-cli/strategies/`:
```bash
alpaca strategy init my_strategy   # creates template
# edit ~/.alpaca-cli/strategies/my_strategy.py
alpaca strategy run my_strategy -p symbol=AAPL -p qty=10
```
Each strategy extends `BaseStrategy` with helpers: `self.buy()`, `self.sell()`, `self.get_position()`, `self.get_account()`.

## CLI Command Reference

```
alpaca
  account
    info           Full account details
    summary        Quick portfolio summary with P&L
    buying-power   Show buying power
  orders
    market         Place market order
    limit          Place limit order
    stop           Place stop order
    stop-limit     Place stop-limit order
    trailing-stop  Place trailing stop order
    bracket        Place bracket order (entry + TP + SL)
    list           List orders (--status open|closed|all)
    get            Get order details
    cancel         Cancel an order
    cancel-all     Cancel all open orders
  positions
    list           List open positions with P&L
    get            Get position details
    close          Close a position (full or partial)
    close-all      Close all positions
  market
    quote          Latest quote for symbol(s)
    snapshot       Full market snapshot
    bars           Historical OHLCV bars
    indicators     Technical indicators (RSI, SMA, EMA, MACD, BBands)
  watchlist
    list           List watchlists
    get            Get watchlist details
    create         Create watchlist
    add            Add symbol to watchlist
    remove         Remove symbol from watchlist
    update         Update watchlist
    delete         Delete watchlist
  analytics
    stats          Trading statistics (win rate, P&L, etc.)
    symbols        P&L breakdown by symbol
  strategy
    list           List available strategies
    run            Run a strategy
    init           Create custom strategy template
    show           Show strategy source
  configure
    init           Interactive setup
    show           Show current config
    set            Set a config value
    test           Test API connection
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/install.sh` | One-command installation (symlink + pip install) |
| `scripts/setup-link.sh` | One-time setup for permanent public link (free ngrok static domain) |
| `scripts/start-web.sh` | Launch web dashboard with tunnel (ngrok permanent or Cloudflare temporary) |
| `scripts/auto-tick.py` | Cron-compatible script to tick all active strategies |
| `run.sh` | Terminal dashboard launcher with auto-restart |

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | This file — skill definition for Claude |
| `web_dashboard.py` | Live web dashboard (Flask + Waitress) |
| `dashboard.py` | Terminal TUI dashboard |
| `trade.py` | Core trading CLI |
| `strategy_manager.py` | Strategy lifecycle manager |
| `grid_bot.py` | Grid strategy implementation |
| `tick.py` | Single tick runner |
| `strategies/` | Built-in strategy implementations |
| `config.example.json` | Example API config |
| `watchlist.json` | Default watchlist symbols |
| `requirements.txt` | Python dependencies |
| `setup.py` | Python package config |
| `marketplace-entry.json` | Skill store metadata |
