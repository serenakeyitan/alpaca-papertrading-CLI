#!/usr/bin/env python3
"""Cron tick runner — runs tick_all on all strategies."""

import json
import sys
from pathlib import Path
from datetime import datetime

VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    sys.path.insert(0, str(p))

SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import alpaca_trade_api as tradeapi
from strategy_manager import StrategyManager

CONFIG_PATH = Path(__file__).parent / "config.json"

def get_api():
    cfg = json.loads(CONFIG_PATH.read_text())
    return tradeapi.REST(
        cfg["api_key"], cfg["secret_key"],
        base_url="https://paper-api.alpaca.markets", api_version="v2"
    )

def main():
    api = get_api()

    # Check market open
    try:
        clock = api.get_clock()
        if not clock.is_open:
            print(f"[{datetime.now()}] Market closed. Skipping.")
            return
    except Exception as e:
        print(f"[{datetime.now()}] Clock error: {e}")
        return

    sm = StrategyManager()
    active = sum(1 for s in sm.strategies.values() if s.status in ("active", "pending"))
    print(f"[{datetime.now()}] Tick: {active} active strategies")
    sm.tick_all(api)
    print(f"[{datetime.now()}] Tick complete")

if __name__ == "__main__":
    main()
