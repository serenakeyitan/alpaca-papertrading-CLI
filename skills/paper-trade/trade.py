#!/usr/bin/env python3
"""OpenClaw Paper Trading CLI — Alpaca paper trading from your terminal."""

import argparse
import json
import os
import sys
import readline
from pathlib import Path

# Use venv's packages
VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    sys.path.insert(0, str(p))

import alpaca_trade_api as tradeapi
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()
CONFIG_PATH = Path(__file__).parent / "config.json"
BANNER = """[bold blue]
  ╔═══════════════════════════════════════╗
  ║   OpenClaw Paper Trading CLI          ║
  ║   Powered by Alpaca Markets           ║
  ╚═══════════════════════════════════════╝[/bold blue]"""

# ── Formatting ────────────────────────────────────────────

def fmt_money(value):
    """Format dollar amount with magnitude awareness."""
    v = float(value)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.1f}M"
    elif abs(v) >= 10_000:
        return f"${v/1_000:,.1f}K"
    else:
        return f"${v:,.2f}"

def fmt_pnl(value):
    """Format P&L with color."""
    v = float(value)
    sign = "+" if v >= 0 else ""
    color = "green" if v >= 0 else "red"
    return f"[{color}]{sign}{fmt_money(v)}[/{color}]"

def fmt_pnl_pct(value):
    """Format P&L percentage with color."""
    v = float(value) * 100
    sign = "+" if v >= 0 else ""
    color = "green" if v >= 0 else "red"
    return f"[{color}]{sign}{v:.2f}%[/{color}]"

def fmt_side(side):
    """Format buy/sell side with color."""
    s = side.upper()
    color = "green" if s == "BUY" else "red"
    return f"[bold {color}]{s}[/bold {color}]"

def fmt_status(status):
    """Format order status."""
    colors = {
        "filled": "green", "partially_filled": "yellow",
        "new": "blue", "accepted": "blue",
        "canceled": "dim", "expired": "dim",
        "rejected": "red", "pending_new": "yellow",
    }
    color = colors.get(status, "white")
    return f"[{color}]{status}[/{color}]"

DASH = "[dim]---[/dim]"

# ── Config ────────────────────────────────────────────────

def resolve_config(args=None):
    """Three-tier config: CLI flag > env var > config file."""
    api_key = None
    secret_key = None
    source = "none"

    # Tier 3: config file
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        api_key = cfg.get("api_key")
        secret_key = cfg.get("secret_key")
        source = "config file"

    # Tier 2: environment
    if os.environ.get("ALPACA_API_KEY"):
        api_key = os.environ["ALPACA_API_KEY"]
        secret_key = os.environ.get("ALPACA_SECRET_KEY", secret_key)
        source = "environment"

    # Tier 1: CLI flags
    if args and getattr(args, "api_key_flag", None):
        api_key = args.api_key_flag
        secret_key = getattr(args, "secret_key_flag", secret_key)
        source = "CLI flag"

    return api_key, secret_key, source

def get_api(args=None):
    api_key, secret_key, source = resolve_config(args)
    if not api_key or not secret_key:
        console.print("[red]Not configured.[/red] Run: [bold]trade setup[/bold]")
        sys.exit(1)
    return tradeapi.REST(
        api_key, secret_key,
        base_url="https://paper-api.alpaca.markets",
        api_version="v2"
    )

# ── Output helpers ────────────────────────────────────────

def output_json(data):
    print(json.dumps(data, indent=2, default=str))

def output_error(msg, output_format="table"):
    if output_format == "json":
        output_json({"error": msg})
    else:
        console.print(f"[red]{msg}[/red]")

# ── Commands ──────────────────────────────────────────────

