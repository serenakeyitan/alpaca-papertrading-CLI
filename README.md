# Alpaca Paper Trading CLI

A terminal-based paper trading system powered by [Alpaca Markets](https://alpaca.markets/). Includes an interactive CLI, a live Bloomberg-style TUI dashboard, and a multi-strategy automation framework.

## Features

- **Interactive CLI** — Buy, sell, quote, watch, and manage orders from your terminal
- **Live Dashboard** — Real-time TUI with positions, watchlist, orders, and strategy panels
- **Strategy Framework** — Run multiple automated strategies simultaneously:
  - **Grid Trading** — Place limit orders at evenly-spaced price levels
  - **DCA (Dollar Cost Averaging)** — Periodic market buys to accumulate over time
  - **Momentum** — Rank symbols by recent price change, go long top gainers
  - **Mean Reversion** — Buy below rolling average, sell above

## Quick Start

```bash
# 1. Clone
git clone https://github.com/serenakeyitan/alpaca-papertrading-CLI.git
cd alpaca-papertrading-CLI

# 2. Set up Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install alpaca-trade-api rich textual

# 3. Configure API keys (get from https://app.alpaca.markets/paper/dashboard/overview)
cp config.example.json config.json
# Edit config.json with your paper trading API key and secret

# 4. Run
python trade.py shell     # Interactive trading shell
python dashboard.py       # Live TUI dashboard
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `trade.py account` | Show account balance and buying power |
| `trade.py buy AAPL 10` | Buy 10 shares of AAPL |
| `trade.py sell AAPL 5` | Sell 5 shares of AAPL |
| `trade.py quote AAPL` | Get current quote |
| `trade.py positions` | Show all open positions |
| `trade.py orders` | Show recent orders |
| `trade.py watch AAPL TSLA` | Live price watch |
| `trade.py history` | Trade history |
| `trade.py strat add grid AAPL` | Add a grid strategy on AAPL |
| `trade.py strat list` | List all strategies |
| `trade.py shell` | Interactive trading shell |
| `trade.py dashboard` | Launch live TUI |

## Strategy Management

```bash
# Add strategies
python trade.py strat add grid AAPL --capital 1000
python trade.py strat add dca TSLA --capital 500
python trade.py strat add momentum "AAPL,TSLA,NVDA" --capital 2000
python trade.py strat add mean_reversion SPY --capital 1000

# Control
python trade.py strat pause <id>
python trade.py strat resume <id>
python trade.py strat remove <id>
python trade.py strat list

# Auto-tick (run via cron)
python tick.py
```

## Architecture

```
trade.py              # CLI entry point
dashboard.py          # Textual TUI dashboard
strategy_manager.py   # Strategy orchestrator
tick.py               # Cron tick runner
grid_bot.py           # Legacy grid bot
strategies/
  base.py             # Abstract strategy base class
  grid.py             # Grid trading strategy
  dca.py              # Dollar cost averaging
  momentum.py         # Momentum/trend following
  mean_reversion.py   # Mean reversion strategy
```

## License

MIT
