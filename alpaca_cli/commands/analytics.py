"""Analytics commands – basic performance stats from closed orders and account history."""

from datetime import datetime, timedelta
from typing import Optional

import click

from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_trading_client
from alpaca_cli.utils.output import (
    format_item,
    format_json,
    format_panel,
    format_pnl,
    format_pct,
    echo_info,
    echo_error,
    echo_warn,
    RICH_AVAILABLE,
    console,
)


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def analytics(ctx: click.Context, json_mode: bool) -> None:
    """Performance analytics and trading statistics."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@analytics.command("stats")
@click.option("--days", type=int, default=30, help="Lookback period in days")
@click.pass_context
def trading_stats(ctx: click.Context, days: int) -> None:
    """Show trading statistics (win rate, avg return, total P&L).

    Analyzes closed orders over the specified period.
    """
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        # Fetch closed orders
        after = datetime.now() - timedelta(days=days)
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=after,
            limit=500,
        )
        closed_orders = client.get_orders(req)

        # Filter to filled orders only
        filled = [o for o in closed_orders if o.status and o.status.value == "filled"]

        if not filled:
            echo_info(f"No filled orders in the last {days} days")
            return

        # Group trades by symbol
        trades_by_symbol: dict = {}
        for order in filled:
            sym = order.symbol
            if sym not in trades_by_symbol:
                trades_by_symbol[sym] = {"buys": [], "sells": []}

            side = order.side.value if order.side else "buy"
            price = float(order.filled_avg_price) if order.filled_avg_price else 0
            qty = float(order.filled_qty) if order.filled_qty else 0

            trades_by_symbol[sym][f"{side}s"].append({
                "price": price,
                "qty": qty,
                "time": order.filled_at,
            })

        # Calculate realized P&L per symbol (simplified: match buys to sells sequentially)
        total_realized_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        total_trades = 0
        pnl_per_trade: list[float] = []

        for sym, sides in trades_by_symbol.items():
            buys = sides["buys"]
            sells = sides["sells"]

            # Simple FIFO matching
            buy_idx = 0
            sell_idx = 0
            while buy_idx < len(buys) and sell_idx < len(sells):
                buy = buys[buy_idx]
                sell = sells[sell_idx]
                matched_qty = min(buy["qty"], sell["qty"])

                if matched_qty > 0:
                    trade_pnl = (sell["price"] - buy["price"]) * matched_qty
                    total_realized_pnl += trade_pnl
                    pnl_per_trade.append(trade_pnl)
                    total_trades += 1

                    if trade_pnl > 0:
                        winning_trades += 1
                    elif trade_pnl < 0:
                        losing_trades += 1

                buy["qty"] -= matched_qty
                sell["qty"] -= matched_qty

                if buy["qty"] <= 0:
                    buy_idx += 1
                if sell["qty"] <= 0:
                    sell_idx += 1

        # Compute stats
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        avg_pnl = (total_realized_pnl / total_trades) if total_trades > 0 else 0
        best_trade = max(pnl_per_trade) if pnl_per_trade else 0
        worst_trade = min(pnl_per_trade) if pnl_per_trade else 0

        # Account data
        acct = client.get_account()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity)
        daily_pnl = equity - last_equity

        stats = {
            "period_days": days,
            "total_orders": len(filled),
            "matched_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 1),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "avg_pnl_per_trade": round(avg_pnl, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "symbols_traded": len(trades_by_symbol),
            "current_equity": equity,
            "daily_pnl": round(daily_pnl, 2),
        }

        if json_mode:
            format_json(stats)
            return

        if RICH_AVAILABLE:
            pnl_str = format_pnl(total_realized_pnl)
            daily_str = format_pnl(daily_pnl)
            content = (
                f"  Period:             Last {days} days\n"
                f"  Total Orders:       {len(filled)}\n"
                f"  Matched Trades:     {total_trades}\n"
                f"  Symbols Traded:     {len(trades_by_symbol)}\n"
                f"\n"
                f"  Win Rate:           {win_rate:.1f}%\n"
                f"  Winning Trades:     {winning_trades}\n"
                f"  Losing Trades:      {losing_trades}\n"
                f"\n"
                f"  Total Realized P&L: {pnl_str}\n"
                f"  Avg P&L/Trade:      ${avg_pnl:,.2f}\n"
                f"  Best Trade:         ${best_trade:,.2f}\n"
                f"  Worst Trade:        ${worst_trade:,.2f}\n"
                f"\n"
                f"  Current Equity:     ${equity:,.2f}\n"
                f"  Daily P&L:          {daily_str}"
            )
            format_panel(content, title="Trading Statistics", style="cyan")
        else:
            click.echo(f"\n  Trading Statistics (Last {days} Days)")
            click.echo("  " + "=" * 40)
            click.echo(f"  Total Orders:       {len(filled)}")
            click.echo(f"  Matched Trades:     {total_trades}")
            click.echo(f"  Win Rate:           {win_rate:.1f}%")
            click.echo(f"  Total Realized P&L: ${total_realized_pnl:,.2f}")
            click.echo(f"  Avg P&L/Trade:      ${avg_pnl:,.2f}")
            click.echo(f"  Best Trade:         ${best_trade:,.2f}")
            click.echo(f"  Worst Trade:        ${worst_trade:,.2f}")
            click.echo(f"  Current Equity:     ${equity:,.2f}")
            click.echo(f"  Daily P&L:          ${daily_pnl:,.2f}")

    except APIError as e:
        echo_error(f"Analytics failed: {e}")


@analytics.command("symbols")
@click.option("--days", type=int, default=30, help="Lookback period in days")
@click.pass_context
def symbol_breakdown(ctx: click.Context, days: int) -> None:
    """Show P&L breakdown by symbol."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        after = datetime.now() - timedelta(days=days)
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=after,
            limit=500,
        )
        closed_orders = client.get_orders(req)
        filled = [o for o in closed_orders if o.status and o.status.value == "filled"]

        if not filled:
            echo_info(f"No filled orders in the last {days} days")
            return

        # Count by symbol
        symbol_stats: dict = {}
        for order in filled:
            sym = order.symbol
            if sym not in symbol_stats:
                symbol_stats[sym] = {"buy_count": 0, "sell_count": 0, "total_volume": 0.0}

            side = order.side.value if order.side else "buy"
            qty = float(order.filled_qty) if order.filled_qty else 0
            price = float(order.filled_avg_price) if order.filled_avg_price else 0

            if side == "buy":
                symbol_stats[sym]["buy_count"] += 1
            else:
                symbol_stats[sym]["sell_count"] += 1

            symbol_stats[sym]["total_volume"] += qty * price

        from alpaca_cli.utils.output import format_table

        rows = []
        for sym, s in sorted(symbol_stats.items()):
            rows.append({
                "symbol": sym,
                "buys": str(s["buy_count"]),
                "sells": str(s["sell_count"]),
                "total_orders": str(s["buy_count"] + s["sell_count"]),
                "volume": f"${s['total_volume']:,.2f}",
            })

        if json_mode:
            format_json(rows)
            return

        format_table(
            rows,
            columns=["symbol", "buys", "sells", "total_orders", "volume"],
            headers=["Symbol", "Buys", "Sells", "Total", "Volume"],
            title=f"Symbol Breakdown (Last {days} Days)",
        )

    except APIError as e:
        echo_error(f"Symbol breakdown failed: {e}")