def cmd_setup(args):
    """Interactive setup wizard."""
    console.print(BANNER)
    console.print()

    # Step 1: API Keys
    console.print("[bold][1/3] API Key Configuration[/bold]")
    if args.api_key and args.secret_key:
        api_key = args.api_key
        secret_key = args.secret_key
    else:
        console.print("  Get your keys at: [link]https://app.alpaca.markets[/link]")
        console.print("  Switch to Paper Trading → API Keys → Generate New Key")
        console.print()
        api_key = input("  API Key: ").strip()
        secret_key = input("  Secret Key: ").strip()

    if not api_key or not secret_key:
        console.print("  [red]✗[/red] API keys required")
        return

    config = {"api_key": api_key, "secret_key": secret_key}
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    os.chmod(CONFIG_PATH, 0o600)
    console.print("  [green]✓[/green] Keys saved")

    # Step 2: Connection test
    console.print()
    console.print("[bold][2/3] Testing Connection[/bold]")
    try:
        api = tradeapi.REST(
            api_key, secret_key,
            base_url="https://paper-api.alpaca.markets",
            api_version="v2"
        )
        account = api.get_account()
        console.print(f"  [green]✓[/green] Connected — {fmt_money(account.equity)} equity")
    except Exception as e:
        console.print(f"  [red]✗[/red] Connection failed: {e}")
        return

    # Step 3: Next steps
    console.print()
    console.print("[bold][3/3] Ready![/bold]")
    console.print()
    console.print(Panel(
        "[bold]Next steps:[/bold]\n"
        "  trade account          View your paper account\n"
        "  trade watch            Check market prices\n"
        "  trade buy AAPL --qty 5 Place your first trade",
        border_style="blue",
        title="Get Started",
        expand=False,
    ))

def cmd_account(args):
    """Show account summary."""
    api = get_api(args)
    a = api.get_account()

    if args.output == "json":
        output_json({
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "today_pnl": float(a.equity) - float(a.last_equity),
            "status": a.status,
        })
        return

    pnl = float(a.equity) - float(a.last_equity)
    pnl_pct = (pnl / float(a.last_equity) * 100) if float(a.last_equity) > 0 else 0

    table = Table(
        title="Paper Trading Account",
        box=box.ROUNDED,
        show_header=False,
        title_style="bold blue",
        min_width=40,
    )
    table.add_column("Field", style="bold", width=16)
    table.add_column("Value", justify="right", width=20)

    table.add_row("Equity", fmt_money(a.equity))
    table.add_row("Cash", fmt_money(a.cash))
    table.add_row("Buying Power", fmt_money(a.buying_power))
    table.add_row("Today P&L", fmt_pnl(pnl))
    table.add_row("Today P&L %", fmt_pnl_pct(pnl / float(a.last_equity)) if float(a.last_equity) > 0 else DASH)
    table.add_row("Status", f"[green]{a.status}[/green]" if a.status == "ACTIVE" else a.status)

    console.print()
    console.print(table)

def cmd_buy(args):
    """Place a buy order."""
    api = get_api(args)
    symbol = args.symbol.upper()

    order_params = {
        "symbol": symbol,
        "side": "buy",
        "type": args.type,
        "time_in_force": args.tif,
    }
    if args.notional:
        order_params["notional"] = args.notional
    elif args.qty:
        order_params["qty"] = args.qty
    else:
        order_params["qty"] = 1

    if args.type == "limit":
        if not args.limit_price:
            output_error("Limit orders require --limit-price", args.output)
            return
        order_params["limit_price"] = args.limit_price

    try:
        order = api.submit_order(**order_params)
    except Exception as e:
        output_error(str(e), args.output)
        return

    if args.output == "json":
        output_json({"id": order.id, "symbol": order.symbol, "side": "buy",
                      "qty": str(order.qty), "type": order.type, "status": order.status})
        return

    console.print(f"  [green]✓[/green] BUY {symbol} | qty={order.qty or 'notional'} | {order.type} | [dim]{order.id[:8]}[/dim]")

def cmd_sell(args):
    """Place a sell order."""
    api = get_api(args)
    symbol = args.symbol.upper()

    order_params = {
        "symbol": symbol,
        "side": "sell",
        "type": args.type,
        "time_in_force": args.tif,
    }
    if args.qty:
        order_params["qty"] = args.qty
    else:
        try:
            pos = api.get_position(symbol)
            order_params["qty"] = pos.qty
        except Exception:
            output_error(f"No position in {symbol}", args.output)
            return

    if args.type == "limit":
        if not args.limit_price:
            output_error("Limit orders require --limit-price", args.output)
            return
        order_params["limit_price"] = args.limit_price

    try:
        order = api.submit_order(**order_params)
    except Exception as e:
        output_error(str(e), args.output)
        return

    if args.output == "json":
        output_json({"id": order.id, "symbol": order.symbol, "side": "sell",
                      "qty": str(order.qty), "type": order.type, "status": order.status})
        return

    console.print(f"  [red]✓[/red] SELL {symbol} | qty={order.qty} | {order.type} | [dim]{order.id[:8]}[/dim]")

