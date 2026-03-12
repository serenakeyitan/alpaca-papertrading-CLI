"""Momentum Scalper — measures price velocity, buys on acceleration, sells when move slows."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class MomentumScalperStrategy(Strategy):
    """Watches price tick-by-tick, measures how fast price is moving.
    Buys when momentum accelerates upward, sells when the move slows.

    Config keys
    -----------
    symbol : str              — e.g. "BTC/USD"
    lookback : int            — samples to measure momentum over (default 5)
    buy_threshold : float     — min % momentum to trigger buy (default 0.03)
    slow_threshold : float    — sell when momentum drops below this % (default 0.01)
    trade_amount : float      — notional $ per trade (default 50)
    max_trades : int          — max round-trips (default 20)
    duration_minutes : int    — auto-pause after N minutes (0 = no limit)
    """

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "momentum_scalper", config, capital_allocated)
        self.config.setdefault("symbol", "BTC/USD")
        self.config.setdefault("lookback", 5)
        self.config.setdefault("buy_threshold", 0.03)   # 0.03% to trigger buy
        self.config.setdefault("slow_threshold", 0.01)   # sell when momentum < 0.01%
        self.config.setdefault("trade_amount", 50)
        self.config.setdefault("max_trades", 20)
        # Runtime state
        self.config.setdefault("price_samples", [])
        self.config.setdefault("momentum_history", [])    # last N momentum readings
        self.config.setdefault("in_position", False)
        self.config.setdefault("entry_price", None)
        self.config.setdefault("trade_count", 0)
        self.config.setdefault("trades", [])               # log of trades

    def initialize(self, api):
        self.status = "initializing"
        symbol = self.config["symbol"]

        price = self._get_latest_price(api, symbol)
        if price is None:
            self.status = "error"
            self.error_msg = f"Cannot get price for {symbol}"
            return

        self.config["price_samples"] = [price]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "active"

    def tick(self, api):
        if self.status != "active":
            return

        self.last_tick = datetime.now(timezone.utc).isoformat()
        symbol = self.config["symbol"]
        lookback = self.config["lookback"]
        buy_thresh = self.config["buy_threshold"]
        slow_thresh = self.config["slow_threshold"]
        trade_amount = self.config["trade_amount"]
        max_trades = self.config["max_trades"]

        price = self._get_latest_price(api, symbol)
        if price is None:
            return

        # Record price
        samples = self.config["price_samples"]
        samples.append(price)
        if len(samples) > lookback * 4:
            samples = samples[-(lookback * 4):]
        self.config["price_samples"] = samples

        # Need enough samples to measure momentum
        if len(samples) < lookback + 1:
            return

        # Compute momentum: % change over lookback period
        old_price = samples[-(lookback + 1)]
        momentum = ((price - old_price) / old_price) * 100  # as percentage

        # Track momentum history
        mom_hist = self.config["momentum_history"]
        mom_hist.append(round(momentum, 4))
        if len(mom_hist) > 20:
            mom_hist = mom_hist[-20:]
        self.config["momentum_history"] = mom_hist

        in_position = self.config.get("in_position", False)
        trade_count = self.config.get("trade_count", 0)

        if trade_count >= max_trades:
            return

        tif = "gtc" if "/" in symbol else "day"
        pos_symbol = symbol.replace("/", "")

        if not in_position:
            # BUY when momentum is strong and positive
            if momentum >= buy_thresh:
                ts = int(datetime.now(timezone.utc).timestamp())
                cid = self.tag_order_id(f"b{trade_count}_{ts}")
                order = self._submit_order(
                    api,
                    symbol=symbol,
                    notional=trade_amount,
                    side="buy",
                    type="market",
                    time_in_force=tif,
                    client_order_id=cid,
                )
                if order:
                    self.total_fills += 1
                    now = datetime.now(timezone.utc).isoformat()
                    self.config["in_position"] = True
                    self.config["entry_price"] = price
                    self.config["trades"].append({
                        "time": now, "side": "buy", "price": price,
                        "momentum": round(momentum, 4),
                    })

        else:
            # SELL when momentum slows down or reverses
            if momentum <= slow_thresh:
                # Sell entire position
                pos_qty = self._get_position_qty(api, pos_symbol)
                if pos_qty > 0:
                    ts = int(datetime.now(timezone.utc).timestamp())
                    cid = self.tag_order_id(f"s{trade_count}_{ts}")
                    order = self._submit_order(
                        api,
                        symbol=symbol,
                        qty=pos_qty,
                        side="sell",
                        type="market",
                        time_in_force=tif,
                        client_order_id=cid,
                    )
                    if order:
                        self.total_fills += 1
                        entry = self.config.get("entry_price", price)
                        pnl = (price - entry) / entry * trade_amount
                        self.realized_pnl += round(pnl, 2)
                        now = datetime.now(timezone.utc).isoformat()
                        self.config["in_position"] = False
                        self.config["entry_price"] = None
                        self.config["trade_count"] = trade_count + 1
                        self.config["trades"].append({
                            "time": now, "side": "sell", "price": price,
                            "momentum": round(momentum, 4), "pnl": round(pnl, 2),
                        })

        # Update unrealized PnL
        if self.config.get("in_position"):
            try:
                pos = api.get_position(pos_symbol)
                self.unrealized_pnl = float(pos.unrealized_pl)
                self.capital_used = abs(float(pos.cost_basis))
            except Exception:
                pass
        else:
            self.unrealized_pnl = 0.0
            self.capital_used = 0.0

    def stop(self, api):
        symbol = self.config["symbol"]
        pos_symbol = symbol.replace("/", "")
        pos_qty = self._get_position_qty(api, pos_symbol)
        if pos_qty > 0:
            tif = "gtc" if "/" in symbol else "day"
            try:
                api.submit_order(
                    symbol=symbol, qty=pos_qty, side="sell",
                    type="market", time_in_force=tif,
                )
            except Exception:
                pass
        self.config["in_position"] = False
        super().stop(api)

    def get_positions(self) -> dict:
        samples = self.config.get("price_samples", [])
        lookback = self.config["lookback"]
        momentum = None
        if len(samples) > lookback:
            old = samples[-(lookback + 1)]
            cur = samples[-1]
            momentum = round(((cur - old) / old) * 100, 4)

        return {
            "symbol": self.config["symbol"],
            "in_position": self.config.get("in_position", False),
            "entry_price": self.config.get("entry_price"),
            "momentum": momentum,
            "momentum_history": self.config.get("momentum_history", [])[-5:],
            "trade_count": self.config.get("trade_count", 0),
            "samples": len(samples),
            "recent_trades": self.config.get("trades", [])[-5:],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MomentumScalperStrategy":
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
        obj.started_at = data.get("started_at", "")
        obj.duration_minutes = data.get("duration_minutes", 0)
        obj.last_tick = data.get("last_tick", "")
        obj.error_msg = data.get("error_msg", "")
        obj.capital_used = data.get("capital_used", 0.0)
        return obj
