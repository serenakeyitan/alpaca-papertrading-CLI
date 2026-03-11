"""Position commands – view open positions, P&L, close positions."""

from typing import Optional

import click

from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_trading_client
from alpaca_cli.utils.output import (
    format_table,
    format_item,
    format_json,
    format_pnl,
    format_pct,
    echo_success,
    echo_error,
    echo_info,
    echo_warn,
    RICH_AVAILABLE,
    console,
)


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def positions(ctx: click.Context, json_mode: bool) -> None:
    """View and manage open positions."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@positions.command("list")
@click.option("--sort", type=click.Choice(["symbol", "pnl", "value", "pct"]), default="symbol", help="Sort by")
@click.pass_context
def list_positions(ctx: click.Context, sort: str) -> None:
    """List all open positions with P&L."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    pos_list = client.get_all_positions()

    if not pos_list:
        echo_info("No open positions")
        return

    rows = [_position_to_dict(p) for p in pos_list]

    # Sort
    sort_keys = {
        "symbol": lambda r: r["symbol"],
        "pnl": lambda r: r["_unrealized_pl"],
        "value": lambda r: r["_market_value"],
        "pct": lambda r: r["_unrealized_plpc"],
    }
    rows.sort(key=sort_keys.get(sort, sort_keys["symbol"]), reverse=(sort in ("pnl", "value", "pct")))

    if json_mode:
        format_json(rows)
        return

    # Calculate totals
    total_value = sum(r["_market_value"] for r in rows)
    total_pnl = sum(r["_unrealized_pl"] for r in rows)
    total_cost = sum(r["_cost_basis"] for r in rows)
    total_pct = (total_pnl / total_cost * 100) if total_cost else 0

    format_table(
        rows,
        columns=["symbol", "side", "qty", "avg_entry", "current_price", "market_value", "unrealized_pl", "unrealized_plpc", "allocation"],
        headers=["Symbol", "Side", "Qty", "Avg Entry", "Price", "Value", "P&L", "P&L %", "Alloc %"],
        title="Open Positions",
    )

    # Totals row
    if RICH_AVAILABLE:
        pnl_str = format_pnl(total_pnl)
        pct_str = format_pct(total_pct)
        console.print(f"\n  Total Value: ${total_value:>12,.2f}    Total P&L: {pnl_str} ({pct_str})")
    else:
        sign = "+" if total_pnl >= 0 else ""
        click.echo(f"\n  Total Value: ${total_value:>12,.2f}    Total P&L: ${sign}{total_pnl:,.2f} ({sign}{total_pct:.2f}%)")

    # Concentration warning
    for r in rows:
        alloc = r["_market_value"] / total_value * 100 if total_value else 0
        if alloc > 25:
            echo_warn(f"{r['symbol']} represents {alloc:.1f}% of portfolio (concentration risk)")


@positions.command("get")
@click.argument("symbol")
@click.pass_context
def get_position(ctx: click.Context, symbol: str) -> None:
    """Get details for a specific position."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        pos = client.get_open_position(symbol.upper())
        data = _position_to_dict(pos)

        if json_mode:
            format_json(data)
            return

        format_item(data, [
            ("symbol", "Symbol"),
            ("side", "Side"),
            ("qty", "Quantity"),
            ("avg_entry", "Avg Entry"),
            ("current_price", "Current Price"),
            ("market_value", "Market Value"),
            ("cost_basis", "Cost Basis"),
            ("unrealized_pl", "Unrealized P&L"),
            ("unrealized_plpc", "P&L %"),
            ("change_today", "Change Today"),
        ])
    except APIError as e:
        echo_error(f"Position not found: {e}")


@positions.command("close")
@click.argument("symbol")
@click.option("--qty", type=float, default=None, help="Partial close quantity")
@click.option("--pct", type=float, default=None, help="Close percentage (e.g. 50 for 50%)")
@click.pass_context
def close_position(ctx: click.Context, symbol: str, qty: Optional[float], pct: Optional[float]) -> None:
    """Close a position (full or partial)."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        params: dict = {}
        if qty:
            params["qty"] = str(qty)
        elif pct:
            params["percentage"] = str(pct / 100)

        order = client.close_position(symbol.upper(), **params)
        if json_mode:
            format_json({"symbol": symbol.upper(), "status": "closing", "order_id": str(order.id)})
        else:
            desc = f"{qty} units" if qty else f"{pct}%" if pct else "full"
            echo_success(f"Closing {desc} of {symbol.upper()} (order: {order.id})")
    except APIError as e:
        echo_error(f"Close failed: {e}")


@positions.command("close-all")
@click.pass_context
def close_all_positions(ctx: click.Context) -> None:
    """Close all open positions."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        closed = client.close_all_positions(cancel_orders=True)
        if json_mode:
            format_json({"closed": len(closed)})
        else:
            echo_success(f"Closing {len(closed)} positions (orders cancelled)")
    except APIError as e:
        echo_error(f"Close all failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────


def _position_to_dict(pos) -> dict:
    """Convert a Position object to a display-friendly dict."""
    market_value = float(pos.market_value or 0)
    unrealized_pl = float(pos.unrealized_pl or 0)
    unrealized_plpc = float(pos.unrealized_plpc or 0) * 100
    cost_basis = float(pos.cost_basis or 0)
    current_price = float(pos.current_price or 0)
    change_today = float(pos.change_today or 0) * 100

    return {
        "symbol": pos.symbol,
        "side": pos.side.value if pos.side else "long",
        "qty": str(pos.qty),
        "avg_entry": f"${float(pos.avg_entry_price):,.2f}" if pos.avg_entry_price else "-",
        "current_price": f"${current_price:,.2f}",
        "market_value": f"${market_value:,.2f}",
        "cost_basis": f"${cost_basis:,.2f}",
        "unrealized_pl": f"{'+'if unrealized_pl>=0 else ''}${unrealized_pl:,.2f}",
        "unrealized_plpc": f"{'+'if unrealized_plpc>=0 else ''}{unrealized_plpc:.2f}%",
        "change_today": f"{'+'if change_today>=0 else ''}{change_today:.2f}%",
        "allocation": "",  # filled by caller
        # Hidden numeric fields for sorting
        "_unrealized_pl": unrealized_pl,
        "_unrealized_plpc": unrealized_plpc,
        "_market_value": market_value,
        "_cost_basis": cost_basis,
    }