def cmd_positions(args):
    """Show current positions."""
    api = get_api(args)
    positions = api.list_positions()

    if args.output == "json":
        output_json([{
            "symbol": p.symbol, "qty": str(p.qty),
            "avg_entry": float(p.avg_entry_price), "current": float(p.current_price),
            "pnl": float(p.unrealized_pl), "pnl_pct": float(p.unrealized_plpc),
            "market_value": float(p.market_value),
        } for p in positions])
        return

    if not positions:
        console.print("  [dim]No open positions.[/dim]")
        return

    table = Table(title="Positions", box=box.ROUNDED, title_style="bold blue")
    table.add_column("Symbol", style="bold")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Mkt Value", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("P&L %", justify="right")

    total_pnl = 0
    total_value = 0
    for p in positions:
        pnl = float(p.unrealized_pl)
        total_pnl += pnl
        total_value += float(p.market_value)
        table.add_row(
            p.symbol, str(p.qty),
            fmt_money(p.avg_entry_price), fmt_money(p.current_price),
            fmt_money(p.market_value),
            fmt_pnl(p.unrealized_pl), fmt_pnl_pct(p.unrealized_plpc),
        )

    table.add_section()
    table.add_row("[bold]Total[/bold]", "", "", "", fmt_money(total_value), fmt_pnl(total_pnl), "")

    console.print()
    console.print(table)

def cmd_orders(args):
    """Show recent orders."""
    api = get_api(args)
    status = args.status if args.status != "all" else None
    orders = api.list_orders(status=status, limit=args.limit)

    if args.output == "json":
        output_json([{
            "id": o.id, "symbol": o.symbol, "side": o.side, "qty": str(o.qty),
            "type": o.type, "status": o.status,
            "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "submitted_at": str(o.submitted_at),
        } for o in orders])
        return

    if not orders:
        console.print("  [dim]No orders found.[/dim]")
        return

    table = Table(title="Orders", box=box.ROUNDED, title_style="bold blue")
    table.add_column("Time", style="dim")
    table.add_column("Side")
    table.add_column("Symbol", style="bold")
    table.add_column("Qty", justify="right")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Fill Price", justify="right")
    table.add_column("ID", style="dim")

    for o in orders:
        t = o.submitted_at.strftime("%m/%d %H:%M") if o.submitted_at else DASH
        price = fmt_money(o.filled_avg_price) if o.filled_avg_price else DASH
        table.add_row(
            t, fmt_side(o.side), o.symbol, str(o.qty or DASH),
            o.type, fmt_status(o.status), price, o.id[:8],
        )

    console.print()
    console.print(table)

def cmd_cancel(args):
    """Cancel an order or all orders."""
    api = get_api(args)
    try:
        if args.order_id == "all":
            api.cancel_all_orders()
            console.print("  [green]✓[/green] All open orders cancelled")
        else:
            api.cancel_order(args.order_id)
            console.print(f"  [green]✓[/green] Order [dim]{args.order_id[:8]}[/dim] cancelled")
    except Exception as e:
        output_error(str(e), args.output)

def cmd_quote(args):
    """Get current quote for symbols."""
    api = get_api(args)
    results = []

    for symbol in args.symbols:
        symbol = symbol.upper()
        try:
            trade = api.get_latest_trade(symbol)
            quote = api.get_latest_quote(symbol)
            results.append({
                "symbol": symbol,
                "last": trade.price,
                "bid": quote.bid_price, "bid_size": quote.bid_size,
                "ask": quote.ask_price, "ask_size": quote.ask_size,
                "spread": quote.ask_price - quote.bid_price if quote.ask_price and quote.bid_price else None,
            })
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})

    if args.output == "json":
        output_json(results)
        return

    for r in results:
        if "error" in r:
            console.print(f"  [red]{r['symbol']}: {r['error']}[/red]")
            continue

        table = Table(box=box.ROUNDED, show_header=False, min_width=30, title=r["symbol"], title_style="bold")
        table.add_column("Field", style="bold", width=12)
        table.add_column("Value", justify="right", width=16)
        table.add_row("Last", fmt_money(r["last"]))
        table.add_row("Bid", f"{fmt_money(r['bid'])} × {r['bid_size']}")
        table.add_row("Ask", f"{fmt_money(r['ask'])} × {r['ask_size']}")
        if r["spread"] is not None:
            table.add_row("Spread", fmt_money(r["spread"]))
        console.print(table)

