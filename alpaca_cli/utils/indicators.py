"""Technical indicators for market analysis.

Lightweight implementations that work with lists of float values.
No heavy dependencies (no TA-Lib required).
"""

from typing import Optional


def sma(prices: list[float], period: int = 20) -> list[Optional[float]]:
    """Simple Moving Average.

    Args:
        prices: List of closing prices.
        period: Lookback period.

    Returns:
        List of SMA values (None for insufficient data).
    """
    result: list[Optional[float]] = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1 : i + 1]
        result[i] = sum(window) / period
    return result


def ema(prices: list[float], period: int = 20) -> list[Optional[float]]:
    """Exponential Moving Average.

    Args:
        prices: List of closing prices.
        period: Lookback period.

    Returns:
        List of EMA values (None for insufficient data).
    """
    result: list[Optional[float]] = [None] * len(prices)
    if len(prices) < period:
        return result

    # Seed with SMA
    seed = sum(prices[:period]) / period
    result[period - 1] = seed

    multiplier = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(prices)):
        val = (prices[i] - prev) * multiplier + prev
        result[i] = val
        prev = val

    return result


def rsi(prices: list[float], period: int = 14) -> list[Optional[float]]:
    """Relative Strength Index.

    Args:
        prices: List of closing prices.
        period: RSI lookback period.

    Returns:
        List of RSI values (0-100, None for insufficient data).
    """
    result: list[Optional[float]] = [None] * len(prices)
    if len(prices) < period + 1:
        return result

    # Calculate price changes
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Initial average gain/loss
    gains = [max(c, 0) for c in changes[:period]]
    losses = [abs(min(c, 0)) for c in changes[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    # Smoothed RSI
    for i in range(period, len(changes)):
        change = changes[i]
        gain = max(change, 0)
        loss = abs(min(change, 0))

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))

    return result


def macd(
    prices: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, list[Optional[float]]]:
    """Moving Average Convergence Divergence.

    Args:
        prices: List of closing prices.
        fast_period: Fast EMA period.
        slow_period: Slow EMA period.
        signal_period: Signal line EMA period.

    Returns:
        Dict with 'macd', 'signal', and 'histogram' lists.
    """
    fast_ema = ema(prices, fast_period)
    slow_ema = ema(prices, slow_period)

    n = len(prices)
    macd_line: list[Optional[float]] = [None] * n

    for i in range(n):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]

    # Signal line: EMA of MACD values
    macd_values = [v for v in macd_line if v is not None]
    if len(macd_values) >= signal_period:
        signal_ema = ema(macd_values, signal_period)
        # Map signal back to full-length list
        signal_line: list[Optional[float]] = [None] * n
        idx = 0
        for i in range(n):
            if macd_line[i] is not None:
                signal_line[i] = signal_ema[idx]
                idx += 1
    else:
        signal_line = [None] * n

    # Histogram
    histogram: list[Optional[float]] = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def bollinger_bands(
    prices: list[float], period: int = 20, num_std: float = 2.0
) -> dict[str, list[Optional[float]]]:
    """Bollinger Bands.

    Args:
        prices: List of closing prices.
        period: SMA period.
        num_std: Number of standard deviations.

    Returns:
        Dict with 'upper', 'middle', 'lower' band lists.
    """
    middle = sma(prices, period)
    n = len(prices)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n

    for i in range(period - 1, n):
        if middle[i] is not None:
            window = prices[i - period + 1 : i + 1]
            mean = middle[i]
            variance = sum((p - mean) ** 2 for p in window) / period
            std = variance**0.5
            upper[i] = mean + num_std * std
            lower[i] = mean - num_std * std

    return {"upper": upper, "middle": middle, "lower": lower}


def vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[Optional[float]]:
    """Volume Weighted Average Price.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        closes: List of close prices.
        volumes: List of volumes.

    Returns:
        List of VWAP values.
    """
    n = len(closes)
    result: list[Optional[float]] = [None] * n

    cumulative_tp_vol = 0.0
    cumulative_vol = 0.0

    for i in range(n):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3
        cumulative_tp_vol += typical_price * volumes[i]
        cumulative_vol += volumes[i]
        if cumulative_vol > 0:
            result[i] = cumulative_tp_vol / cumulative_vol

    return result
