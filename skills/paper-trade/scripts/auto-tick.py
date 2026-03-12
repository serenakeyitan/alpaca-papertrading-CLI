#!/usr/bin/env python3
"""Auto-tick — run one tick cycle on all active strategies, then exit.

Designed to be called by cron every 30 seconds (or any interval).
Exits cleanly so cron can re-invoke it on the next schedule.

Usage:
    /opt/homebrew/lib/node_modules/openclaw/skills/paper-trade/.venv/bin/python \
        /opt/homebrew/lib/node_modules/openclaw/skills/paper-trade/scripts/auto-tick.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── venv + skill dir bootstrap ──────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_SITE = SKILL_DIR / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import alpaca_trade_api as tradeapi
from strategy_manager import StrategyManager

LOG_PATH = SKILL_DIR / "auto_tick.log"
CONFIG_PATH = SKILL_DIR / "config.json"
HOME_CONFIG = Path.home() / ".alpaca-cli" / "config.json"


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")
    # Keep log from growing unbounded (truncate to last 500 lines)
    try:
        lines = LOG_PATH.read_text().splitlines()
        if len(lines) > 500:
            LOG_PATH.write_text("\n".join(lines[-500:]) + "\n")
    except OSError:
        pass


def _load_config():
    for p in (CONFIG_PATH, HOME_CONFIG):
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError("No Alpaca config found")


def main():
    cfg = _load_config()
    api = tradeapi.REST(
        cfg["api_key"], cfg["secret_key"],
        base_url="https://paper-api.alpaca.markets", api_version="v2",
    )

    mgr = StrategyManager()
    strategies = mgr.list_strategies()
    active = [s for s in strategies if s["status"] in ("active", "pending")]

    if not active:
        _log("No active strategies — skipping tick")
        return

    _log(f"Ticking {len(active)} active strategies: {', '.join(s['name'] for s in active)}")
    mgr.tick_all(api)
    _log("Tick complete")


if __name__ == "__main__":
    main()
