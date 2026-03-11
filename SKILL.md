---
name: alpaca-papertrading
description: Paper trade stocks and crypto via Alpaca from the terminal. Supports all order types, technical indicators, watchlists, analytics, and custom strategies.
---

# Alpaca Paper Trading CLI Skill

## When to Use This Skill

Use this skill when the user wants to:
- **Trade stocks or crypto** on Alpaca's paper trading platform
- **Check account info** (balance, equity, buying power, P&L)
- **Place orders** (market, limit, stop, stop-limit, trailing stop, bracket)
- **View positions** and unrealized P&L
- **Get market data** (quotes, historical bars, snapshots)
- **Calculate technical indicators** (RSI, SMA, EMA, MACD, Bollinger Bands)
- **Manage watchlists** on Alpaca
- **Run trading strategies** (DCA, RSI-based, rebalance, or custom)
- **View trading analytics** (win rate, P&L, symbol breakdown)

## Natural Language Mapping

The user will speak in natural language. Map their intent to CLI commands:

| User says | CLI command |
|-----------|-------------|
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

## Setup

The CLI is installed at the project root. To use it:

```bash
cd /Users/keyitan/alpaca-papertrading-CLI
pip install -e .
alpaca configure init
```

## Key Rules

1. **Paper trading ONLY** - This is hardcoded to Alpaca's paper trading endpoint. No live trading.
2. **No confirmation required** - Orders execute immediately. Warn for large orders (100+ units).
3. **Crypto symbols** use slash format: BTC/USD, ETH/USD, SOL/USD
4. **Stock symbols** are uppercase: AAPL, MSFT, TSLA
5. **All output** uses rich colored formatting with fallback to plain text.
6. **--json flag** available on all commands for machine-readable output.

## Command Reference

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

## Custom Strategies

Users can create custom strategies in `~/.alpaca-cli/strategies/`:

```bash
alpaca strategy init my_strategy   # creates template
# edit ~/.alpaca-cli/strategies/my_strategy.py
alpaca strategy run my_strategy -p symbol=AAPL -p qty=10
```

Each strategy extends `BaseStrategy` with helpers: `self.buy()`, `self.sell()`, `self.get_position()`, `self.get_account()`.