def cmd_history(args):
    """Show trade history."""
    api = get_api(args)
    activities = api.get_activities(activity_types="FILL", direction="desc")
    activities = list(activities)[:args.limit]

    if args.output == "json":
        output_json([{
            "symbol": a.symbol, "side": a.side, "qty": str(a.qty),
            "price": float(a.price),
            "total": float(a.price) * float(a.qty),
            "time": str(a.transaction_time) if hasattr(a, 'transaction_time') else None,
        } for a in activities])
        return

    if not activities:
        console.print("  [dim]No trade history.[/dim]")
        return

    table = Table(title="Trade History", box=box.ROUNDED, title_style="bold blue")
    table.add_column("Time", style="dim")
    table.add_column("Side")
    table.add_column("Symbol", style="bold")
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Total", justify="right")

    for a in activities:
        date = str(a.transaction_time)[:16] if hasattr(a, 'transaction_time') else DASH
        total = float(a.price) * float(a.qty)
        table.add_row(
            date, fmt_side(a.side), a.symbol,
            str(a.qty), fmt_money(a.price), fmt_money(total),
        )

    console.print()
    console.print(table)

def cmd_close(args):
    """Close a position or all positions."""
    api = get_api(args)
    try:
        if args.symbol == "all":
            api.close_all_positions()
            console.print("  [green]✓[/green] All positions closed")
        else:
            symbol = args.symbol.upper()
            api.close_position(symbol)
            console.print(f"  [green]✓[/green] {symbol} position closed")
    except Exception as e:
        output_error(str(e), args.output)

