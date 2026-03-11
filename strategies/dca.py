"""Dollar Cost Averaging strategy — periodic market buys to accumulate."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class DCAStrategy(Strategy):
    """Dollar Cost Averaging: buy a fixed dollar amount of a symbol at
    regular intervals.  Simple accumulation strategy.

    Config keys
    -----------
    symbol : str               — ticker to accumulate (e.g. "AAPL")
    amount_per_buy : float     — notional $ per purchase (e.g. 500)
    interval_minutes : int     — minutes between buys (e.g. 30)
    """

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "dca", config, capital_allocated)
        self.config.setdefault("symbol", "AAPL")
        self.config.setdefault("amount_per_buy", 500.0)
        self.config.setdefault("interval_minutes", 30)
        # Runtime state
        self.config.setdefault("last_buy_time", None)
        self.config.setdefault("total_invested", 0.0)
        self.config.setdefault("total_shares", 0.0)
        self.config.setdefault("buy_count", 0)
        self.config.setdefault("buy_history", [])  # [{time, price, qty, amount}]

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, api):
        """Validate symbol and do first buy immediately."""
        self.status = "initializing"
        symbol = self.config["symbol"]

        price = self._get_latest_price(api, symbol)
        if price is None:
            self.status = "error"
            self.error_msg = f"Cannot get price for {symbol}"
            return

        # Place initial buy
        self._do_buy(api)
        self.status = "active"

    def tick(self, api):
        """If enough time has passed since the last buy, place a market buy."""
        if self.status != "active":
            return

        self.last_tick = datetime.now(timezone.utc).isoformat()
        symbol = self.config["symbol"]
        interval = self.config["interval_minutes"]
        last_buy = self.config.get("last_buy_time")

        now = datetime.now(timezone.utc)

        # Check if it's time to buy
        if last_buy is not None:
            try:
                last_dt = datetime.fromisoformat(last_buy)
                # Ensure timezone-aware comparison
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (now - last_dt).total_seconds() / 60.0
                if elapsed < interval:
                    # Update unrealized P&L only
                    self._update_pnl(api)
                    return
            except (ValueError, TypeError):
                pass  # bad timestamp, proceed with buy

        # Check we haven't exceeded allocated capital
        total_invested = self.config.get("total_invested", 0.0)
        amount = self.config["amount_per_buy"]
        if self.capital_allocated > 0 and total_invested + amount > self.capital_allocated:
            # No more capital to deploy
            self._update_pnl(api)
            return

        self._do_buy(api)
        self._update_pnl(api)

    def _do_buy(self, api):
        """Place a notional market buy."""
        symbol = self.config["symbol"]
        amount = self.config["amount_per_buy"]
        buy_count = self.config.get("buy_count", 0)

        cid = self.tag_order_id(f"b{buy_count}")
        order = self._submit_order(
            api,
            symbol=symbol,
            notional=amount,
            side="buy",
            type="market",
            time_in_force="day",
            client_order_id=cid,
        )

        now = datetime.now(timezone.utc)
        self.config["last_buy_time"] = now.isoformat()
        self.config["buy_count"] = buy_count + 1
        self.total_fills += 1

        # Record the buy
        price = self._get_latest_price(api, symbol)
        if price and price > 0:
            shares_bought = amount / price
            self.config["total_invested"] = self.config.get("total_invested", 0.0) + amount
            self.config["total_shares"] = self.config.get("total_shares", 0.0) + shares_bought
            self.capital_used = self.config["total_invested"]

            history = self.config.get("buy_history", [])
            history.append({
                "time": now.isoformat(),
                "price": round(price, 2),
                "qty": round(shares_bought, 4),
                "amount": amount,
            })
            # Keep last 100 entries
            self.config["buy_history"] = history[-100:]

    def _update_pnl(self, api):
        """Update unrealized P&L from current position."""
        symbol = self.config["symbol"]
        try:
            pos = api.get_position(symbol)
            self.unrealized_pnl = float(pos.unrealized_pl)
            self.capital_used = abs(float(pos.cost_basis))
        except Exception:
            pass

    def stop(self, api):
        """Stop DCA — no open orders to cancel (all market), just stop."""
        super().stop(api)

    def get_positions(self) -> dict:
        return {
            "symbol": self.config["symbol"],
            "total_invested": self.config.get("total_invested", 0.0),
            "total_shares": self.config.get("total_shares", 0.0),
            "buy_count": self.config.get("buy_count", 0),
            "avg_price": (
                self.config["total_invested"] / self.config["total_shares"]
                if self.config.get("total_shares", 0) > 0
                else 0
            ),
            "amount_per_buy": self.config["amount_per_buy"],
            "interval_minutes": self.config["interval_minutes"],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DCAStrategy":
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
