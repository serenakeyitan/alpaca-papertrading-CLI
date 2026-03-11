"""Base strategy class for the multi-strategy paper trading platform."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class Strategy:
    """Abstract base class for all trading strategies.

    Subclasses must implement:
        - initialize(api)  — one-time setup (buy base position, etc.)
        - tick(api)        — called every cycle; core strategy logic
        - stop(api)        — graceful shutdown, cancel orders
    """

    # -- class-level defaults (overridden by subclass or instance) ----------

    name: str = ""
    type: str = ""               # "grid", "dca", "momentum", "mean_reversion"
    status: str = "pending"      # pending | initializing | active | paused | stopped | error
    capital_allocated: float = 0.0
    capital_used: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fills: int = 0
    orders: list = None          # tagged client_order_ids
    created_at: str = ""
    last_tick: str = ""
    error_msg: str = ""
    config: dict = None          # strategy-specific config

    def __init__(self, name: str, strategy_type: str, config: dict,
                 capital_allocated: float = 0.0):
        self.name = name
        self.type = strategy_type
        self.config = dict(config) if config else {}
        self.capital_allocated = capital_allocated
        self.capital_used = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.total_fills = 0
        self.orders = []
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.last_tick = ""
        self.error_msg = ""

    # -- Order-ID tagging ---------------------------------------------------

    def tag_order_id(self, base_id: str) -> str:
        """Return a client_order_id tagged with strategy info.

        Format: ``{type}_{name}_{base_id}`` truncated to 48 chars.
        """
        raw = f"{self.type}_{self.name}_{base_id}"
        return raw[:48]

    def _owns_order(self, order) -> bool:
        """Return True if *order* belongs to this strategy."""
        cid = getattr(order, "client_order_id", "") or ""
        prefix = f"{self.type}_{self.name}_"
        return cid.startswith(prefix)

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, api):
        """Called once when the strategy transitions to *active*.

        Subclasses should place initial orders / buy base positions here.
        """
        raise NotImplementedError

    def tick(self, api):
        """Called every cycle while strategy is *active*.

        This is where the core strategy logic lives.
        """
        raise NotImplementedError

    def stop(self, api):
        """Gracefully stop the strategy — cancel all open orders."""
        self.status = "stopped"
        # Cancel all orders that belong to this strategy
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

    # -- Query helpers ------------------------------------------------------

    def get_orders(self, api, status="all") -> list:
        """Return orders belonging to this strategy."""
        try:
            all_orders = api.list_orders(status=status, limit=500)
            return [o for o in all_orders if self._owns_order(o)]
        except Exception:
            return []

    def get_positions(self) -> dict:
        """Return strategy-local position tracking.

        Subclasses should override this to return their tracked positions.
        Default returns an empty dict.
        """
        return {}

    # -- Serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize strategy state to a JSON-safe dict."""
        return {
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "capital_allocated": self.capital_allocated,
            "capital_used": self.capital_used,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_fills": self.total_fills,
            "orders": list(self.orders),
            "created_at": self.created_at,
            "last_tick": self.last_tick,
            "error_msg": self.error_msg,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Strategy":
        """Deserialize a strategy from a dict.

        This returns a *base* Strategy instance.  The StrategyManager is
        responsible for instantiating the correct subclass via the registry.
        """
        obj = cls.__new__(cls)
        obj.name = data.get("name", "")
        obj.type = data.get("type", "")
        obj.status = data.get("status", "pending")
        obj.capital_allocated = data.get("capital_allocated", 0.0)
        obj.capital_used = data.get("capital_used", 0.0)
        obj.realized_pnl = data.get("realized_pnl", 0.0)
        obj.unrealized_pnl = data.get("unrealized_pnl", 0.0)
        obj.total_fills = data.get("total_fills", 0)
        obj.orders = list(data.get("orders", []))
        obj.created_at = data.get("created_at", "")
        obj.last_tick = data.get("last_tick", "")
        obj.error_msg = data.get("error_msg", "")
        obj.config = dict(data.get("config", {}))
        return obj

    # -- Helpers for subclasses ---------------------------------------------

    def _get_latest_price(self, api, symbol: str) -> float | None:
        """Fetch the latest trade price for *symbol*."""
        try:
            trade = api.get_latest_trade(symbol)
            return float(trade.price)
        except Exception:
            return None

    def _get_position_qty(self, api, symbol: str) -> float:
        """Return current position qty for *symbol*, 0 if none."""
        try:
            pos = api.get_position(symbol)
            return float(pos.qty)
        except Exception:
            return 0.0

    def _submit_order(self, api, **kwargs) -> object | None:
        """Submit an order and track its client_order_id."""
        try:
            order = api.submit_order(**kwargs)
            cid = kwargs.get("client_order_id", "")
            if cid and cid not in self.orders:
                self.orders.append(cid)
            return order
        except Exception:
            return None

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r} status={self.status!r}>"
