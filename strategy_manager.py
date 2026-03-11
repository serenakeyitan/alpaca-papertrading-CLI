"""Strategy Manager — orchestrates multiple trading strategies."""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Add parent so strategy imports work
SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from strategies.grid import GridStrategy
from strategies.dca import DCAStrategy
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy

STATE_PATH = Path(__file__).parent / "strategies_state.json"
LOG_PATH = Path(__file__).parent / "strategy_manager.log"

# Registry: type string -> class
STRATEGY_REGISTRY = {
    "grid": GridStrategy,
    "dca": DCAStrategy,
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
}


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


class StrategyManager:
    """Manages the lifecycle of multiple trading strategies.

    Strategies are persisted to ``strategies_state.json`` so they survive
    restarts.  The manager provides methods to add, remove, tick, and
    query strategies.
    """

    def __init__(self):
        self.strategies: dict[str, object] = {}  # name -> Strategy instance
        self._load()

    # -- Persistence --------------------------------------------------------

    def _load(self):
        """Load all strategies from the state file."""
        if not STATE_PATH.exists():
            return

        try:
            data = json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return

        for entry in data.get("strategies", []):
            stype = entry.get("type", "")
            cls = STRATEGY_REGISTRY.get(stype)
            if cls is None:
                _log(f"Unknown strategy type '{stype}', skipping")
                continue
            try:
                strategy = cls.from_dict(entry)
                self.strategies[strategy.name] = strategy
            except Exception as e:
                _log(f"Failed to load strategy '{entry.get('name', '?')}': {e}")

    def save(self):
        """Persist all strategies to the state file."""
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": [s.to_dict() for s in self.strategies.values()],
        }
        STATE_PATH.write_text(json.dumps(data, indent=2))

    # -- Strategy CRUD ------------------------------------------------------

    def add_strategy(self, strategy_type: str, name: str, config: dict,
                     capital_allocated: float = 0.0) -> object:
        """Create, register, and return a new strategy.

        Raises ValueError if the name already exists or the type is unknown.
        """
        if name in self.strategies:
            raise ValueError(f"Strategy '{name}' already exists")

        cls = STRATEGY_REGISTRY.get(strategy_type)
        if cls is None:
            raise ValueError(
                f"Unknown strategy type '{strategy_type}'. "
                f"Available: {', '.join(STRATEGY_REGISTRY.keys())}"
            )

        strategy = cls(name=name, config=config, capital_allocated=capital_allocated)
        self.strategies[name] = strategy
        self.save()
        _log(f"Added strategy: {name} (type={strategy_type})")
        return strategy

    def remove_strategy(self, name: str, api=None):
        """Stop and remove a strategy by name.

        If *api* is provided, the strategy's ``stop()`` method is called
        first to cancel orders / close positions.
        """
        if name not in self.strategies:
            raise ValueError(f"Strategy '{name}' not found")

        strategy = self.strategies[name]
        if api and strategy.status in ("active", "paused", "initializing"):
            try:
                strategy.stop(api)
            except Exception as e:
                _log(f"Error stopping '{name}': {e}")

        del self.strategies[name]
        self.save()
        _log(f"Removed strategy: {name}")

    def get_strategy(self, name: str) -> object:
        """Return a single strategy by name, or None."""
        return self.strategies.get(name)

    def list_strategies(self) -> list[dict]:
        """Return a summary list of all strategies."""
        result = []
        for s in self.strategies.values():
            result.append({
                "name": s.name,
                "type": s.type,
                "status": s.status,
                "capital_allocated": s.capital_allocated,
                "capital_used": s.capital_used,
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "total_pnl": s.realized_pnl + s.unrealized_pnl,
                "total_fills": s.total_fills,
                "last_tick": s.last_tick,
                "created_at": s.created_at,
                "error_msg": s.error_msg,
            })
        return result

    # -- Tick ---------------------------------------------------------------

    def tick_all(self, api):
        """Run one tick cycle on every active strategy.

        Strategies in "pending" status are initialized first.  Strategies
        in "paused", "stopped", or "error" are skipped.
        """
        for name, strategy in list(self.strategies.items()):
            try:
                if strategy.status == "pending":
                    _log(f"Initializing strategy: {name}")
                    strategy.initialize(api)
                    if strategy.status == "error":
                        _log(f"Strategy {name} failed to initialize: {strategy.error_msg}")
                    else:
                        _log(f"Strategy {name} initialized -> {strategy.status}")

                elif strategy.status == "active":
                    strategy.tick(api)

                # paused, stopped, error -> skip
            except Exception as e:
                strategy.status = "error"
                strategy.error_msg = str(e)
                _log(f"Strategy {name} error during tick: {e}")

        self.save()

    # -- Aggregated summary -------------------------------------------------

    def get_summary(self) -> dict:
        """Return an aggregated summary of all strategies for the dashboard."""
        total_allocated = 0.0
        total_used = 0.0
        total_realized = 0.0
        total_unrealized = 0.0
        total_fills = 0
        active_count = 0
        error_count = 0
        strategies = []

        for s in self.strategies.values():
            total_allocated += s.capital_allocated
            total_used += s.capital_used
            total_realized += s.realized_pnl
            total_unrealized += s.unrealized_pnl
            total_fills += s.total_fills
            if s.status == "active":
                active_count += 1
            if s.status == "error":
                error_count += 1

            strategies.append({
                "name": s.name,
                "type": s.type,
                "status": s.status,
                "capital_used": s.capital_used,
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "total_pnl": s.realized_pnl + s.unrealized_pnl,
                "total_fills": s.total_fills,
                "last_tick": s.last_tick,
                "error_msg": s.error_msg,
                "positions": s.get_positions(),
            })

        return {
            "total_strategies": len(self.strategies),
            "active_count": active_count,
            "error_count": error_count,
            "total_allocated": total_allocated,
            "total_used": total_used,
            "total_realized_pnl": total_realized,
            "total_unrealized_pnl": total_unrealized,
            "total_pnl": total_realized + total_unrealized,
            "total_fills": total_fills,
            "strategies": strategies,
        }

    # -- Convenience --------------------------------------------------------

    def pause_strategy(self, name: str):
        """Pause a running strategy (it won't tick until resumed)."""
        s = self.strategies.get(name)
        if s is None:
            raise ValueError(f"Strategy '{name}' not found")
        if s.status == "active":
            s.status = "paused"
            self.save()
            _log(f"Paused strategy: {name}")
        else:
            raise ValueError(f"Strategy '{name}' is not active (status={s.status})")

    def resume_strategy(self, name: str):
        """Resume a paused strategy."""
        s = self.strategies.get(name)
        if s is None:
            raise ValueError(f"Strategy '{name}' not found")
        if s.status == "paused":
            s.status = "active"
            self.save()
            _log(f"Resumed strategy: {name}")
        else:
            raise ValueError(f"Strategy '{name}' is not paused (status={s.status})")