def cmd_watch(args):
    """Watchlist — quick overview of multiple symbols."""
    api = get_api(args)
    symbols = args.symbols or ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META"]
    results = []

    for s in symbols:
        s = s.upper()
        try:
            trade = api.get_latest_trade(s)
            quote = api.get_latest_quote(s)
            results.append({
                "symbol": s, "price": trade.price,
                "bid": quote.bid_price, "ask": quote.ask_price,
            })
        except Exception:
            results.append({"symbol": s, "price": None, "bid": None, "ask": None})

    if args.output == "json":
        output_json(results)
        return

    table = Table(title="Watchlist", box=box.ROUNDED, title_style="bold blue")
    table.add_column("Symbol", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")

    for r in results:
        if r["price"] is None:
            table.add_row(r["symbol"], DASH, DASH, DASH)
        else:
            table.add_row(
                r["symbol"], fmt_money(r["price"]),
                fmt_money(r["bid"]) if r["bid"] else DASH,
                fmt_money(r["ask"]) if r["ask"] else DASH,
            )

    console.print()
    console.print(table)

def cmd_grid(args):
    """Run grid trading bot (legacy)."""
    grid_path = Path(__file__).parent / "grid_bot.py"
    venv_python = Path(__file__).parent / ".venv/bin/python"
    action = args.action if hasattr(args, 'action') and args.action else "status"
    os.execv(str(venv_python), [str(venv_python), str(grid_path), action])

def cmd_strat(args):
    """Manage strategies."""
    sys.path.insert(0, str(Path(__file__).parent))
    from strategy_manager import StrategyManager
    sm = StrategyManager()

    if args.strat_action == "list":
        strats = sm.list_strategies()
        if not strats:
            console.print("  [dim]No strategies. Use: trade strat add <type> <name> <symbol>[/dim]")
            return
        table = Table(title="Strategies", box=box.ROUNDED, title_style="bold blue")
        table.add_column("Name", style="bold")
        table.add_column("Type", style="cyan")
        table.add_column("Status")
        table.add_column("Capital", justify="right")
        table.add_column("Real P&L", justify="right")
        table.add_column("Unrl P&L", justify="right")
        table.add_column("Total P&L", justify="right")
        table.add_column("Fills", justify="right")
        table.add_column("Last Tick", style="dim")
        for s in strats:
            pnl = s["total_pnl"]
            pc = "green" if pnl >= 0 else "red"
            ps = "+" if pnl >= 0 else ""
            table.add_row(
                s["name"], s["type"], s["status"],
                fmt_money(s["capital_allocated"]),
                fmt_pnl(s["realized_pnl"]),
                fmt_pnl(s["unrealized_pnl"]),
                Text(f"{ps}{fmt_money(pnl)}", style=pc),
                str(s["total_fills"]),
                (s["last_tick"] or "—")[:19],
            )
        console.print(table)

    elif args.strat_action == "add":
        stype = args.type
        name = args.name
        symbol = args.symbol.upper()
        capital = args.capital

        if stype == "grid":
            config = {"symbol": symbol, "grid_pct": 6, "num_grids": 10, "qty_per_grid": 2}
        elif stype == "dca":
            config = {"symbol": symbol, "amount_per_buy": 500, "interval_minutes": 30}
        elif stype == "momentum":
            config = {"symbols": [symbol], "lookback_minutes": 60,
                      "top_n": 3, "amount_per_position": 3000, "rebalance_minutes": 60}
        elif stype == "mean_reversion":
            config = {"symbol": symbol, "window": 20, "threshold_pct": 2.0, "qty": 5}
        else:
            console.print(f"[red]Unknown type: {stype}[/red]")
            return

        sm.add_strategy(stype, name, config, capital)
        console.print(f"  [green]✓[/green] Strategy [bold]{name}[/bold] ({stype}) added — {symbol}, capital={fmt_money(capital)}")

    elif args.strat_action == "remove":
        api = get_api(args)
        sm.remove_strategy(args.name, api)
        console.print(f"  [green]✓[/green] Strategy [bold]{args.name}[/bold] removed")

    elif args.strat_action == "pause":
        sm.pause_strategy(args.name)
        console.print(f"  [yellow]❚❚[/yellow] Strategy [bold]{args.name}[/bold] paused")

    elif args.strat_action == "resume":
        sm.resume_strategy(args.name)
        console.print(f"  [green]▶[/green] Strategy [bold]{args.name}[/bold] resumed")

    elif args.strat_action == "tick":
        api = get_api(args)
        console.print("  Running tick on all strategies...")
        sm.tick_all(api)
        console.print("  [green]✓[/green] Tick complete")
        # Show updated status
        args.strat_action = "list"
        cmd_strat(args)

def cmd_dashboard(args):
    """Launch Bloomberg-style trading terminal."""
    dashboard_path = Path(__file__).parent / "dashboard.py"
    venv_python = Path(__file__).parent / ".venv/bin/python"
    os.execv(str(venv_python), [str(venv_python), str(dashboard_path)])

def cmd_shell(args):
    """Interactive trading shell."""
    console.print(BANNER)
    console.print("  Type commands without 'trade' prefix. [dim]Ctrl+D to exit.[/dim]")
    console.print()

    while True:
        try:
            line = input("\033[1;34mtrade>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Goodbye![/dim]")
            break

        if not line:
            continue
        if line in ("exit", "quit", "q"):
            console.print("  [dim]Goodbye![/dim]")
            break
        if line in ("shell",):
            console.print("  [dim]Already in shell mode.[/dim]")
            continue
        if line == "help":
            line = "--help"

        try:
            shell_args = build_parser().parse_args(line.split())
            dispatch(shell_args)
        except SystemExit:
            pass  # argparse calls sys.exit on --help or error
        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")

# ── Parser ────────────────────────────────────────────────

def _add_global_args(parser):
    """Add global flags to a parser or subparser."""
    parser.add_argument("-o", "--output", default="table", choices=["table", "json"],
                        help="Output format (default: table)")
    parser.add_argument("--api-key", dest="api_key_flag", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--secret-key", dest="secret_key_flag", default=None, help=argparse.SUPPRESS)

def build_parser():
    parser = argparse.ArgumentParser(
        prog="trade",
        description="OpenClaw Paper Trading CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  trade setup                          Interactive setup wizard
  trade setup <KEY> <SECRET>           Quick setup with keys
  trade account                        Account summary
  trade buy AAPL --qty 10              Buy 10 shares
  trade buy NVDA --notional 5000       Buy $5000 worth
  trade sell AAPL                      Sell all shares
  trade pos                            Show positions
  trade quote AAPL TSLA                Get quotes
  trade watch                          Watchlist
  trade orders                         Recent orders
  trade history                        Trade fills
  trade close all                      Close everything
  trade strat list                     List all strategies
  trade strat add grid my-grid NVDA    Add grid strategy on NVDA
  trade strat add dca my-dca AAPL      Add DCA strategy on AAPL
  trade strat pause my-grid            Pause strategy
  trade strat resume my-grid           Resume strategy
  trade strat remove my-grid           Remove strategy
  trade strat tick                     Run one tick cycle
  trade dash                           Live trading terminal
  trade pos -o json                    JSON output for scripting
"""
    )
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command")

    # setup
    p = sub.add_parser("setup", help="Configure API keys")
    p.add_argument("api_key", nargs="?")
    p.add_argument("secret_key", nargs="?")
    _add_global_args(p)

    # account
    p = sub.add_parser("account", help="Account summary"); _add_global_args(p)
    p = sub.add_parser("acc", help="Account summary"); _add_global_args(p)

    # buy
    p = sub.add_parser("buy", help="Buy a stock")
    p.add_argument("symbol")
    p.add_argument("--qty", type=float)
    p.add_argument("--notional", type=float, help="Dollar amount")
    p.add_argument("--type", default="market", choices=["market", "limit"])
    p.add_argument("--limit-price", type=float)
    p.add_argument("--tif", default="day", choices=["day", "gtc", "ioc"])
    _add_global_args(p)

    # sell
    p = sub.add_parser("sell", help="Sell a stock")
    p.add_argument("symbol")
    p.add_argument("--qty", type=float)
    p.add_argument("--type", default="market", choices=["market", "limit"])
    p.add_argument("--limit-price", type=float)
    p.add_argument("--tif", default="day", choices=["day", "gtc", "ioc"])
    _add_global_args(p)

    # positions
    p = sub.add_parser("positions", help="Show positions"); _add_global_args(p)
    p = sub.add_parser("pos", help="Show positions"); _add_global_args(p)

    # orders
    p = sub.add_parser("orders", help="Show orders")
    p.add_argument("--status", default="all", choices=["all", "open", "closed"])
    p.add_argument("--limit", type=int, default=20)
    _add_global_args(p)

    # cancel
    p = sub.add_parser("cancel", help="Cancel order(s)")
    p.add_argument("order_id", help="Order ID or 'all'")
    _add_global_args(p)

    # quote
    p = sub.add_parser("quote", help="Get stock quote")
    p.add_argument("symbols", nargs="+")
    _add_global_args(p)

    # history
    p = sub.add_parser("history", help="Trade history")
    p.add_argument("--limit", type=int, default=20)
    _add_global_args(p)

    # close
    p = sub.add_parser("close", help="Close position(s)")
    p.add_argument("symbol", help="Symbol or 'all'")
    _add_global_args(p)

    # watchlist
    p = sub.add_parser("watch", help="Watchlist quotes")
    p.add_argument("symbols", nargs="*")
    _add_global_args(p)

    # grid bot
    p = sub.add_parser("grid", help="Grid trading bot")
    p.add_argument("action", nargs="?", default="status",
                   choices=["once", "loop", "status", "reset"],
                   help="once|loop|status|reset")
    _add_global_args(p)

    # dashboard
    p = sub.add_parser("dashboard", help="Bloomberg-style trading terminal")
    _add_global_args(p)
    p = sub.add_parser("dash", help="Bloomberg-style trading terminal")
    _add_global_args(p)

    # strat
    strat_parser = sub.add_parser("strat", help="Manage strategies")
    strat_sub = strat_parser.add_subparsers(dest="strat_action")

    # strat list
    strat_sub.add_parser("list", help="List all strategies")

    # strat add
    sp = strat_sub.add_parser("add", help="Add a strategy")
    sp.add_argument("type", choices=["grid", "dca", "momentum", "mean_reversion"])
    sp.add_argument("name", help="Strategy name")
    sp.add_argument("symbol", help="Symbol to trade")
    sp.add_argument("--capital", type=float, default=10000, help="Capital to allocate (default $10K)")

    # strat remove
    sp = strat_sub.add_parser("remove", help="Remove a strategy")
    sp.add_argument("name")

    # strat pause
    sp = strat_sub.add_parser("pause", help="Pause a strategy")
    sp.add_argument("name")

    # strat resume
    sp = strat_sub.add_parser("resume", help="Resume a strategy")
    sp.add_argument("name")

    # strat tick
    strat_sub.add_parser("tick", help="Run one tick cycle")

    _add_global_args(strat_parser)

    # shell
    p = sub.add_parser("shell", help="Interactive trading shell")
    _add_global_args(p)

    return parser

def dispatch(args):
    commands = {
        "setup": cmd_setup,
        "account": cmd_account,
        "acc": cmd_account,
        "buy": cmd_buy,
        "sell": cmd_sell,
        "positions": cmd_positions,
        "pos": cmd_positions,
        "orders": cmd_orders,
        "cancel": cmd_cancel,
        "quote": cmd_quote,
        "history": cmd_history,
        "close": cmd_close,
        "watch": cmd_watch,
        "shell": cmd_shell,
        "grid": cmd_grid,
        "strat": cmd_strat,
        "dashboard": cmd_dashboard,
        "dash": cmd_dashboard,
    }
    if args.command in commands:
        commands[args.command](args)
    else:
        build_parser().print_help()

def main():
    parser = build_parser()
    args = parser.parse_args()
    dispatch(args)

if __name__ == "__main__":
    main()
