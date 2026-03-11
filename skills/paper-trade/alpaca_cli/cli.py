"""Main CLI entry point for alpaca-cli.

Usage:
    alpaca [OPTIONS] COMMAND [ARGS]...

Commands:
    account     View account information, buying power, and portfolio summary
    orders      Place, list, and cancel orders
    positions   View and manage open positions
    market      Market data: quotes, bars, and technical indicators
    watchlist   Manage Alpaca watchlists
    analytics   Performance analytics and trading statistics
    strategy    Run and manage trading strategies
    configure   Configure API keys and CLI settings
"""

import click

from alpaca_cli import __version__
from alpaca_cli.commands.account import account
from alpaca_cli.commands.orders import orders
from alpaca_cli.commands.positions import positions
from alpaca_cli.commands.market import market
from alpaca_cli.commands.watchlist import watchlist
from alpaca_cli.commands.analytics import analytics
from alpaca_cli.commands.strategy import strategy
from alpaca_cli.commands.configure import configure


@click.group()
@click.version_option(version=__version__, prog_name="alpaca")
def cli() -> None:
    """Alpaca Paper Trading CLI – trade stocks & crypto from the terminal.

    \b
    Quick start:
      1. alpaca configure init        (set API keys)
      2. alpaca account summary       (check balance)
      3. alpaca orders market AAPL 1  (buy 1 share of AAPL)
      4. alpaca positions list        (see positions)
    """


# Register all command groups
cli.add_command(account)
cli.add_command(orders)
cli.add_command(positions)
cli.add_command(market)
cli.add_command(watchlist)
cli.add_command(analytics)
cli.add_command(strategy)
cli.add_command(configure)


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
