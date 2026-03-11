"""Alpaca client wrapper for paper trading.

Provides centralized access to all Alpaca API clients:
- TradingClient: orders, positions, account, watchlists
- StockHistoricalDataClient: stock bars, quotes, trades
- CryptoHistoricalDataClient: crypto bars, quotes, trades
"""

import click

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient

from .config import get_api_key, get_secret_key, validate_keys


def _ensure_keys() -> tuple[str, str]:
    """Validate and return API keys or raise ClickException."""
    valid, msg = validate_keys()
    if not valid:
        raise click.ClickException(msg)
    return get_api_key(), get_secret_key()


def get_trading_client() -> TradingClient:
    """Create a TradingClient for paper trading.

    Returns:
        Configured TradingClient (paper=True, always).
    """
    api_key, secret_key = _ensure_keys()
    return TradingClient(api_key, secret_key, paper=True)


def get_stock_data_client() -> StockHistoricalDataClient:
    """Create a StockHistoricalDataClient.

    Returns:
        Configured StockHistoricalDataClient.
    """
    api_key, secret_key = _ensure_keys()
    return StockHistoricalDataClient(api_key, secret_key)


def get_crypto_data_client() -> CryptoHistoricalDataClient:
    """Create a CryptoHistoricalDataClient.

    Returns:
        Configured CryptoHistoricalDataClient.
    """
    api_key, secret_key = _ensure_keys()
    return CryptoHistoricalDataClient(api_key, secret_key)
