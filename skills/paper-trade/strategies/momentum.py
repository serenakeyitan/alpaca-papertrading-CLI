"""Momentum strategy — buy top gainers, sell losers, rebalance periodically."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class MomentumStrategy(Strategy):
    """Momentum: rank a universe of symbols by recent price change, go long
    the top N gainers and exit losers.  Rebalances at a configurable interval.

    Config keys
    -----------
    symbols : list[str]          — universe of tickers to scan
    lookback_minutes : int       — window for measuring momentum (e.g. 60)
    top_n : int                  — how many top gainers to hold (e.g. 3)
    amount_per_position : float  — notional $ per position (e.g. 2000)
    rebalance_minutes : int      — minutes between rebalances (e.g. 30)
    """

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "momentum", config, capital_allocated)
        self.config.setdefault("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
                                            "NVDA", "META", "AMD", "NFLX", "SPY"])
        self.config.setdefault("lookback_minutes", 60)
        self.config.setdefault("top_n", 3)
        self.config.setdefault("amount_per_position", 2000.0)
        self.config.setdefault("rebalance_minutes", 30)
        # Runtime state
        self.config.setdefault("last_rebalance_time", None)
        self.config.setdefault("current_holdings", [])   # symbols currently held
        self.config.setdefault("price_snapshots", {})     # {symbol: [{time, price}]}
        self.config.setdefault("rebalance_count", 0)

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, api):
        """Take initial price snapshots and do first rebalance."""
        self.status = "initializing"

        # Validate we can fetch prices for at least some symbols
        valid = []
        for sym in self.config["symbols"]:
            price = self._get_latest_price(api, sym)
            if price is not None:
                valid.append(sym)
                self._record_price(sym, price)

        if len(valid) < self.config["top_n"]:
            self.status = "error"
            self.error_msg = f"Only {len(valid)} valid symbols, need at least {self.config['top_n']}"
            return

        self.config["symbols"] = valid
        self._rebalance(api)
        self.status = "active"

    def tick(self, api):
        """Record prices, rebalance if enough time has passed."""
        if self.status != "active":
            return

        self.last_tick = datetime.now(timezone.utc).isoformat()
        now = datetime.now(timezone.utc)

        # Always record current prices
        for sym in self.config["symbols"]:
            price = self._get_latest_price(api, sym)
            if price is not None:
                self._record_price(sym, price)

        # Check if it's time to rebalance
        last_rb = self.config.get("last_rebalance_time")
        interval = self.config["rebalance_minutes"]

        should_rebalance = False
        if last_rb is None:
            should_rebalance = True
        else:
            try:
                last_dt = datetime.fromisoformat(last_rb)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (now - last_dt).total_seconds() / 60.0
                if elapsed >= interval:
                    should_rebalance = True
            except (ValueError, TypeError):
                should_rebalance = True

        if should_rebalance:
            self._rebalance(api)

        # Update P&L
        self._update_pnl(api)

    def _record_price(self, symbol: str, price: float):
        """Append a timestamped price to the snapshot history."""
        snapshots = self.config.get("price_snapshots", {})
        if symbol not in snapshots:
            snapshots[symbol] = []

        snapshots[symbol].append({
            "time": datetime.now(timezone.utc).isoformat(),
            "price": price,
        })

        # Keep only last 200 entries per symbol
        snapshots[symbol] = snapshots[symbol][-200:]
        self.config["price_snapshots"] = snapshots

    def _compute_momentum(self) -> list[tuple[str, float]]:
        """Return list of (symbol, pct_change) sorted descending by momentum.

        Uses the oldest available price snapshot within the lookback window
        as the reference price.
        """
        lookback = self.config["lookback_minutes"]
        now = datetime.now(timezone.utc)
        cutoff_seconds = lookback * 60
        results = []

        snapshots = self.config.get("price_snapshots", {})

        for sym, entries in snapshots.items():
            if not entries:
                continue

            current_price = entries[-1]["price"]

            # Find the oldest entry within the lookback window
            ref_price = None
            for entry in entries:
                try:
                    t = datetime.fromisoformat(entry["time"])
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    age = (now - t).total_seconds()
                    if age <= cutoff_seconds:
                        ref_price = entry["price"]
                        break  # oldest within window
                except (ValueError, TypeError):
                    continue

            if ref_price is None:
                # Use oldest available
                ref_price = entries[0]["price"]

            if ref_price > 0:
                pct_change = (current_price - ref_price) / ref_price
                results.append((sym, pct_change))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _rebalance(self, api):
        """Rank symbols by momentum, buy top N, sell the rest."""
        top_n = self.config["top_n"]
        amount = self.config["amount_per_position"]
        rebalance_count = self.config.get("rebalance_count", 0)

        rankings = self._compute_momentum()
        if not rankings:
            return

        # Desired holdings: top N symbols
        desired = set(sym for sym, _ in rankings[:top_n])
        current = set(self.config.get("current_holdings", []))

        # Sell symbols no longer in top N
        to_sell = current - desired
        for sym in to_sell:
            pos_qty = self._get_position_qty(api, sym)
            if pos_qty > 0:
                cid = self.tag_order_id(f"sell{rebalance_count}_{sym}")
                self._submit_order(
                    api,
                    symbol=sym,
                    qty=pos_qty,
                    side="sell",
                    type="market",
                    time_in_force="day",
                    client_order_id=cid,
                )
                self.total_fills += 1

        # Buy symbols newly in top N
        to_buy = desired - current
        for sym in to_buy:
            # Check we don't already hold it from another strategy
            pos_qty = self._get_position_qty(api, sym)
            if pos_qty > 0:
                # Already have a position, skip buying
                continue

            cid = self.tag_order_id(f"buy{rebalance_count}_{sym}")
            self._submit_order(
                api,
                symbol=sym,
                notional=amount,
                side="buy",
                type="market",
                time_in_force="day",
                client_order_id=cid,
            )
            self.total_fills += 1

        now = datetime.now(timezone.utc)
        self.config["current_holdings"] = list(desired)
        self.config["last_rebalance_time"] = now.isoformat()
        self.config["rebalance_count"] = rebalance_count + 1

    def _update_pnl(self, api):
        """Sum unrealized P&L across all held positions."""
        total_unrealized = 0.0
        total_cost = 0.0
        for sym in self.config.get("current_holdings", []):
            try:
                pos = api.get_position(sym)
                total_unrealized += float(pos.unrealized_pl)
                total_cost += abs(float(pos.cost_basis))
            except Exception:
                pass
        self.unrealized_pnl = total_unrealized
        self.capital_used = total_cost

    def stop(self, api):
        """Sell all momentum positions and cancel pending orders."""
        for sym in list(self.config.get("current_holdings", [])):
            pos_qty = self._get_position_qty(api, sym)
            if pos_qty > 0:
                try:
                    api.submit_order(
                        symbol=sym,
                        qty=pos_qty,
                        side="sell",
                        type="market",
                        time_in_force="day",
                    )
                except Exception:
                    pass
        self.config["current_holdings"] = []
        super().stop(api)

    def get_positions(self) -> dict:
        rankings = self._compute_momentum()
        return {
            "current_holdings": self.config.get("current_holdings", []),
            "rebalance_count": self.config.get("rebalance_count", 0),
            "top_n": self.config["top_n"],
            "rankings": [(sym, round(chg * 100, 2)) for sym, chg in rankings[:10]],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MomentumStrategy":
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
