"""Watchlist commands – create, manage, and view Alpaca watchlists."""

from typing import Optional

import click

from alpaca.trading.requests import CreateWatchlistRequest, UpdateWatchlistRequest
from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_trading_client
from alpaca_cli.utils.output import (
    format_table,
    format_item,
    format_json,
    echo_success,
    echo_error,
    echo_info,
)


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def watchlist(ctx: click.Context, json_mode: bool) -> None:
    """Manage Alpaca watchlists."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@watchlist.command("list")
@click.pass_context
def list_watchlists(ctx: click.Context) -> None:
    """List all watchlists."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        wls = client.get_watchlists()

        if json_mode:
            rows = [_wl_to_dict(w) for w in wls]
            format_json(rows)
            return

        if not wls:
            echo_info("No watchlists found. Create one with 'alpaca watchlist create'")
            return

        rows = [_wl_to_dict(w) for w in wls]
        format_table(
            rows,
            columns=["id", "name", "symbol_count", "created_at", "updated_at"],
            headers=["ID", "Name", "Symbols", "Created", "Updated"],
            title="Watchlists",
        )
    except APIError as e:
        echo_error(f"Failed to list watchlists: {e}")


@watchlist.command("get")
@click.argument("watchlist_id")
@click.pass_context
def get_watchlist(ctx: click.Context, watchlist_id: str) -> None:
    """Get watchlist details and symbols."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        wl = client.get_watchlist_by_id(watchlist_id)
        data = _wl_to_dict(wl)

        if json_mode:
            format_json(data)
            return

        format_item(data, [
            ("id", "Watchlist ID"),
            ("name", "Name"),
            ("symbol_count", "Symbol Count"),
            ("created_at", "Created"),
            ("updated_at", "Updated"),
        ])

        if wl.assets:
            click.echo("\n  Symbols:")
            for asset in wl.assets:
                symbol = asset.symbol if hasattr(asset, "symbol") else str(asset)
                click.echo(f"    - {symbol}")
        else:
            echo_info("  No symbols in this watchlist")
    except APIError as e:
        echo_error(f"Failed to get watchlist: {e}")


@watchlist.command("create")
@click.argument("name")
@click.option("--symbols", "-s", multiple=True, help="Symbols to add (repeatable)")
@click.pass_context
def create_watchlist(ctx: click.Context, name: str, symbols: tuple[str, ...]) -> None:
    """Create a new watchlist.

    Example: alpaca watchlist create 'My Tech' -s AAPL -s MSFT -s GOOGL
    """
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        req = CreateWatchlistRequest(
            name=name,
            symbols=[s.upper() for s in symbols] if symbols else [],
        )
        wl = client.create_watchlist(req)

        if json_mode:
            format_json(_wl_to_dict(wl))
        else:
            echo_success(f"Watchlist '{name}' created (ID: {wl.id})")
            if symbols:
                echo_info(f"  Added: {', '.join(s.upper() for s in symbols)}")
    except APIError as e:
        echo_error(f"Failed to create watchlist: {e}")


@watchlist.command("add")
@click.argument("watchlist_id")
@click.argument("symbol")
@click.pass_context
def add_to_watchlist(ctx: click.Context, watchlist_id: str, symbol: str) -> None:
    """Add a symbol to a watchlist.

    Example: alpaca watchlist add <watchlist_id> TSLA
    """
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        wl = client.add_asset_to_watchlist_by_id(watchlist_id, symbol.upper())
        if json_mode:
            format_json({"watchlist_id": str(wl.id), "added": symbol.upper()})
        else:
            echo_success(f"Added {symbol.upper()} to watchlist '{wl.name}'")
    except APIError as e:
        echo_error(f"Failed to add symbol: {e}")


@watchlist.command("remove")
@click.argument("watchlist_id")
@click.argument("symbol")
@click.pass_context
def remove_from_watchlist(ctx: click.Context, watchlist_id: str, symbol: str) -> None:
    """Remove a symbol from a watchlist."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        wl = client.remove_asset_from_watchlist_by_id(watchlist_id, symbol.upper())
        if json_mode:
            format_json({"watchlist_id": str(wl.id), "removed": symbol.upper()})
        else:
            echo_success(f"Removed {symbol.upper()} from watchlist '{wl.name}'")
    except APIError as e:
        echo_error(f"Failed to remove symbol: {e}")


@watchlist.command("update")
@click.argument("watchlist_id")
@click.option("--name", default=None, help="New name")
@click.option("--symbols", "-s", multiple=True, help="Replace all symbols (repeatable)")
@click.pass_context
def update_watchlist(ctx: click.Context, watchlist_id: str, name: Optional[str], symbols: tuple[str, ...]) -> None:
    """Update a watchlist name or replace all symbols."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        params: dict = {}
        if name:
            params["name"] = name
        if symbols:
            params["symbols"] = [s.upper() for s in symbols]

        if not params:
            echo_error("Provide --name or --symbols to update")
            return

        req = UpdateWatchlistRequest(**params)
        wl = client.update_watchlist_by_id(watchlist_id, req)

        if json_mode:
            format_json(_wl_to_dict(wl))
        else:
            echo_success(f"Watchlist '{wl.name}' updated")
    except APIError as e:
        echo_error(f"Failed to update watchlist: {e}")


@watchlist.command("delete")
@click.argument("watchlist_id")
@click.pass_context
def delete_watchlist(ctx: click.Context, watchlist_id: str) -> None:
    """Delete a watchlist."""
    json_mode = ctx.obj.get("json", False)
    client = get_trading_client()

    try:
        client.delete_watchlist_by_id(watchlist_id)
        echo_success(f"Watchlist {watchlist_id} deleted")
    except APIError as e:
        echo_error(f"Failed to delete watchlist: {e}")


# ── Helpers ───────────────────────────────────────────────────────────


def _wl_to_dict(wl) -> dict:
    """Convert Watchlist to display dict."""
    assets = wl.assets or []
    symbols = [a.symbol if hasattr(a, "symbol") else str(a) for a in assets]
    return {
        "id": str(wl.id),
        "name": wl.name,
        "symbol_count": str(len(symbols)),
        "symbols": symbols,
        "created_at": wl.created_at.strftime("%Y-%m-%d %H:%M") if wl.created_at else "",
        "updated_at": wl.updated_at.strftime("%Y-%m-%d %H:%M") if wl.updated_at else "",
    }
