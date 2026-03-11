"""Order commands – place, list, cancel orders.

Supports all advanced order types:
- Market, Limit, Stop, Stop-Limit
- Trailing Stop (trail_price or trail_percent)
- Bracket (OTO: entry + take-profit + stop-loss)
"""

from typing import Optional
from datetime import datetime

import click

from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_trading_client
from alpaca_cli.utils.output import (
    format_table,
    format_item,
    format_json,
    echo_success,
    echo_error,
    echo_warn,
    echo_info,
)


def _parse_side(side: str) -> OrderSide:
    """Parse order side string."""
    s = side.lower().strip()
    if s in ("buy", "b", "long"):
        return OrderSide.BUY
    elif s in ("sell", "s", "short"):
        return OrderSide.SELL
    raise click.BadParameter(f"Invalid side '{side}'. Use 'buy' or 'sell'.")


def _parse_tif(tif: str) -> TimeInForce:
    """Parse time-in-force string."""
    mapping = {
        "day": TimeInForce.DAY,
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "fok": TimeInForce.FOK,
        "opg": TimeInForce.OPG,
        "cls": TimeInForce.CLS,
    }
    t = tif.lower().strip()
    if t in mapping:
        return mapping[t]
    raise click.BadParameter(f"Invalid time_in_force '{tif}'. Use: {', '.join(mapping.keys())}")


