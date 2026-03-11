"""Account commands – view account info, buying power, equity, and portfolio summary."""

from typing import Optional

import click

from alpaca_cli.utils.client import get_trading_client
from alpaca_cli.utils.output import (
    format_item,
    format_json,
    format_panel,
    format_pnl,
    format_pct,
    echo_info,
    echo_warn,
    RICH_AVAILABLE,
    console,
)


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def account(ctx: click.Context, json_mode: bool) -> None:
    """View account information, buying power, and portfolio summary."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@account.command("info")
@click.pass_context
def account_info(ctx: click.Context) -> None:
    """Show full account details."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    acct = client.get_account()

    data = {
        "account_number": acct.account_number,
        "status": acct.status.value if acct.status else "",
        "currency": acct.currency,
        "cash": f"${float(acct.cash):,.2f}",
        "portfolio_value": f"${float(acct.portfolio_value):,.2f}",
        "equity": f"${float(acct.equity):,.2f}",
        "buying_power": f"${float(acct.buying_power):,.2f}",
        "long_market_value": f"${float(acct.long_market_value):,.2f}",
        "short_market_value": f"${float(acct.short_market_value):,.2f}",
        "initial_margin": f"${float(acct.initial_margin):,.2f}",
        "maintenance_margin": f"${float(acct.maintenance_margin):,.2f}",
        "last_equity": f"${float(acct.last_equity):,.2f}",
        "daytrade_count": str(acct.daytrade_count),
        "pattern_day_trader": str(acct.pattern_day_trader),
        "trading_blocked": str(acct.trading_blocked),
        "account_blocked": str(acct.account_blocked),
    }

    if json_mode:
        format_json(data)
        return

    format_item(data, [
        ("account_number", "Account"),
        ("status", "Status"),
        ("currency", "Currency"),
        ("cash", "Cash"),
        ("portfolio_value", "Portfolio Value"),
        ("equity", "Equity"),
        ("buying_power", "Buying Power"),
        ("long_market_value", "Long Value"),
        ("short_market_value", "Short Value"),
        ("initial_margin", "Initial Margin"),
        ("maintenance_margin", "Maint. Margin"),
        ("last_equity", "Last Equity"),
        ("daytrade_count", "Day Trades"),
        ("pattern_day_trader", "PDT"),
        ("trading_blocked", "Trading Blocked"),
        ("account_blocked", "Account Blocked"),
    ])


@account.command("summary")
@click.pass_context
def account_summary(ctx: click.Context) -> None:
    """Show quick portfolio summary with P&L."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    acct = client.get_account()

    equity = float(acct.equity)
    last_equity = float(acct.last_equity)
    cash = float(acct.cash)
    buying_power = float(acct.buying_power)
    portfolio_value = float(acct.portfolio_value)

    daily_pnl = equity - last_equity
    daily_pct = (daily_pnl / last_equity * 100) if last_equity else 0

    data = {
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
        "portfolio_value": portfolio_value,
        "daily_pnl": daily_pnl,
        "daily_pct": daily_pct,
    }

    if json_mode:
        format_json(data)
        return

    if RICH_AVAILABLE:
        pnl_str = format_pnl(daily_pnl)
        pct_str = format_pct(daily_pct)
        content = (
            f"  Equity:          ${equity:>12,.2f}\n"
            f"  Cash:            ${cash:>12,.2f}\n"
            f"  Buying Power:    ${buying_power:>12,.2f}\n"
            f"  Portfolio Value: ${portfolio_value:>12,.2f}\n"
            f"  Daily P&L:       {pnl_str} ({pct_str})"
        )
        console.print()
        format_panel(content, title="Paper Trading Account", style="cyan")
    else:
        click.echo(f"\n  Equity:          ${equity:>12,.2f}")
        click.echo(f"  Cash:            ${cash:>12,.2f}")
        click.echo(f"  Buying Power:    ${buying_power:>12,.2f}")
        click.echo(f"  Portfolio Value: ${portfolio_value:>12,.2f}")
        sign = "+" if daily_pnl >= 0 else ""
        click.echo(f"  Daily P&L:       ${sign}{daily_pnl:,.2f} ({sign}{daily_pct:.2f}%)")

    # Warn if buying power is low
    if buying_power < equity * 0.05:
        echo_warn("Buying power is below 5% of equity")


@account.command("buying-power")
@click.pass_context
def buying_power(ctx: click.Context) -> None:
    """Show current buying power."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()
    acct = client.get_account()

    bp = float(acct.buying_power)
    if json_mode:
        format_json({"buying_power": bp})
    else:
        click.echo(f"${bp:,.2f}")
