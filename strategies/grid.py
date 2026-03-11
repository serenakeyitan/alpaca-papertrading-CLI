"""Grid trading strategy — places buy/sell limit orders across a price grid."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class GridStrategy(Strategy):
    """Grid trading: place limit buy/sell orders at evenly-spaced price levels
    around a center price.  When a grid order fills, the opposite order is
    placed so the strategy keeps "buying low, selling high" within the range.

    Config keys
    -----------
    symbol : str          — ticker to trade (e.g. "NVDA")
    grid_pct : float      — total grid width as % of center price (e.g. 6)
    num_grids : int        — number of grid levels (buy + sell combined)
    qty_per_grid : int     — shares per grid order
    """

    # -- per-instance state beyond base class --------------------------------
    # center_price, grid_levels, open_order_ids are kept in self.config for
    # persistence via to_dict / from_dict.

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "grid", config, capital_allocated)
        # Ensure required keys have defaults
        self.config.setdefault("symbol", "NVDA")
        self.config.setdefault("grid_pct", 6)
        self.config.setdefault("num_grids", 10)
        self.config.setdefault("qty_per_grid", 2)
        # Runtime state stored inside config for serialization
        self.config.setdefault("center_price", None)
        self.config.setdefault("open_order_ids", [])
        self.config.setdefault("grid_levels", [])

    # -- helpers -------------------------------------------------------------

    def _compute_grid_levels(self, center: float):
        """Return list of dicts with price / side / grid_idx."""
        grid_pct = self.config["grid_pct"]
        num_grids = self.config["num_grids"]
        half = num_grids // 2
        step = (center * grid_pct / 100) / num_grids
        levels = []
        for i in range(-half, half + 1):
            if i == 0:
                continue
            price = round(center + i * step, 2)
            side = "buy" if i < 0 else "sell"
            levels.append({"price": price, "side": side, "grid_idx": i})
        return levels

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, api):
        """Set center price, buy base position for sell-side grids."""
        self.status = "initializing"
        symbol = self.config["symbol"]
        qty_per_grid = self.config["qty_per_grid"]
        half_grids = self.config["num_grids"] // 2

        price = self._get_latest_price(api, symbol)
        if price is None:
            self.status = "error"
            self.error_msg = f"Cannot get price for {symbol}"
            return

        self.config["center_price"] = price

        # Buy base position so sell grids can be placed
        target_qty = qty_per_grid * half_grids
        current_qty = self._get_position_qty(api, symbol)
        need = target_qty - current_qty

        if need > 0:
            cid = self.tag_order_id("base")
            self._submit_order(
                api,
                symbol=symbol,
                qty=need,
                side="buy",
                type="market",
                time_in_force="day",
                client_order_id=cid,
            )

        self.status = "active"

    def tick(self, api):
        """Check fills, place missing grid orders, re-center if needed."""
        if self.status != "active":
            return

        symbol = self.config["symbol"]
        grid_pct = self.config["grid_pct"]
        num_grids = self.config["num_grids"]
        qty = self.config["qty_per_grid"]
        center = self.config["center_price"]

        self.last_tick = datetime.now(timezone.utc).isoformat()

        current_price = self._get_latest_price(api, symbol)
        if current_price is None:
            return

        # Re-center if price drifted too far
        if center is not None:
            drift_pct = abs(current_price - center) / center * 100
            if drift_pct > grid_pct * 0.8:
                # Cancel all existing grid orders and re-center
                self._cancel_all_grid_orders(api)
                center = current_price
                self.config["center_price"] = center
        else:
            center = current_price
            self.config["center_price"] = center

        # Detect fills since last tick
        prev_ids = set(self.config.get("open_order_ids", []))
        current_open = self.get_orders(api, status="open")
        current_open_ids = {o.id for o in current_open}
        gone_ids = prev_ids - current_open_ids

        step = (center * grid_pct / 100) / num_grids

        for oid in gone_ids:
            try:
                filled_order = api.get_order(oid)
                if filled_order.status == "filled" and filled_order.filled_avg_price:
                    self.total_fills += 1
                    fill_qty = float(filled_order.filled_qty)
                    self.realized_pnl += round(step * fill_qty, 2)
            except Exception:
                pass

        # Compute desired levels
        levels = self._compute_grid_levels(center)

        # Existing open order prices
        existing_prices = set()
        for o in current_open:
            if o.limit_price:
                existing_prices.add(round(float(o.limit_price), 2))

        pos_qty = self._get_position_qty(api, symbol)

        # Place missing grid orders
        new_order_ids = [o.id for o in current_open]
        for level in levels:
            price = level["price"]
            side = level["side"]
            grid_idx = level["grid_idx"]

            if price in existing_prices:
                continue
            if side == "sell" and pos_qty < qty:
                continue
            if side == "buy" and price >= current_price:
                continue
            if side == "sell" and price <= current_price:
                continue

            cid = self.tag_order_id(f"g{grid_idx}")
            order = self._submit_order(
                api,
                symbol=symbol,
                qty=qty,
                side=side,
                type="limit",
                limit_price=price,
                time_in_force="day",
                client_order_id=cid,
            )
            if order:
                new_order_ids.append(order.id)

        self.config["open_order_ids"] = new_order_ids

        # Update capital_used (rough estimate based on position value)
        self.capital_used = pos_qty * current_price
        # Update unrealized P&L from position
        try:
            pos = api.get_position(symbol)
            self.unrealized_pnl = float(pos.unrealized_pl)
        except Exception:
            self.unrealized_pnl = 0.0

    def stop(self, api):
        """Cancel all grid orders and stop."""
        self._cancel_all_grid_orders(api)
        self.config["open_order_ids"] = []
        super().stop(api)

    def _cancel_all_grid_orders(self, api):
        """Cancel all open orders belonging to this strategy."""
        try:
            open_orders = api.list_orders(status="open", limit=500)
            for o in open_orders:
                if self._owns_order(o):
                    try:
                        api.cancel_order(o.id)
                    except Exception:
                        pass
        except Exception:
            pass

    def get_positions(self) -> dict:
        symbol = self.config["symbol"]
        return {
            "symbol": symbol,
            "center_price": self.config.get("center_price"),
            "grid_pct": self.config["grid_pct"],
            "num_grids": self.config["num_grids"],
            "qty_per_grid": self.config["qty_per_grid"],
            "open_order_count": len(self.config.get("open_order_ids", [])),
        }

    def to_dict(self) -> dict:
        d = super().to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "GridStrategy":
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