def _warn_large_order(symbol: str, qty: float, side: str) -> None:
    """Warn on large orders (basic risk management)."""
    if qty >= 100:
        echo_warn(f"Large order: {side.upper()} {qty} units of {symbol}")
    if qty >= 1000:
        echo_warn(f"Very large order! {qty} units. Proceed with caution.")


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def orders(ctx: click.Context, json_mode: bool) -> None:
    """Place, list, and cancel orders."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


# ── Place Orders ──────────────────────────────────────────────────────


@orders.command("market")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.option("--side", "-s", default="buy", help="buy or sell")
@click.option("--tif", default="gtc", help="Time in force: day, gtc, ioc, fok")
@click.option("--notional", type=float, default=None, help="Dollar amount instead of qty")
@click.pass_context
def market_order(ctx: click.Context, symbol: str, qty: float, side: str, tif: str, notional: Optional[float]) -> None:
    """Place a market order. Example: alpaca orders market AAPL 10 --side buy"""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    order_side = _parse_side(side)
    time_in_force = _parse_tif(tif)
    _warn_large_order(symbol, qty, side)

    params: dict = {
        "symbol": symbol.upper(),
        "side": order_side,
        "time_in_force": time_in_force,
    }
    if notional:
        params["notional"] = notional
    else:
        params["qty"] = qty

    try:
        req = MarketOrderRequest(**params)
        order = client.submit_order(req)
        _print_order(order, json_mode)
        echo_success(f"Market {side.upper()} order placed for {symbol.upper()}")
    except APIError as e:
        echo_error(f"Order failed: {e}")


@orders.command("limit")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.argument("limit_price", type=float)
@click.option("--side", "-s", default="buy", help="buy or sell")
@click.option("--tif", default="gtc", help="Time in force: day, gtc, ioc, fok")
@click.pass_context
def limit_order(ctx: click.Context, symbol: str, qty: float, limit_price: float, side: str, tif: str) -> None:
    """Place a limit order. Example: alpaca orders limit AAPL 10 150.00 --side buy"""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    _warn_large_order(symbol, qty, side)

    try:
        req = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=_parse_side(side),
            time_in_force=_parse_tif(tif),
            limit_price=limit_price,
        )
        order = client.submit_order(req)
        _print_order(order, json_mode)
        echo_success(f"Limit {side.upper()} order placed for {symbol.upper()} @ ${limit_price:,.2f}")
    except APIError as e:
        echo_error(f"Order failed: {e}")


@orders.command("stop")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.argument("stop_price", type=float)
@click.option("--side", "-s", default="sell", help="buy or sell")
@click.option("--tif", default="gtc", help="Time in force")
@click.pass_context
def stop_order(ctx: click.Context, symbol: str, qty: float, stop_price: float, side: str, tif: str) -> None:
    """Place a stop order. Example: alpaca orders stop AAPL 10 145.00 --side sell"""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    _warn_large_order(symbol, qty, side)

    try:
        req = StopOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=_parse_side(side),
            time_in_force=_parse_tif(tif),
            stop_price=stop_price,
        )
        order = client.submit_order(req)
        _print_order(order, json_mode)
        echo_success(f"Stop {side.upper()} order placed for {symbol.upper()} @ ${stop_price:,.2f}")
    except APIError as e:
        echo_error(f"Order failed: {e}")


@orders.command("stop-limit")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.argument("stop_price", type=float)
@click.argument("limit_price", type=float)
@click.option("--side", "-s", default="sell", help="buy or sell")
@click.option("--tif", default="gtc", help="Time in force")
@click.pass_context
def stop_limit_order(
    ctx: click.Context, symbol: str, qty: float, stop_price: float, limit_price: float, side: str, tif: str
) -> None:
    """Place a stop-limit order. Example: alpaca orders stop-limit AAPL 10 145.00 144.50"""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    _warn_large_order(symbol, qty, side)

    try:
        req = StopLimitOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=_parse_side(side),
            time_in_force=_parse_tif(tif),
            stop_price=stop_price,
            limit_price=limit_price,
        )
        order = client.submit_order(req)
        _print_order(order, json_mode)
        echo_success(f"Stop-Limit {side.upper()} order placed for {symbol.upper()}")
    except APIError as e:
        echo_error(f"Order failed: {e}")


@orders.command("trailing-stop")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.option("--side", "-s", default="sell", help="buy or sell")
@click.option("--trail-price", type=float, default=None, help="Trail by dollar amount")
@click.option("--trail-percent", type=float, default=None, help="Trail by percentage")
@click.option("--tif", default="gtc", help="Time in force")
@click.pass_context
def trailing_stop_order(
    ctx: click.Context,
    symbol: str,
    qty: float,
    side: str,
    trail_price: Optional[float],
    trail_percent: Optional[float],
    tif: str,
) -> None:
    """Place a trailing stop order. Example: alpaca orders trailing-stop AAPL 10 --trail-percent 5"""
    json_mode = ctx.obj.get("json", False)

    if not trail_price and not trail_percent:
        echo_error("Provide --trail-price or --trail-percent")
        return

    client = get_trading_client()
    _warn_large_order(symbol, qty, side)

    try:
        params: dict = {
            "symbol": symbol.upper(),
            "qty": qty,
            "side": _parse_side(side),
            "time_in_force": _parse_tif(tif),
        }
        if trail_price:
            params["trail_price"] = trail_price
        else:
            params["trail_percent"] = trail_percent

        req = TrailingStopOrderRequest(**params)
        order = client.submit_order(req)
        _print_order(order, json_mode)
        trail_desc = f"${trail_price}" if trail_price else f"{trail_percent}%"
        echo_success(f"Trailing Stop {side.upper()} placed for {symbol.upper()} (trail: {trail_desc})")
    except APIError as e:
        echo_error(f"Order failed: {e}")


@orders.command("bracket")
@click.argument("symbol")
@click.argument("qty", type=float)
@click.option("--side", "-s", default="buy", help="buy or sell")
@click.option("--type", "order_type", type=click.Choice(["market", "limit"]), default="market", help="Entry order type")
@click.option("--limit-price", type=float, default=None, help="Entry limit price (for limit entry)")
@click.option("--take-profit", type=float, required=True, help="Take-profit limit price")
@click.option("--stop-loss", type=float, required=True, help="Stop-loss price")
@click.option("--stop-limit", type=float, default=None, help="Stop-loss limit price (optional)")
@click.option("--tif", default="gtc", help="Time in force")
@click.pass_context
def bracket_order(
    ctx: click.Context,
    symbol: str,
    qty: float,
    side: str,
    order_type: str,
    limit_price: Optional[float],
    take_profit: float,
    stop_loss: float,
    stop_limit: Optional[float],
    tif: str,
) -> None:
    """Place a bracket order (entry + take-profit + stop-loss).

    Example: alpaca orders bracket AAPL 10 --take-profit 160 --stop-loss 140
    """
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    _warn_large_order(symbol, qty, side)

    try:
        tp_params = {"limit_price": take_profit}
        sl_params: dict = {"stop_price": stop_loss}
        if stop_limit:
            sl_params["limit_price"] = stop_limit

        if order_type == "limit":
            if not limit_price:
                echo_error("--limit-price required for limit entry bracket order")
                return
            req = LimitOrderRequest(
                symbol=symbol.upper(),
                qty=qty,
                side=_parse_side(side),
                time_in_force=_parse_tif(tif),
                limit_price=limit_price,
                order_class=OrderClass.BRACKET,
                take_profit=tp_params,
                stop_loss=sl_params,
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol.upper(),
                qty=qty,
                side=_parse_side(side),
                time_in_force=_parse_tif(tif),
                order_class=OrderClass.BRACKET,
                take_profit=tp_params,
                stop_loss=sl_params,
            )

        order = client.submit_order(req)
        _print_order(order, json_mode)
        echo_success(
            f"Bracket {side.upper()} order placed for {symbol.upper()} "
            f"(TP: ${take_profit:,.2f}, SL: ${stop_loss:,.2f})"
        )
    except APIError as e:
        echo_error(f"Order failed: {e}")


# ── List / Cancel ─────────────────────────────────────────────────────


@orders.command("list")
@click.option("--status", type=click.Choice(["open", "closed", "all"]), default="open", help="Filter by status")
@click.option("--limit", "max_results", type=int, default=50, help="Max results")
@click.option("--symbol", default=None, help="Filter by symbol")
@click.pass_context
def list_orders(ctx: click.Context, status: str, max_results: int, symbol: Optional[str]) -> None:
    """List orders."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    from alpaca.trading.requests import GetOrdersRequest

    status_map = {
        "open": QueryOrderStatus.OPEN,
        "closed": QueryOrderStatus.CLOSED,
        "all": QueryOrderStatus.ALL,
    }

    params: dict = {
        "status": status_map[status],
        "limit": max_results,
    }
    if symbol:
        params["symbols"] = [symbol.upper()]

    request = GetOrdersRequest(**params)
    order_list = client.get_orders(request)

    if json_mode:
        rows = [_order_to_dict(o) for o in order_list]
        format_json(rows)
        return

    if not order_list:
        echo_info(f"No {status} orders found")
        return

    rows = [_order_to_dict(o) for o in order_list]
    format_table(
        rows,
        columns=["symbol", "side", "type", "qty", "filled_qty", "limit_price", "stop_price", "status", "submitted_at"],
        headers=["Symbol", "Side", "Type", "Qty", "Filled", "Limit", "Stop", "Status", "Submitted"],
        title=f"{status.upper()} Orders",
    )


