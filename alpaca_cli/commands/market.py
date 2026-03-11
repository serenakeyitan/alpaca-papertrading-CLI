"""Market data commands – quotes, bars, and technical indicators.

Supports both stocks and crypto via Alpaca's data API.
"""

from datetime import datetime, timedelta
from typing import Optional

import click

from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockBarsRequest,
    StockSnapshotRequest,
    CryptoLatestQuoteRequest,
    CryptoBarsRequest,
    CryptoSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_stock_data_client, get_crypto_data_client
from alpaca_cli.utils.output import (
    format_table,
    format_item,
    format_json,
    format_pnl,
    format_pct,
    echo_success,
    echo_error,
    echo_info,
    RICH_AVAILABLE,
    console,
)
from alpaca_cli.utils.indicators import sma, ema, rsi, macd, bollinger_bands


def _is_crypto(symbol: str) -> bool:
    """Heuristic: crypto symbols contain / or are known crypto tickers."""
    crypto_suffixes = {"USD", "USDT", "USDC", "BTC", "ETH"}
    if "/" in symbol:
        return True
    # Check common patterns like BTCUSD, BTC/USD
    upper = symbol.upper().replace("/", "")
    for suffix in crypto_suffixes:
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return True
    return False


def _normalize_crypto(symbol: str) -> str:
    """Normalize crypto symbol to Alpaca format (e.g. BTC/USD)."""
    symbol = symbol.upper().strip()
    if "/" in symbol:
        return symbol
    # Try to split common patterns
    for base in ["BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "UNI", "AAVE", "DOT", "ADA", "XRP", "LTC", "MATIC", "SHIB"]:
        if symbol.startswith(base) and len(symbol) > len(base):
            quote = symbol[len(base):]
            return f"{base}/{quote}"
    # Default: assume /USD
    return f"{symbol}/USD"


def _parse_timeframe(tf: str) -> TimeFrame:
    """Parse timeframe string like '1min', '5min', '1hour', '1day'."""
    tf = tf.lower().strip()
    mapping = {
        "1min": TimeFrame(1, TimeFrameUnit.Minute),
        "5min": TimeFrame(5, TimeFrameUnit.Minute),
        "15min": TimeFrame(15, TimeFrameUnit.Minute),
        "30min": TimeFrame(30, TimeFrameUnit.Minute),
        "1hour": TimeFrame(1, TimeFrameUnit.Hour),
        "4hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1day": TimeFrame(1, TimeFrameUnit.Day),
        "1week": TimeFrame(1, TimeFrameUnit.Week),
        "1month": TimeFrame(1, TimeFrameUnit.Month),
    }
    if tf in mapping:
        return mapping[tf]
    raise click.BadParameter(f"Invalid timeframe '{tf}'. Use: {', '.join(mapping.keys())}")


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def market(ctx: click.Context, json_mode: bool) -> None:
    """Market data: quotes, bars, and technical indicators."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


# ── Quotes ────────────────────────────────────────────────────────────


@market.command("quote")
@click.argument("symbols", nargs=-1, required=True)
@click.pass_context
def get_quote(ctx: click.Context, symbols: tuple[str, ...]) -> None:
    """Get latest quote for one or more symbols.

    Example: alpaca market quote AAPL MSFT BTC/USD
    """
    json_mode = ctx.obj.get("json", False)
    rows = []

    for symbol in symbols:
        try:
            if _is_crypto(symbol):
                sym = _normalize_crypto(symbol)
                client = get_crypto_data_client()
                req = CryptoLatestQuoteRequest(symbol_or_symbols=sym)
                quotes = client.get_crypto_latest_quote(req)
                q = quotes[sym]
                rows.append({
                    "symbol": sym,
                    "bid": f"${float(q.bid_price):,.2f}",
                    "ask": f"${float(q.ask_price):,.2f}",
                    "bid_size": str(q.bid_size),
                    "ask_size": str(q.ask_size),
                    "timestamp": q.timestamp.strftime("%Y-%m-%d %H:%M:%S") if q.timestamp else "",
                })
            else:
                sym = symbol.upper()
                client = get_stock_data_client()
                req = StockLatestQuoteRequest(symbol_or_symbols=sym)
                quotes = client.get_stock_latest_quote(req)
                q = quotes[sym]
                rows.append({
                    "symbol": sym,
                    "bid": f"${float(q.bid_price):,.4f}" if q.bid_price else "-",
                    "ask": f"${float(q.ask_price):,.4f}" if q.ask_price else "-",
                    "bid_size": str(q.bid_size),
                    "ask_size": str(q.ask_size),
                    "timestamp": q.timestamp.strftime("%Y-%m-%d %H:%M:%S") if q.timestamp else "",
                })
        except Exception as e:
            echo_error(f"Failed to get quote for {symbol}: {e}")

    if not rows:
        return

    if json_mode:
        format_json(rows)
        return

    format_table(
        rows,
        columns=["symbol", "bid", "ask", "bid_size", "ask_size", "timestamp"],
        headers=["Symbol", "Bid", "Ask", "Bid Size", "Ask Size", "Time"],
        title="Latest Quotes",
    )


# ── Snapshot ──────────────────────────────────────────────────────────


@market.command("snapshot")
@click.argument("symbol")
@click.pass_context
def get_snapshot(ctx: click.Context, symbol: str) -> None:
    """Get full market snapshot for a symbol (quote + bar + trade)."""
    json_mode = ctx.obj.get("json", False)

    try:
        if _is_crypto(symbol):
            sym = _normalize_crypto(symbol)
            client = get_crypto_data_client()
            req = CryptoSnapshotRequest(symbol_or_symbols=sym)
            snapshots = client.get_crypto_snapshot(req)
            snap = snapshots[sym]
        else:
            sym = symbol.upper()
            client = get_stock_data_client()
            req = StockSnapshotRequest(symbol_or_symbols=sym)
            snapshots = client.get_stock_snapshot(req)
            snap = snapshots[sym]

        bar = snap.daily_bar
        quote = snap.latest_quote
        trade = snap.latest_trade
        prev_bar = snap.previous_daily_bar

        data = {
            "symbol": sym,
            "latest_price": f"${float(trade.price):,.2f}" if trade else "-",
            "latest_size": str(trade.size) if trade else "-",
            "bid": f"${float(quote.bid_price):,.2f}" if quote else "-",
            "ask": f"${float(quote.ask_price):,.2f}" if quote else "-",
            "daily_open": f"${float(bar.open):,.2f}" if bar else "-",
            "daily_high": f"${float(bar.high):,.2f}" if bar else "-",
            "daily_low": f"${float(bar.low):,.2f}" if bar else "-",
            "daily_close": f"${float(bar.close):,.2f}" if bar else "-",
            "daily_volume": f"{int(bar.volume):,}" if bar else "-",
            "prev_close": f"${float(prev_bar.close):,.2f}" if prev_bar else "-",
        }

        if json_mode:
            format_json(data)
            return

        format_item(data, [
            ("symbol", "Symbol"),
            ("latest_price", "Last Price"),
            ("latest_size", "Last Size"),
            ("bid", "Bid"),
            ("ask", "Ask"),
            ("daily_open", "Open"),
            ("daily_high", "High"),
            ("daily_low", "Low"),
            ("daily_close", "Close"),
            ("daily_volume", "Volume"),
            ("prev_close", "Prev Close"),
        ])
    except Exception as e:
        echo_error(f"Snapshot failed for {symbol}: {e}")


# ── Bars / Candles ────────────────────────────────────────────────────


@market.command("bars")
@click.argument("symbol")
@click.option("--timeframe", "-t", default="1day", help="Timeframe: 1min, 5min, 15min, 1hour, 1day, 1week")
@click.option("--days", type=int, default=30, help="Lookback in days")
@click.option("--limit", type=int, default=50, help="Max bars to show")
@click.pass_context
def get_bars(ctx: click.Context, symbol: str, timeframe: str, days: int, limit: int) -> None:
    """Get historical bars (OHLCV candles).

    Example: alpaca market bars AAPL --timeframe 1day --days 30
    """
    json_mode = ctx.obj.get("json", False)
    tf = _parse_timeframe(timeframe)
    start = datetime.now() - timedelta(days=days)

    try:
        if _is_crypto(symbol):
            sym = _normalize_crypto(symbol)
            client = get_crypto_data_client()
            req = CryptoBarsRequest(
                symbol_or_symbols=sym,
                timeframe=tf,
                start=start,
                limit=limit,
            )
            bars_data = client.get_crypto_bars(req)
            bars = bars_data[sym]
        else:
            sym = symbol.upper()
            client = get_stock_data_client()
            req = StockBarsRequest(
                symbol_or_symbols=sym,
                timeframe=tf,
                start=start,
                limit=limit,
            )
            bars_data = client.get_stock_bars(req)
            bars = bars_data[sym]

        rows = []
        for bar in bars:
            rows.append({
                "timestamp": bar.timestamp.strftime("%Y-%m-%d %H:%M"),
                "open": f"${float(bar.open):,.2f}",
                "high": f"${float(bar.high):,.2f}",
                "low": f"${float(bar.low):,.2f}",
                "close": f"${float(bar.close):,.2f}",
                "volume": f"{int(bar.volume):,}",
            })

        if json_mode:
            format_json(rows)
            return

        format_table(
            rows,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
            headers=["Time", "Open", "High", "Low", "Close", "Volume"],
            title=f"{sym} Bars ({timeframe})",
        )
    except Exception as e:
        echo_error(f"Bars failed for {symbol}: {e}")


# ── Technical Indicators ──────────────────────────────────────────────


@market.command("indicators")
@click.argument("symbol")
@click.option("--period", type=int, default=14, help="Indicator period")
@click.option("--days", type=int, default=60, help="Lookback in days")
@click.option(
    "--type", "indicator_type",
    type=click.Choice(["rsi", "sma", "ema", "macd", "bbands", "all"]),
    default="all",
    help="Which indicator to show",
)
@click.pass_context
def get_indicators(ctx: click.Context, symbol: str, period: int, days: int, indicator_type: str) -> None:
    """Calculate technical indicators for a symbol.

    Example: alpaca market indicators AAPL --type rsi --period 14
    """
    json_mode = ctx.obj.get("json", False)
    start = datetime.now() - timedelta(days=days)

    try:
        if _is_crypto(symbol):
            sym = _normalize_crypto(symbol)
            client = get_crypto_data_client()
            req = CryptoBarsRequest(
                symbol_or_symbols=sym,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start,
            )
            bars_data = client.get_crypto_bars(req)
            bars = bars_data[sym]
        else:
            sym = symbol.upper()
            client = get_stock_data_client()
            req = StockBarsRequest(
                symbol_or_symbols=sym,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start,
            )
            bars_data = client.get_stock_bars(req)
            bars = bars_data[sym]

        closes = [float(b.close) for b in bars]

        if not closes:
            echo_error(f"No data for {sym}")
            return

        results: dict = {"symbol": sym, "latest_close": closes[-1]}

        if indicator_type in ("rsi", "all"):
            rsi_vals = rsi(closes, period)
            latest_rsi = rsi_vals[-1]
            results["rsi"] = round(latest_rsi, 2) if latest_rsi is not None else None

        if indicator_type in ("sma", "all"):
            sma_vals = sma(closes, period)
            results["sma"] = round(sma_vals[-1], 2) if sma_vals[-1] is not None else None

        if indicator_type in ("ema", "all"):
            ema_vals = ema(closes, period)
            results["ema"] = round(ema_vals[-1], 2) if ema_vals[-1] is not None else None

        if indicator_type in ("macd", "all"):
            macd_data = macd(closes)
            results["macd_line"] = round(macd_data["macd"][-1], 4) if macd_data["macd"][-1] is not None else None
            results["macd_signal"] = round(macd_data["signal"][-1], 4) if macd_data["signal"][-1] is not None else None
            results["macd_histogram"] = round(macd_data["histogram"][-1], 4) if macd_data["histogram"][-1] is not None else None

        if indicator_type in ("bbands", "all"):
            bb = bollinger_bands(closes, period)
            results["bb_upper"] = round(bb["upper"][-1], 2) if bb["upper"][-1] is not None else None
            results["bb_middle"] = round(bb["middle"][-1], 2) if bb["middle"][-1] is not None else None
            results["bb_lower"] = round(bb["lower"][-1], 2) if bb["lower"][-1] is not None else None

        if json_mode:
            format_json(results)
            return

        # Pretty print
        echo_info(f"Technical Indicators for {sym} (period: {period}, {days}d lookback)")
        click.echo(f"  Latest Close: ${closes[-1]:,.2f}")
        click.echo()

        if "rsi" in results:
            rsi_val = results["rsi"]
            rsi_label = ""
            if rsi_val is not None:
                if rsi_val > 70:
                    rsi_label = " (OVERBOUGHT)"
                elif rsi_val < 30:
                    rsi_label = " (OVERSOLD)"
            click.echo(f"  RSI({period}):    {rsi_val}{rsi_label}")

        if "sma" in results:
            click.echo(f"  SMA({period}):    ${results['sma']:,.2f}" if results["sma"] else f"  SMA({period}):    N/A")

        if "ema" in results:
            click.echo(f"  EMA({period}):    ${results['ema']:,.2f}" if results["ema"] else f"  EMA({period}):    N/A")

        if "macd_line" in results:
            click.echo(f"  MACD:        {results['macd_line']}")
            click.echo(f"  Signal:      {results['macd_signal']}")
            click.echo(f"  Histogram:   {results['macd_histogram']}")

        if "bb_upper" in results:
            click.echo(f"  BB Upper:    ${results['bb_upper']:,.2f}" if results["bb_upper"] else "  BB Upper:    N/A")
            click.echo(f"  BB Middle:   ${results['bb_middle']:,.2f}" if results["bb_middle"] else "  BB Middle:   N/A")
            click.echo(f"  BB Lower:    ${results['bb_lower']:,.2f}" if results["bb_lower"] else "  BB Lower:    N/A")

    except Exception as e:
        echo_error(f"Indicators failed for {symbol}: {e}")
