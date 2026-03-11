"""Mean Reversion strategy — buy below rolling average, sell above."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class MeanReversionStrategy(Strategy):
    """Mean Reversion: track a rolling average of recent prices.  When the
    current price drops below ``avg - threshold_pct``, buy.  When it rises
    above ``avg + threshold_pct``, sell.

    Config keys
    -----------
    symbol : str           — ticker to trade (e.g. "AAPL")
    window : int           — number of price samples for the rolling average
    threshold_pct : float  — % deviation from mean to trigger buy/sell (e.g. 1.5)
    qty : int              — shares per trade
    """

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "mean_reversion", config, capital_allocated)
        self.config.setdefault("symbol", "AAPL")
        self.config.setdefault("window", 20)
        self.config.setdefault("threshold_pct", 1.5)
        self.config.setdefault("qty", 5)
        # Runtime state
        self.config.setdefault("price_samples", [])    # list of floats
        self.config.setdefault("position_side", None)   # None, "long"
        self.config.setdefault("entry_price", None)
        self.config.setdefault("trade_count", 0)
        self.config.setdefault("last_signal", None)     # "buy", "sell", None

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, api):
        """Validate symbol and start collecting price samples."""
        self.status = "initializing"
        symbol = self.config["symbol"]

        price = self._get_latest_price(api, symbol)
        if price is None:
            self.status = "error"
            self.error_msg = f"Cannot get price for {symbol}"
            return

        # Seed with initial price
        self.config["price_samples"] = [price]
        self.status = "active"

    def tick(self, api):
        """Collect price sample, check for mean-reversion signals, trade."""
        if self.status != "active":
            return

        self.last_tick = datetime.now(timezone.utc).isoformat()
        symbol = self.config["symbol"]
        window = self.config["window"]
        threshold_pct = self.config["threshold_pct"]
        qty = self.config["qty"]

        current_price = self._get_latest_price(api, symbol)
        if current_price is None:
            return

        # Record price sample
        samples = self.config["price_samples"]
        samples.append(current_price)
        # Keep only the last ``window * 2`` samples (extra for smoothing)
        max_keep = window * 2
        if len(samples) > max_keep:
            samples = samples[-max_keep:]
        self.config["price_samples"] = samples

        # Need at least ``window`` samples to compute a meaningful average
        if len(samples) < window:
            return

        # Compute rolling average over the last ``window`` samples
        recent = samples[-window:]
        rolling_avg = sum(recent) / len(recent)

        # Thresholds
        buy_threshold = rolling_avg * (1 - threshold_pct / 100)
        sell_threshold = rolling_avg * (1 + threshold_pct / 100)

        pos_qty = self._get_position_qty(api, symbol)
        trade_count = self.config.get("trade_count", 0)
        position_side = self.config.get("position_side")

        # BUY signal: price below lower threshold and not already long
        if current_price <= buy_threshold and pos_qty == 0:
            cid = self.tag_order_id(f"buy{trade_count}")
            order = self._submit_order(
                api,
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day",
                client_order_id=cid,
            )
            if order:
                self.total_fills += 1
                self.config["trade_count"] = trade_count + 1
                self.config["position_side"] = "long"
                self.config["entry_price"] = current_price
                self.config["last_signal"] = "buy"
                self.capital_used = current_price * qty

        # SELL signal: price above upper threshold and we are long
        elif current_price >= sell_threshold and pos_qty > 0:
            sell_qty = min(qty, pos_qty)
            cid = self.tag_order_id(f"sell{trade_count}")
            order = self._submit_order(
                api,
                symbol=symbol,
                qty=sell_qty,
                side="sell",
                type="market",
                time_in_force="day",
                client_order_id=cid,
            )
            if order:
                self.total_fills += 1
                self.config["trade_count"] = trade_count + 1

                # Calculate realized P&L for this round-trip
                entry = self.config.get("entry_price")
                if entry:
                    pnl = (current_price - entry) * sell_qty
                    self.realized_pnl += round(pnl, 2)

                # Check if we've fully exited
                remaining = pos_qty - sell_qty
                if remaining <= 0:
                    self.config["position_side"] = None
                    self.config["entry_price"] = None
                    self.capital_used = 0.0

                self.config["last_signal"] = "sell"

        # Update unrealized P&L
        if pos_qty > 0:
            try:
                pos = api.get_position(symbol)
                self.unrealized_pnl = float(pos.unrealized_pl)
                self.capital_used = abs(float(pos.cost_basis))
            except Exception:
                pass
        else:
            self.unrealized_pnl = 0.0

    def stop(self, api):
        """Sell any remaining position and stop."""
        symbol = self.config["symbol"]
        pos_qty = self._get_position_qty(api, symbol)
        if pos_qty > 0:
            try:
                api.submit_order(
                    symbol=symbol,
                    qty=pos_qty,
                    side="sell",
                    type="market",
                    time_in_force="day",
                )
            except Exception:
                pass
        self.config["position_side"] = None
        self.config["entry_price"] = None
        super().stop(api)

    def get_positions(self) -> dict:
        samples = self.config.get("price_samples", [])
        window = self.config["window"]
        rolling_avg = None
        if len(samples) >= window:
            recent = samples[-window:]
            rolling_avg = round(sum(recent) / len(recent), 2)

        return {
            "symbol": self.config["symbol"],
            "position_side": self.config.get("position_side"),
            "entry_price": self.config.get("entry_price"),
            "rolling_avg": rolling_avg,
            "samples_collected": len(samples),
            "window": window,
            "threshold_pct": self.config["threshold_pct"],
            "qty": self.config["qty"],
            "trade_count": self.config.get("trade_count", 0),
            "last_signal": self.config.get("last_signal"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MeanReversionStrategy":
        obj = cls(
            name=data["name"],
            config=data.get("config", {}),
            capital_allocated=data.get("capital_allocated", 0.0),
        )
        obj.status = data.get("status", "pending")
        obj.realized_pnl = data.get("realized_pnl", 0.0)
        obj.unrealized_pnl = data.get("unrealized_pnl", 0.0)
        obj.total_fills = data.get("total_fills", 0)
        obj.orders = list(data.get("orders", []))
        obj.created_at = data.get("created_at", "")
        obj.last_tick = data.get("last_tick", "")
        obj.error_msg = data.get("error_msg", "")
        obj.capital_used = data.get("capital_used", 0.0)
        return obj
