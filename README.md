# Alpaca Paper Trading CLI

A terminal-based paper trading system powered by [Alpaca Markets](https://alpaca.markets/). Includes a Click-based CLI (`alpaca` command), an interactive trading shell, a live Bloomberg-style TUI dashboard, and a multi-strategy automation framework.

## Features

- **All order types**: Market, limit, stop, stop-limit, trailing stop, bracket (OTO)
- **Stocks & crypto**: Trade US equities and crypto (BTC, ETH, SOL, etc.)
- **Technical indicators**: RSI, SMA, EMA, MACD, Bollinger Bands
- **Watchlists**: Create and manage Alpaca watchlists
- **Analytics**: Win rate, P&L tracking, symbol breakdown
- **Live Dashboard**: Real-time TUI with positions, watchlist, orders, and strategy panels
- **Strategy Framework**: Run multiple automated strategies simultaneously:
  - **Grid Trading**: Place limit orders at evenly-spaced price levels
  - **DCA (Dollar Cost Averaging)**: Periodic market buys to accumulate over time
  - **Momentum**: Rank symbols by recent price change, go long top gainers
  - **Mean Reversion**: Buy below rolling average, sell above
  - **RSI-based**: Buy oversold, sell overbought
  - **Rebalance**: Target portfolio allocation
  - **Custom strategies**: Write your own in Python
- **Rich output**: Colored terminal output with fallback to plain text
- **Paper only**: Hardcoded to paper trading endpoint for safety

## Quick Start

```bash
# 1. Clone
git clone https://github.com/serenakeyitan/alpaca-papertrading-CLI.git
cd alpaca-papertrading-CLI

# 2. Auto-install everything (Python, tmux, pip, CLI)
bash scripts/setup-deps.sh

# 3. Configure API keys (get from https://app.alpaca.markets/paper/dashboard/overview)
alpaca configure init

# 4. Trade
alpaca account summary
alpaca orders market AAPL 10 --side buy
alpaca positions list

# 5. Launch tmux trading workspace
bash scripts/tmux-trading.sh
```

## System Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Runtime |
| pip | latest | Package manager |
| tmux | any | Multi-pane trading workspace |
| git | any | Version control |

### Auto-install (recommended)

```bash
bash scripts/setup-deps.sh
```

Detects your OS and installs everything automatically:

| OS | Package Manager | Tested |
|----|-----------------|--------|
| macOS | Homebrew | Yes |
| Ubuntu / Debian | apt | Yes |
| Fedora / RHEL | dnf | Yes |
| Arch / Manjaro | pacman | Yes |
| Alpine | apk | Yes |
| Windows | WSL required | Yes (via WSL) |

### Manual install

```bash
# macOS
brew install python tmux git

# Ubuntu / Debian
sudo apt install python3 python3-pip python3-venv tmux git

# Fedora
sudo dnf install python3 python3-pip tmux git

# Arch
sudo pacman -S python python-pip tmux git

# Then install the CLI
pip install -e .
```

Python packages: `click`, `alpaca-py`, `python-dotenv`, `rich`.

## tmux Trading Workspace

Launch a Bloomberg-style multi-pane trading terminal:

```bash
bash scripts/tmux-trading.sh
```

```
+---------------------+---------------------+
|   PORTFOLIO         |   LIVE QUOTES       |
|   (auto-refresh)    |   (watchlist)       |
+---------------------+---------------------+
|   TRADING SHELL     |   ORDERS / STATS    |
|   (type commands)   |   (auto-refresh)    |
+---------------------+---------------------+
       Window 2: Technical indicators (auto-refresh)
```

Options:

```bash
# Custom session name
bash scripts/tmux-trading.sh --session my-trading

# Custom watchlist
bash scripts/tmux-trading.sh --watchlist "AAPL MSFT BTC/USD ETH/USD SOL/USD"

# Faster refresh (every 10 seconds)
bash scripts/tmux-trading.sh --refresh 10

# Create in background
bash scripts/tmux-trading.sh --no-attach

# Reattach to running session
tmux attach -t paper-trade

# Kill session
tmux kill-session -t paper-trade
```

Keyboard shortcuts (inside tmux):
- `Ctrl+B, D` — detach (session keeps running)
- `Ctrl+B, Arrow` — switch panes
- `Ctrl+B, N` — next window (market indicators)
- `Ctrl+B, P` — previous window

## Configuration

```bash
# Interactive setup (recommended)
alpaca configure init

# Or set manually
alpaca configure set api_key YOUR_KEY
alpaca configure set secret_key YOUR_SECRET

# Or use .env file
cp .env.example .env
# Edit .env with your keys

# Test connection
alpaca configure test
```

API keys are stored in `~/.alpaca-cli/config.json` and `~/.alpaca-cli/.env`.

## Click CLI Commands (`alpaca`)

| Command | Description |
|---------|-------------|
| `alpaca account info` | Full account details |
| `alpaca account summary` | Portfolio summary with P&L |
| `alpaca account buying-power` | Show buying power |
| `alpaca orders market AAPL 10` | Market order |
| `alpaca orders limit AAPL 10 150` | Limit order |
| `alpaca orders stop AAPL 10 145` | Stop order |
| `alpaca orders stop-limit AAPL 10 145 144` | Stop-limit order |
| `alpaca orders trailing-stop AAPL 10 --trail-percent 5` | Trailing stop |
| `alpaca orders bracket AAPL 10 --take-profit 160 --stop-loss 140` | Bracket order |
| `alpaca orders list` | List open orders |
| `alpaca orders cancel <id>` | Cancel order |
| `alpaca orders cancel-all` | Cancel all |
| `alpaca positions list` | List positions with P&L |
| `alpaca positions close AAPL` | Close position |
| `alpaca positions close AAPL --pct 50` | Partial close |
| `alpaca market quote AAPL MSFT` | Latest quotes |
| `alpaca market snapshot AAPL` | Full snapshot |
| `alpaca market bars AAPL --timeframe 1day` | Historical bars |
| `alpaca market indicators AAPL --type all` | Technical indicators |
| `alpaca watchlist list` | List watchlists |
| `alpaca watchlist create 'Tech' -s AAPL -s MSFT` | Create watchlist |
| `alpaca analytics stats` | Trading statistics |
| `alpaca analytics symbols` | P&L by symbol |
| `alpaca strategy list` | List strategies |
| `alpaca strategy run dca -p symbol=SPY -p amount=100` | Run strategy |
| `alpaca strategy init my_strat` | Create custom strategy |

All commands support `--json` flag for machine-readable output.

## Legacy CLI Commands (`trade.py`)

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
| `dashboard.py` | Launch live TUI dashboard |

## Strategy Management

```bash
# Built-in strategies via Click CLI
alpaca strategy run dca -p symbol=SPY -p amount=100
alpaca strategy run rsi -p symbol=AAPL -p period=14 -p oversold=30
alpaca strategy run rebalance -p 'targets={"AAPL":0.4,"MSFT":0.3,"GOOGL":0.3}'

# Create custom strategy
alpaca strategy init mean_reversion
# Edit ~/.alpaca-cli/strategies/mean_reversion.py
alpaca strategy run mean_reversion -p symbol=AAPL -p qty=10

# Legacy strategy management
python trade.py strat add grid AAPL --capital 1000
python trade.py strat add dca TSLA --capital 500
python trade.py strat add momentum "AAPL,TSLA,NVDA" --capital 2000
python trade.py strat list
python tick.py   # Auto-tick (run via cron)
```

## Architecture

```
scripts/
  setup-deps.sh            # Cross-OS dependency installer (Python, tmux, pip, git)
  install.sh               # Claude Code skill installer (symlinks + pip)
  tmux-trading.sh          # Multi-pane tmux trading workspace

alpaca_cli/                # Click-based CLI
  cli.py                   # Main entry point (`alpaca` command)
  commands/
    account.py             # Account info, buying power
    orders.py              # All order types (market/limit/stop/bracket/trailing)
    positions.py           # Position management
    market.py              # Quotes, bars, indicators
    watchlist.py           # Alpaca watchlists
    analytics.py           # Performance stats
    strategy.py            # Strategy framework
    configure.py           # Configuration
  utils/
    config.py              # Config management (.env + JSON)
    client.py              # Alpaca client wrapper (paper=True)
    output.py              # Rich formatted output with fallback
    indicators.py          # Technical indicators (RSI, SMA, EMA, MACD, BBands, VWAP)

SKILL.md                   # Claude Code skill definition
.claude-plugin/plugin.json # Plugin metadata
marketplace-entry.json     # Skill store listing

trade.py                   # Legacy CLI entry point
dashboard.py               # Textual TUI dashboard
strategy_manager.py        # Strategy orchestrator
tick.py                    # Cron tick runner
grid_bot.py                # Legacy grid bot
strategies/
  base.py                  # Abstract strategy base class
  grid.py                  # Grid trading strategy
  dca.py                   # Dollar cost averaging
  momentum.py              # Momentum/trend following
  mean_reversion.py        # Mean reversion strategy
```

## License

MIT