@orders.command("get")
@click.argument("order_id")
@click.pass_context
def get_order(ctx: click.Context, order_id: str) -> None:
    """Get details of a specific order."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        order = client.get_order_by_id(order_id)
        _print_order(order, json_mode)
    except APIError as e:
        echo_error(f"Could not fetch order: {e}")


@orders.command("cancel")
@click.argument("order_id")
@click.pass_context
def cancel_order(ctx: click.Context, order_id: str) -> None:
    """Cancel an open order by ID."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        client.cancel_order_by_id(order_id)
        echo_success(f"Order {order_id} cancelled")
    except APIError as e:
        echo_error(f"Cancel failed: {e}")


@orders.command("cancel-all")
@click.pass_context
def cancel_all_orders(ctx: click.Context) -> None:
    """Cancel all open orders."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        cancelled = client.cancel_orders()
        if json_mode:
            format_json({"cancelled": len(cancelled)})
        else:
            echo_success(f"Cancelled {len(cancelled)} orders")
    except APIError as e:
        echo_error(f"Cancel all failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────


def _order_to_dict(order) -> dict:
    """Convert an Order object to a display-friendly dict."""
    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "side": order.side.value if order.side else "",
        "type": order.type.value if order.type else "",
        "qty": str(order.qty or ""),
        "filled_qty": str(order.filled_qty or "0"),
        "limit_price": f"${float(order.limit_price):,.2f}" if order.limit_price else "-",
        "stop_price": f"${float(order.stop_price):,.2f}" if order.stop_price else "-",
        "status": order.status.value if order.status else "",
        "submitted_at": order.submitted_at.strftime("%Y-%m-%d %H:%M") if order.submitted_at else "",
        "filled_at": order.filled_at.strftime("%Y-%m-%d %H:%M") if order.filled_at else "-",
        "filled_avg_price": f"${float(order.filled_avg_price):,.2f}" if order.filled_avg_price else "-",
        "order_class": order.order_class.value if order.order_class else "simple",
        "time_in_force": order.time_in_force.value if order.time_in_force else "",
    }


def _print_order(order, json_mode: bool) -> None:
    """Print order details."""
    data = _order_to_dict(order)
    if json_mode:
        format_json(data)
        return

    format_item(data, [
        ("id", "Order ID"),
        ("symbol", "Symbol"),
        ("side", "Side"),
        ("type", "Type"),
        ("qty", "Quantity"),
        ("filled_qty", "Filled"),
        ("limit_price", "Limit Price"),
        ("stop_price", "Stop Price"),
        ("status", "Status"),
        ("order_class", "Order Class"),
        ("time_in_force", "Time in Force"),
        ("submitted_at", "Submitted"),
        ("filled_at", "Filled At"),
        ("filled_avg_price", "Avg Fill Price"),
    ])
