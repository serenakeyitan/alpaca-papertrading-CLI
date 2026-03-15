#!/usr/bin/env python3
"""Alpaca Paper Trading — Live Web Dashboard.

A Bloomberg-style browser dashboard that mirrors the terminal TUI,
with live auto-refreshing data from Alpaca.

Run directly:
    python web_dashboard.py [--port 8888]

Or via the helper script:
    bash scripts/start-web.sh
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── venv bootstrap ──────────────────────────────────────────
VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import requests as http_requests
import alpaca_trade_api as tradeapi
from flask import Flask, jsonify, Response

# ── Config ──────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
TRADE_LOG_PATH = Path(__file__).parent / "trade_log.txt"
HOME_CONFIG = Path.home() / ".alpaca-cli" / "config.json"

DEFAULT_WATCHLIST = ["NVDA", "AAPL", "SPY", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "QQQ"]

app = Flask(__name__)


def _load_config():
    # Environment variables first (for cloud deployment: Render, Railway, etc.)
    api_key = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    if api_key and secret_key:
        return {"api_key": api_key, "secret_key": secret_key}
    # Fall back to config files (local development)
    for p in (CONFIG_PATH, HOME_CONFIG):
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError("No Alpaca config found. Set ALPACA_API_KEY + ALPACA_SECRET_KEY env vars, or run: alpaca configure init")


def _get_api():
    cfg = _load_config()
    return tradeapi.REST(
        cfg["api_key"], cfg["secret_key"],
        base_url="https://paper-api.alpaca.markets", api_version="v2",
    )


def _load_watchlist():
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text())
    return list(DEFAULT_WATCHLIST)


def _get_strategy_manager():
    try:
        from strategy_manager import StrategyManager
        return StrategyManager()
    except Exception:
        return None


# ── Background data cache ──────────────────────────────────
# A single background thread fetches ALL data from Alpaca every 5 seconds.
# API endpoints serve instantly from cache — no Alpaca calls on request.
# 10 browser tabs = same 1 set of API calls per cycle, not 10x.

import threading
import time as _time
import re as _re
import sqlite3

_DB_PATH = SKILL_DIR / "dashboard_cache.db"


class _DataCache:
    """Thread-safe cache populated by a tiered background worker.

    Refresh rates:
    - Fast  (every 2s):  account balance/equity + watchlist prices (most important)
    - Normal (every ~4s): positions, orders, recent fills
    - Slow  (every ~10s): strategies (local or derived from Alpaca orders)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "account": {"error": "loading..."},
            "positions": [],
            "watchlist": [],
            "orders": [],
            "strategies": [],
            "log": [],
        }
        self._seen_order_ids = set()
        self._trade_log = []
        self._history_loaded = False
        self._init_db()

    # ── SQLite for trade log persistence ───────────────────

    def _init_db(self):
        """Create trade log table if it doesn't exist."""
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    msg TEXT NOT NULL,
                    style TEXT NOT NULL DEFAULT 'dim',
                    order_id TEXT,
                    created_at REAL DEFAULT (strftime('%s','now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_log_order_id
                ON trade_log(order_id)
            """)
            conn.commit()

    def _db_load_log(self):
        """Load trade log from SQLite on startup."""
        with sqlite3.connect(str(_DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT ts, msg, style, order_id FROM trade_log ORDER BY id DESC LIMIT 200"
            ).fetchall()
        entries = [{"ts": r[0], "msg": r[1], "style": r[2]} for r in reversed(rows)]
        seen = {r[3] for r in rows if r[3]}
        return entries, seen

    def _db_insert_log(self, ts, msg, style, order_id=None):
        """Insert a trade log entry into SQLite."""
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                conn.execute(
                    "INSERT INTO trade_log (ts, msg, style, order_id) VALUES (?, ?, ?, ?)",
                    (ts, msg, style, order_id),
                )
                conn.commit()
        except Exception:
            pass

    # ── Cache read (instant, thread-safe) ──────────────────

    def get(self, key):
        with self._lock:
            return self._data.get(key)

    # ── Background fetch functions ─────────────────────────

    def _fetch_account(self, api):
        acct = api.get_account()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity)
        pnl = equity - last_equity
        pnl_pct = (pnl / last_equity * 100) if last_equity else 0
        clock = api.get_clock()

        strat_pnl = strat_deployed = strat_allocated = strat_active = strat_total = 0
        sm = _get_strategy_manager()
        if sm:
            try:
                summary = sm.get_summary()
                strat_pnl = summary.get("total_pnl", 0)
                strat_deployed = summary.get("total_used", 0)
                strat_allocated = summary.get("total_allocated", 0)
                strat_active = summary.get("active_count", 0)
                strat_total = summary.get("total_strategies", 0)
            except Exception:
                pass

        return {
            "equity": equity,
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "market_open": clock.is_open,
            "status": acct.status,
            "strat_pnl": strat_pnl,
            "strat_deployed": strat_deployed,
            "strat_allocated": strat_allocated,
            "strat_active": strat_active,
            "strat_total": strat_total,
        }

    def _fetch_positions(self, api):
        positions = api.list_positions()
        result = []
        for p in positions:
            result.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "entry": float(p.avg_entry_price),
                "current": float(p.current_price),
                "market_value": float(p.market_value),
                "pnl": float(p.unrealized_pl),
                "pnl_pct": float(p.unrealized_plpc) * 100,
                "change_today": float(p.change_today) * 100 if p.change_today else 0,
                "asset_class": p.asset_class,
            })
        result.sort(key=lambda x: abs(x["market_value"]), reverse=True)
        return result

    def _fetch_watchlist(self, cfg):
        symbols = _load_watchlist()
        stocks = [s for s in symbols if "/" not in s]
        cryptos = [s for s in symbols if "/" in s]
        result = []
        headers = {
            "APCA-API-KEY-ID": cfg["api_key"],
            "APCA-API-SECRET-KEY": cfg["secret_key"],
        }

        if stocks:
            try:
                r = http_requests.get(
                    "https://data.alpaca.markets/v2/stocks/snapshots",
                    params={"symbols": ",".join(stocks), "feed": "iex"},
                    headers=headers, timeout=10,
                )
                snapshots = r.json()
                for sym in stocks:
                    if sym in snapshots:
                        snap = snapshots[sym]
                        price = snap.get("latestTrade", {}).get("p", 0)
                        prev = snap.get("prevDailyBar", {}).get("c", 0)
                        change = ((price - prev) / prev * 100) if prev else 0
                        result.append({
                            "symbol": sym, "price": price,
                            "change_pct": change, "type": "stock",
                        })
            except Exception:
                pass

        if cryptos:
            try:
                r = http_requests.get(
                    "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades",
                    params={"symbols": ",".join(cryptos)},
                    headers=headers, timeout=10,
                )
                trades = r.json()
                r2 = http_requests.get(
                    "https://data.alpaca.markets/v1beta3/crypto/us/bars",
                    params={"symbols": ",".join(cryptos), "timeframe": "1Day", "limit": 1},
                    headers=headers, timeout=10,
                )
                bars_data = r2.json().get("bars", {})
                for sym in cryptos:
                    price = 0
                    if "trades" in trades and sym in trades["trades"]:
                        price = trades["trades"][sym].get("p", 0)
                    elif "trades" in trades and sym.replace("/", "") in trades["trades"]:
                        price = trades["trades"][sym.replace("/", "")].get("p", 0)
                    change = 0
                    sym_bars = bars_data.get(sym, [])
                    if sym_bars and price:
                        day_open = sym_bars[-1].get("o", 0)
                        if day_open:
                            change = (price - day_open) / day_open * 100
                    result.append({
                        "symbol": sym, "price": price,
                        "change_pct": change, "type": "crypto",
                    })
            except Exception:
                pass

        return result

    def _fetch_orders_and_fills(self, api):
        orders = api.list_orders(status="open", limit=50)
        result = []
        current_ids = set()
        for o in orders:
            current_ids.add(o.id)
            strategy = "manual"
            if o.client_order_id:
                coid = str(o.client_order_id)
                for prefix in ("grid_", "dca_", "momentum_", "mean_reversion_", "dip_buyer_"):
                    if coid.startswith(prefix):
                        parts = coid.split("_", 2)
                        strategy = f"{parts[0]}-{parts[1]}" if len(parts) > 1 else parts[0]
                        break
            time_str = _utc_to_local_str(o.submitted_at)[:11]
            result.append({
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": float(o.qty) if o.qty else 0,
                "type": o.type,
                "status": o.status,
                "limit_price": float(o.limit_price) if o.limit_price else None,
                "stop_price": float(o.stop_price) if o.stop_price else None,
                "submitted_at": time_str,
                "strategy": strategy,
            })

        # Detect new orders for trade log
        if self._seen_order_ids:
            new_ids = current_ids - self._seen_order_ids
            for o in result:
                if o["id"] in new_ids:
                    side_txt = o["side"].upper()
                    price_txt = f"@ ${o['limit_price']:.2f}" if o["limit_price"] else "MKT"
                    ts = datetime.now().strftime("%m/%d %H:%M:%S")
                    msg = f"NEW {side_txt} {o['symbol']} x{o['qty']:.0f} {price_txt} {o['type']} [{o['strategy']}]"
                    self._trade_log.append({"ts": ts, "msg": msg, "style": "new"})
                    self._db_insert_log(ts, msg, "new", o["id"])
        self._seen_order_ids.update(current_ids)

        # Check recent filled orders
        try:
            filled = api.list_orders(status="closed", limit=20)
            for o in filled:
                if o.status == "filled" and o.id not in self._seen_order_ids:
                    self._seen_order_ids.add(o.id)
                    if o.filled_at:
                        side_txt = o.side.upper()
                        price = float(o.filled_avg_price) if o.filled_avg_price else 0
                        qty = float(o.qty) if o.qty else 0
                        qty_fmt = f"{qty:.6f}".rstrip("0").rstrip(".") if qty % 1 else f"{qty:.0f}"
                        ts = _utc_to_local_str(o.filled_at)
                        msg = f"FILL {side_txt} {o.symbol} x{qty_fmt} @ ${price:,.2f}"
                        self._trade_log.append({"ts": ts, "msg": msg,
                            "style": "fill-buy" if o.side == "buy" else "fill-sell"})
                        self._db_insert_log(ts, msg,
                            "fill-buy" if o.side == "buy" else "fill-sell", o.id)
                        if len(self._trade_log) > 200:
                            self._trade_log.pop(0)
        except Exception:
            pass

        return result

    def _fetch_strategies(self):
        sm = _get_strategy_manager()
        if not sm:
            return []
        strategies = sm.list_strategies()
        result = []
        for s in strategies:
            last_tick = ""
            if s.get("last_tick"):
                try:
                    raw = str(s["last_tick"]).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(raw)
                    local_dt = dt.astimezone()
                    last_tick = local_dt.strftime("%H:%M:%S")
                except Exception:
                    last_tick = str(s["last_tick"])[:8]
            is_crypto = "/" in str(s.get("name", "")) or "eth" in str(s.get("name", "")).lower() or "btc" in str(s.get("name", "")).lower()
            result.append({
                "name": s.get("name", ""),
                "type": s.get("type", ""),
                "status": s.get("status", "stopped"),
                "capital": s.get("capital_allocated", 0) + s.get("realized_pnl", 0),
                "used": s.get("capital_used", 0),
                "realized_pnl": s.get("realized_pnl", 0),
                "unrealized_pnl": s.get("unrealized_pnl", 0),
                "total_pnl": s.get("total_pnl", 0),
                "fills": s.get("total_fills", 0),
                "last_tick": last_tick or "---",
                "error_msg": s.get("error_msg", ""),
                "is_crypto": is_crypto,
            })
        return result

    def _load_order_history(self, api):
        """Load historical fills from Alpaca into SQLite (one-time)."""
        try:
            orders = api.list_orders(status="closed", limit=500)
            fills = [o for o in orders if o.status == "filled"]
            seen_ids = set()
            unique_fills = []
            for o in fills:
                if o.id not in seen_ids:
                    seen_ids.add(o.id)
                    unique_fills.append(o)
            fills = unique_fills
            fills.sort(key=lambda o: str(o.filled_at or o.submitted_at or ""))

            for o in fills:
                if o.id in self._seen_order_ids:
                    continue
                self._seen_order_ids.add(o.id)
                ts = _utc_to_local_str(o.filled_at or o.submitted_at)
                side_txt = o.side.upper()
                qty = float(o.qty) if o.qty else 0
                price = float(o.filled_avg_price) if o.filled_avg_price else 0
                sym = o.symbol
                cid = o.client_order_id or ""
                strat_tag = ""
                m = _re.match(r'^(grid|dca|momentum|mean_reversion|dip_buyer|momentum_scalper)_([^_]+)_', cid)
                if m:
                    strat_tag = f" [{m.group(2)}]"
                style = "fill-buy" if o.side == "buy" else "fill-sell"
                qty_fmt = f"{qty:.6f}".rstrip("0").rstrip(".") if qty % 1 else f"{qty:.0f}"
                msg = f"FILL {side_txt} {sym} x{qty_fmt} @ ${price:,.2f}{strat_tag}"
                self._trade_log.append({"ts": ts, "msg": msg, "style": style})
                self._db_insert_log(ts, msg, style, o.id)

            if fills:
                ts = datetime.now().strftime("%m/%d %H:%M:%S")
                msg = f"Loaded {len(fills)} historical fills from Alpaca"
                self._trade_log.append({"ts": ts, "msg": msg, "style": "info"})
                self._db_insert_log(ts, msg, "info")
        except Exception as e:
            ts = datetime.now().strftime("%m/%d %H:%M:%S")
            msg = f"Error loading history: {e}"
            self._trade_log.append({"ts": ts, "msg": msg, "style": "dim"})

    # ── Main background loop ───────────────────────────────

    def start(self):
        """Start the background refresh thread."""
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _fetch_strategies_from_orders(self, api):
        """Derive strategy info from Alpaca orders when no local StrategyManager exists.

        Uses FIFO matching to calculate realized P&L only on completed
        buy→sell round trips. Unrealized P&L uses current position market
        prices from the cached positions data.
        """
        try:
            filled = api.list_orders(status="closed", limit=500)
            fills = [o for o in filled if o.status == "filled"]
            # Sort chronologically for FIFO matching
            fills.sort(key=lambda o: str(o.filled_at or o.submitted_at or ""))

            strats = {}
            for o in fills:
                cid = o.client_order_id or ""
                m = _re.match(r'^(grid|dca|momentum|mean_reversion|dip_buyer|momentum_scalper)_([^_]+)_', cid)
                if not m:
                    continue
                stype, sname = m.group(1), m.group(2)
                key = sname
                if key not in strats:
                    strats[key] = {
                        "name": sname, "type": stype, "status": "active",
                        "capital": 0, "used": 0, "realized_pnl": 0,
                        "unrealized_pnl": 0, "total_pnl": 0, "fills": 0,
                        "last_tick": "---", "error_msg": "", "is_crypto": False,
                        # FIFO queue: list of (remaining_qty, price) for open buys
                        "_buy_queue": [],
                        "_symbol": "",
                    }
                s = strats[key]
                s["fills"] += 1
                s["_symbol"] = o.symbol
                s["is_crypto"] = "/" in o.symbol or "eth" in sname.lower() or "btc" in sname.lower()
                price = float(o.filled_avg_price) if o.filled_avg_price else 0
                qty = float(o.qty) if o.qty else 0
                if o.filled_at:
                    ts = _utc_to_local_str(o.filled_at)
                    s["last_tick"] = ts[6:14] if len(ts) > 6 else ts

                if o.side == "buy":
                    s["_buy_queue"].append([qty, price])  # mutable for FIFO
                    s["used"] += qty * price
                else:
                    # FIFO match sells against buys
                    sell_remaining = qty
                    while sell_remaining > 0 and s["_buy_queue"]:
                        buy_qty, buy_price = s["_buy_queue"][0]
                        matched = min(sell_remaining, buy_qty)
                        s["realized_pnl"] += matched * (price - buy_price)
                        sell_remaining -= matched
                        s["_buy_queue"][0][0] -= matched
                        if s["_buy_queue"][0][0] <= 1e-10:
                            s["_buy_queue"].pop(0)

            # Get current positions for unrealized P&L
            current_positions = {}
            with self._lock:
                for p in self._data.get("positions", []):
                    current_positions[p["symbol"]] = p

            result = []
            for s in strats.values():
                s["realized_pnl"] = round(s["realized_pnl"], 2)
                # Unrealized: remaining buy queue matched against current price
                symbol = s.pop("_symbol")
                pos = current_positions.get(symbol)
                if pos and s["_buy_queue"]:
                    current_price = pos["current"]
                    unrealized = sum(
                        q * (current_price - p) for q, p in s["_buy_queue"]
                    )
                    s["unrealized_pnl"] = round(unrealized, 2)
                s["total_pnl"] = round(s["realized_pnl"] + s["unrealized_pnl"], 2)
                s["capital"] = round(s["used"], 2)
                del s["_buy_queue"]
                result.append(s)
            return result
        except Exception:
            return []

    def _run(self):
        """Tiered background refresh with parallel API calls.

        API calls are parallelized within each cycle so network latency
        doesn't stack (~500ms total instead of ~2100ms sequential).

        Keeps total API calls under Alpaca's 200/min rate limit:
        - Fast (2s):   account + watchlist prices    → 5 calls × 30/min = 150
        - Normal (4s): positions, orders, fills      → 3 calls × 15/min =  45
        - Slow (12s):  strategies                    → 1 call  ×  5/min =   5
        Total: ~200 calls/min (at limit; strategy call is conditional)
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Load trade log from SQLite first
        entries, seen = self._db_load_log()
        if entries:
            self._trade_log = entries
            self._seen_order_ids = seen
            self._history_loaded = True

        cycle = 0
        while True:
            try:
                api = _get_api()
                cfg = _load_config()

                # One-time: load historical fills
                if not self._history_loaded:
                    self._history_loaded = True
                    self._load_order_history(api)

                # ── Parallel fetch: fire all calls for this cycle concurrently ──
                futures = {}
                with ThreadPoolExecutor(max_workers=6) as pool:
                    # Fast tier (every cycle = every 2s)
                    futures["account"] = pool.submit(self._fetch_account, api)
                    futures["watchlist"] = pool.submit(self._fetch_watchlist, cfg)

                    # Normal tier (every 2 cycles = every ~4s)
                    if cycle % 2 == 0:
                        futures["positions"] = pool.submit(self._fetch_positions, api)
                        futures["orders"] = pool.submit(self._fetch_orders_and_fills, api)

                    # Slow tier (every 6 cycles = every ~12s)
                    if cycle % 6 == 0:
                        futures["strategies"] = pool.submit(self._fetch_strategies)

                # Collect results and update cache atomically
                results = {}
                for key, future in futures.items():
                    try:
                        results[key] = future.result(timeout=15)
                    except Exception:
                        pass  # keep last good data

                # Fallback: derive strategies from orders if local manager returned empty
                if "strategies" in results and not results["strategies"]:
                    try:
                        results["strategies"] = self._fetch_strategies_from_orders(api)
                    except Exception:
                        pass

                with self._lock:
                    for key, value in results.items():
                        self._data[key] = value
                    if "orders" in results:
                        self._data["log"] = self._trade_log[-100:]

            except Exception:
                pass  # keep last good data on transient errors

            cycle += 1
            _time.sleep(1.5)


# Global cache instance — starts background refresh immediately on import
_cache = _DataCache()
_cache.start()


# ── API endpoints (serve from cache — instant) ─────────────

@app.route("/api/account")
def api_account():
    return jsonify(_cache.get("account"))


@app.route("/api/positions")
def api_positions():
    return jsonify(_cache.get("positions"))


@app.route("/api/watchlist")
def api_watchlist():
    return jsonify(_cache.get("watchlist"))


@app.route("/api/orders")
def api_orders():
    return jsonify(_cache.get("orders"))


@app.route("/api/strategies")
def api_strategies():
    return jsonify(_cache.get("strategies"))


@app.route("/api/log")
def api_log():
    return jsonify(_cache.get("log"))


def _utc_to_local_str(ts_obj):
    """Convert a UTC timestamp (string, datetime, or pandas Timestamp) to local MM/DD HH:MM:SS."""
    from datetime import timezone as tz
    if ts_obj is None:
        return "---"
    try:
        # Convert pandas Timestamp to stdlib datetime first
        if hasattr(ts_obj, 'to_pydatetime'):
            ts_obj = ts_obj.to_pydatetime()
        if isinstance(ts_obj, str):
            raw = ts_obj.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
        elif hasattr(ts_obj, 'astimezone'):
            dt = ts_obj
        else:
            return "---"
        # Ensure UTC aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz.utc)
        local_dt = dt.astimezone()
        return local_dt.strftime("%m/%d %H:%M:%S")
    except Exception:
        return "---"


@app.route("/api/bars/<path:symbol>")
def api_bars(symbol):
    try:
        cfg = _load_config()
        headers = {
            "APCA-API-KEY-ID": cfg["api_key"],
            "APCA-API-SECRET-KEY": cfg["secret_key"],
        }
        end = datetime.now()
        start = end - timedelta(days=30)
        result = []

        if "/" in symbol:
            # Crypto — use v1beta3 endpoint
            r = http_requests.get(
                "https://data.alpaca.markets/v1beta3/crypto/us/bars",
                params={
                    "symbols": symbol,
                    "timeframe": "1Day",
                    "start": start.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": end.strftime("%Y-%m-%dT00:00:00Z"),
                    "limit": 30,
                },
                headers=headers, timeout=10,
            )
            data = r.json()
            for bar in data.get("bars", {}).get(symbol, []):
                result.append({
                    "open": bar["o"], "high": bar["h"],
                    "low": bar["l"], "close": bar["c"],
                    "volume": int(bar.get("v", 0) if isinstance(bar.get("v", 0), (int, float)) and bar.get("v", 0) > 1 else 0),
                })
        else:
            # Stocks — use alpaca-trade-api
            api = _get_api()
            bars = api.get_bars(
                symbol, tradeapi.TimeFrame.Day,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                limit=30, feed="iex",
            ).df
            for _, row in bars.iterrows():
                result.append({
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                })

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── HTML Dashboard ─────────────────────────────────────────

@app.route("/")
def index():
    return Response(DASHBOARD_HTML, content_type="text/html")


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenClaw Terminal</title>
<style>
  :root {
    --bg: #010409;
    --dark-bg: #0d1117;
    --panel-bg: #010409;
    --header-bg: #0d1117;
    --border: #30363d;
    --text: #f0f6fc;
    --dim: #8b949e;
    --white: #f0f6fc;
    --accent: #58c0fa;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --cyan: #79c0ff;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    background: var(--bg); color: var(--text);
    font-size: 13px; line-height: 1.3;
    overflow: hidden; height: 100vh;
    display: flex; flex-direction: column;
    padding: 6px;
  }

  /* ── Title Bar ── */
  #title-bar {
    height: 28px; display: flex; align-items: center;
    padding: 0 14px; background: var(--accent); color: #010409;
    font-weight: 700; font-size: 13px;
    flex-shrink: 0; white-space: nowrap; overflow: hidden;
  }
  #title-bar .sep { margin: 0 6px; opacity: 0.4; }

  /* ── Account Bar ── */
  #account-bar {
    height: 28px; display: flex; align-items: center;
    padding: 0 14px; background: var(--dark-bg);
    font-size: 13px; flex-shrink: 0;
    white-space: nowrap; overflow: hidden;
  }
  #account-bar .lbl { color: var(--dim); margin-right: 4px; }
  #account-bar .val { font-weight: 700; color: var(--white); margin-right: 12px; }

  /* ── Main layout — 3 rows: tables(9fr), strat-area(4fr), log(1fr) ── */
  .main {
    flex: 1; display: flex; flex-direction: column;
    overflow: hidden; min-height: 0;
  }

  /* Row 1: watchlist(2fr) | positions(3fr), height: ~60% */
  #tables-row {
    flex: 9; display: flex; min-height: 0;
    border-bottom: 1px solid var(--border);
  }
  #watchlist-pane {
    flex: 2; display: flex; flex-direction: column;
    border-right: 1px solid var(--border); min-width: 0; overflow: hidden;
  }
  #positions-pane {
    flex: 3; display: flex; flex-direction: column;
    min-width: 0; overflow: hidden;
  }

  /* Row 2: strategies(2fr) | orders(1fr), height: ~25% */
  #strat-area {
    flex: 4; display: flex; min-height: 0;
    border-bottom: 1px solid var(--border);
  }
  #strat-left {
    flex: 2; display: flex; flex-direction: column;
    border-right: 1px solid var(--border); min-width: 0; overflow: hidden;
  }
  #strat-right {
    flex: 1; display: flex; flex-direction: column;
    min-width: 0; overflow: hidden;
  }

  /* Row 3: trading log, height: remaining */
  #log-area {
    flex: 4; display: flex; flex-direction: column;
    min-height: 80px; overflow: hidden;
  }

  /* ── Pane title ── */
  .pane-title {
    height: 26px; padding: 0 12px; font-size: 13px; font-weight: 700;
    color: var(--accent); background: var(--header-bg);
    display: flex; align-items: center; flex-shrink: 0;
    border-bottom: 1px solid var(--border);
    cursor: grab; user-select: none;
  }
  .pane-title:active { cursor: grabbing; }
  .pane-title .drag-handle {
    margin-right: 6px; opacity: 0.3; font-size: 11px; letter-spacing: -1px;
  }
  .pane-title:hover .drag-handle { opacity: 0.7; }

  /* ── Drag & drop feedback ── */
  .panel[draggable] { transition: opacity 0.15s; }
  .panel.drag-over {
    outline: 1px solid var(--accent); outline-offset: -1px;
  }
  .panel.dragging { opacity: 0.4; }

  /* ── Tables ── */
  .tbl-wrap { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 0 4px; }
  table { width: 100%; border-collapse: collapse; }
  /* Header — centered over column body */
  th {
    position: sticky; top: 0; z-index: 1;
    padding: 4px 10px; text-align: center;
    font-size: 13px; font-weight: 700;
    color: var(--accent); background: var(--header-bg);
    border-bottom: 1px solid var(--border);
    overflow: hidden; text-overflow: ellipsis;
  }
  td {
    padding: 4px 10px; text-align: center;
    white-space: nowrap; font-size: 13px;
    overflow: hidden; text-overflow: ellipsis;
  }
  /* Right-align numeric columns */
  th.r, td.r { text-align: right; }
  .sym { font-weight: 700; color: var(--white); }
  .pos { color: var(--green); }
  .neg { color: var(--red); }
  .dim { color: var(--dim); }
  .cyn { color: var(--cyan); }
  .yel { color: var(--yellow); }
  .wht { color: var(--white); font-weight: 700; }
  .bld { font-weight: 700; }

  /* ── Trade Log ── */
  #log-body {
    flex: 1; overflow-y: auto; padding: 4px 12px; font-size: 13px;
  }
  .log-entry { line-height: 1.4; }
  .log-ts { color: var(--dim); margin-right: 8px; }
  .log-fill-buy { color: var(--green); font-weight: 700; }
  .log-fill-sell { color: var(--red); font-weight: 700; }
  .log-new { color: var(--yellow); }
  .log-cancel { color: var(--dim); }
  .log-strat { color: var(--accent); }
  .log-info { color: var(--cyan); }

  /* ── Status Line ── */
  #status-line {
    height: 26px; display: flex; align-items: center;
    padding: 0 14px; background: var(--header-bg);
    color: var(--dim); font-size: 13px;
    flex-shrink: 0;
    white-space: nowrap; overflow: hidden;
  }
  #status-line .sep { margin: 0 6px; }

  /* ── Empty state ── */
  .empty { padding: 8px; color: var(--dim); font-size: 13px; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border); }

  @media (max-width: 900px) {
    #tables-row, #strat-area { flex-direction: column; }
    #watchlist-pane, #positions-pane, #strat-left, #strat-right {
      flex: 1; border-right: none; border-bottom: 1px solid var(--border);
    }
  }
</style>
</head>
<body>

<!-- Title Bar: " OPENCLAW TERMINAL  │  HH:MM:SS ●  │  Stock Market OPEN/CLOSED  │  Strategies X/Y [AUTO Xs]  │  Press / command" -->
<div id="title-bar">
  <span>&nbsp;OPENCLAW TERMINAL</span>
  <span class="sep">│</span>
  <span id="title-clock">--:--:--</span>
  <span id="breath-dot">&nbsp;●</span>
  <span class="sep">│</span>
  <span>Stock Market <span id="title-market">CLOSED</span></span>
  <span class="sep">│</span>
  <span id="title-strat">Strategies 0/0</span>
  <span class="sep">│</span>
  <span>Press <b>/</b> command</span>
</div>

<!-- Account Bar: " EQUITY $X  CASH $X  BP $X  DAY ▲+$X (+X.XX%)  STRAT +$X  DEPLOYED $X/$X  ACTIVE" -->
<div id="account-bar">
  <span class="lbl">EQUITY</span><span class="val" id="ab-equity">—</span>
  <span class="lbl">CASH</span><span class="val" id="ab-cash">—</span>
  <span class="lbl">BP</span><span class="val" id="ab-bp">—</span>
  <span class="lbl">DAY</span><span class="val" id="ab-day">—</span>
  <span class="lbl">STRAT</span><span class="val" id="ab-strat">—</span>
  <span class="lbl">DEPLOYED</span><span class="val" id="ab-deployed">—</span>
  <span id="ab-status" style="color:var(--accent);margin-left:auto;font-weight:700"></span>
</div>

<div class="main">
  <!-- Row 1: Watchlist | Positions -->
  <div id="tables-row">

    <div id="watchlist-pane" class="panel" draggable="true" data-panel="watchlist">
      <div class="pane-title"><span class="drag-handle">⠿</span>&nbsp;WATCHLIST</div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>&nbsp;#</th><th>MARKET</th><th class="r">Price</th><th class="r">Chg</th><th>Trend</th></tr></thead>
          <tbody id="watchlist-body"></tbody>
        </table>
      </div>
    </div>

    <div id="positions-pane" class="panel" draggable="true" data-panel="positions">
      <div class="pane-title"><span class="drag-handle">⠿</span>&nbsp;POSITIONS</div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Symbol</th><th class="r">Qty</th><th class="r">Price</th><th class="r">P&amp;L</th><th class="r">P&amp;L%</th></tr></thead>
          <tbody id="positions-body"></tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Row 2: Strategies | Open Orders -->
  <div id="strat-area">

    <div id="strat-left" class="panel" draggable="true" data-panel="strategies">
      <div class="pane-title"><span class="drag-handle">⠿</span>&nbsp;STRATEGIES</div>
      <div class="tbl-wrap">
        <table>
          <thead><tr>
            <th>Name</th><th>Type</th><th>Status</th><th class="r">Capital</th><th class="r">Used</th>
            <th class="r">Real P&amp;L</th><th class="r">Unrl P&amp;L</th><th class="r">Total P&amp;L</th>
            <th class="r">Fills</th><th class="r">Last Tick</th>
          </tr></thead>
          <tbody id="strat-body"></tbody>
        </table>
        <div class="empty" id="strat-empty">No strategies. Use main terminal to add — they will show up here.</div>
      </div>
    </div>

    <div id="strat-right" class="panel" draggable="true" data-panel="orders">
      <div class="pane-title"><span class="drag-handle">⠿</span>&nbsp;OPEN ORDERS</div>
      <div class="tbl-wrap">
        <table>
          <thead><tr>
            <th>Time</th><th>Side</th><th>Symbol</th><th class="r">Qty</th>
            <th>Type</th><th class="r">Limit</th><th>Status</th><th>Strategy</th>
          </tr></thead>
          <tbody id="orders-body"></tbody>
        </table>
        <div class="empty" id="orders-empty" style="display:none">No open orders</div>
      </div>
    </div>

  </div>

  <!-- Row 3: Trading Log -->
  <div id="log-area" class="panel" draggable="true" data-panel="log">
    <div class="pane-title"><span class="drag-handle">⠿</span>&nbsp;TRADING LOG</div>
    <div id="log-body">
      <div class="log-entry"><span class="log-ts">--/-- --:--:--</span><span class="log-info">Terminal started — loading recent orders...</span></div>
    </div>
  </div>
</div>

<!-- Status Line -->
<div id="status-line">
  <span>Auto-refresh every 5s</span>
  <span class="sep">│</span>
  <span id="tick-count">tick #0</span>
  <span class="sep">│</span>
  <span id="status-time"></span>
</div>

<script>
const $ = s => document.getElementById(s);
const fmt = (n, d=2) => n != null ? n.toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) : '—';
const sign = n => n >= 0 ? '+' : '';
const arrow = n => n > 0.001 ? '▲' : n < -0.001 ? '▼' : '─';
const cls = n => n >= 0 ? 'pos' : 'neg';

/* Currency formatter matching original fmt():
   >= 1M  -> "$1.5M"
   >= 100K -> "$125.5K"
   else   -> "$1,234.56"  */
function fmtC(n) {
  if (n == null) return '—';
  const a = Math.abs(n);
  if (a >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (a >= 1e5) return '$' + (n/1e3).toFixed(1) + 'K';
  return '$' + fmt(n);
}

const barCache = {};
let tickNum = 0;
let breathOn = true;
let marketOpen = false;

function renderSpark(bars) {
  if (!bars || !bars.length) return '<span class="dim">&nbsp;&nbsp;···&nbsp;&nbsp;</span>';
  const closes = bars.map(b => b.close);
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const rng = hi - lo || 1;
  const width = 10;
  let sampled = closes;
  if (closes.length !== width) {
    const step = Math.max(closes.length / width, 1);
    sampled = [];
    for (let i = 0; i < width; i++) sampled.push(closes[Math.min(Math.floor(i * step), closes.length - 1)]);
  }
  const blocks = '\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588';
  return sampled.map((c, i) => {
    const idx = Math.min(Math.floor((c - lo) / rng * 7), 7);
    const color = i === 0 || c >= sampled[i-1] ? 'var(--green)' : 'var(--red)';
    return `<span style="color:${color}">${blocks[idx]}</span>`;
  }).join('');
}

async function fetchJSON(url) {
  try { const r = await fetch(url); return r.json(); }
  catch(e) { return {error: e.message}; }
}

// ── Clock (1s) ──
function updateClock() {
  const now = new Date();
  $('title-clock').textContent = now.toLocaleTimeString('en-US', {hour12: false});
  breathOn = !breathOn;
  $('breath-dot').textContent = breathOn ? ' \u25CF' : ' \u25CB';
}
setInterval(updateClock, 1000);
updateClock();

// ── Account ──
async function refreshAccount() {
  const d = await fetchJSON('/api/account');
  if (d.error) return;
  $('ab-equity').textContent = fmtC(d.equity);
  $('ab-cash').textContent = fmtC(d.cash);
  $('ab-bp').textContent = fmtC(d.buying_power);
  $('ab-status').textContent = d.status;

  // DAY P&L — matches: [color]▲+$X (+X.XX%)[/]
  const dc = d.pnl >= 0 ? 'pos' : 'neg';
  const ds = d.pnl >= 0 ? '+' : '';
  $('ab-day').innerHTML = `<span class="${dc}">${arrow(d.pnl)}${ds}${fmtC(d.pnl)} (${ds}${d.pnl_pct.toFixed(2)}%)</span>`;

  // STRAT P&L
  const sc = d.strat_pnl >= 0 ? 'pos' : 'neg';
  const ss = d.strat_pnl >= 0 ? '+' : '';
  $('ab-strat').innerHTML = `<span class="${sc}">${ss}${fmtC(d.strat_pnl)}</span>`;

  $('ab-deployed').textContent = `${fmtC(d.strat_deployed)}/${fmtC(d.strat_allocated)}`;
  $('title-strat').textContent = `Strategies ${d.strat_active} active / ${d.strat_total} total`;

  $('title-market').textContent = d.market_open ? 'OPEN' : 'CLOSED';
  marketOpen = d.market_open;

}

// ── Watchlist — columns: #, MARKET, Price, Chg, Trend ──
async function refreshWatchlist() {
  const data = await fetchJSON('/api/watchlist');
  if (data.error || !Array.isArray(data)) return;

  for (const item of data) {
    if (!barCache[item.symbol]) {
      fetchJSON('/api/bars/' + encodeURIComponent(item.symbol))
        .then(bars => { if (Array.isArray(bars)) barCache[item.symbol] = bars; })
        .catch(() => {});
    }
  }

  $('watchlist-body').innerHTML = data.map((w, i) => {
    const chg = w.change_pct;
    const pc = chg > 0.01 ? 'pos' : chg < -0.01 ? 'neg' : 'dim';
    const ps = chg > 0.01 ? 'pos' : chg < -0.01 ? 'neg' : 'wht';
    // Large prices (crypto) show $ change; stocks show %
    const chgTxt = Math.abs(w.price) >= 1000
      ? `${arrow(chg)}${sign(chg)}$${Math.abs(w.price * chg / 100).toFixed(0)}`
      : `${arrow(chg)}${(chg*1).toFixed(2)}%`;
    return `<tr>
      <td class="dim">&nbsp;&nbsp;${i+1}</td>
      <td class="sym">${w.symbol}</td>
      <td class="r ${ps}">${fmtC(w.price)}</td>
      <td class="r ${pc}">${chgTxt}</td>
      <td>${renderSpark(barCache[w.symbol])}</td>
    </tr>`;
  }).join('');
}

// ── Positions — columns: POSITIONS, Qty, Price, P&L, P&L% + TOTAL row ──
async function refreshPositions() {
  const data = await fetchJSON('/api/positions');
  if (data.error || !Array.isArray(data)) return;
  if (!data.length) {
    $('positions-body').innerHTML = '<tr><td class="dim" colspan="5">No positions</td></tr>';
    return;
  }

  let totalVal = 0, totalPnl = 0;
  data.forEach(p => { totalVal += p.market_value; totalPnl += p.pnl; });

  $('positions-body').innerHTML = data.map(p => {
    const c = cls(p.pnl), s = sign(p.pnl);
    return `<tr>
      <td class="sym">${p.symbol}</td>
      <td class="r">${p.qty % 1 ? p.qty.toFixed(4).replace(/0+$/,'') : p.qty}</td>
      <td class="r wht">${fmtC(p.current)}</td>
      <td class="r ${c}">${arrow(p.pnl)}${s}${fmtC(p.pnl)}</td>
      <td class="r ${c}">${s}${p.pnl_pct.toFixed(2)}%</td>
    </tr>`;
  }).join('') + `<tr>
    <td class="wht bld">TOTAL</td><td></td>
    <td class="r wht">${fmtC(totalVal)}</td>
    <td class="r ${cls(totalPnl)} bld">${sign(totalPnl)}${fmtC(totalPnl)}</td>
    <td></td>
  </tr>`;
}

// ── Strategies — 10 columns matching original ──
async function refreshStrategies() {
  const data = await fetchJSON('/api/strategies');
  if (data.error || !Array.isArray(data)) return;
  const tbody = $('strat-body');
  const empty = $('strat-empty');
  if (!data.length) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  const statusMap = {
    active:       ['\u25CF ACTIVE',  'pos'],
    pending:      ['\u25CC PENDING', 'yel'],
    initializing: ['\u25CE INIT',    'yel'],
    paused:       ['|| PAUSED',      'dim'],
    stopped:      ['\u25A0 STOPPED', 'dim'],
    error:        ['X ERROR',        'neg'],
  };

  tbody.innerHTML = data.map(s => {
    let [statusTxt, sCls] = statusMap[s.status] || ['?', 'dim'];
    // Show IDLE for stock strategies when market is closed
    if (!s.is_crypto && !marketOpen && s.status === 'active') {
      statusTxt = '\u25CB MKT CLOSED';
      sCls = 'dim';
    }
    const err = s.status === 'error' && s.error_msg ? ` (${s.error_msg.slice(0,20)})` : '';
    return `<tr>
      <td class="sym">${s.name}</td>
      <td class="cyn">${s.type}</td>
      <td class="${sCls}">${statusTxt}${err}</td>
      <td class="r wht">${fmtC(s.capital)}</td>
      <td class="r dim">${fmtC(s.used)}</td>
      <td class="r ${cls(s.realized_pnl)}">${sign(s.realized_pnl)}${fmtC(s.realized_pnl)}</td>
      <td class="r ${cls(s.unrealized_pnl)}">${sign(s.unrealized_pnl)}${fmtC(s.unrealized_pnl)}</td>
      <td class="r ${cls(s.total_pnl)} bld">${sign(s.total_pnl)}${fmtC(s.total_pnl)}</td>
      <td class="r wht">${s.fills}</td>
      <td class="r dim">${s.last_tick}</td>
    </tr>`;
  }).join('');
}

// ── Orders — 8 columns matching original ──
async function refreshOrders() {
  const data = await fetchJSON('/api/orders');
  if (data.error || !Array.isArray(data)) return;
  const tbody = $('orders-body');
  const empty = $('orders-empty');
  if (!data.length) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';
  tbody.innerHTML = data.map(o => {
    const sc = o.side === 'buy' ? 'pos' : 'neg';
    const statusCls = (o.status === 'new' || o.status === 'accepted') ? 'yel' : 'dim';
    const stratCls = o.strategy !== 'manual' ? 'cyn' : 'dim';
    return `<tr>
      <td class="dim">${o.submitted_at}</td>
      <td class="${sc} bld">${o.side.toUpperCase()}</td>
      <td class="sym">${o.symbol}</td>
      <td class="r">${o.qty || '---'}</td>
      <td class="dim">${o.type}</td>
      <td class="r">${o.limit_price ? fmtC(o.limit_price) : 'mkt'}</td>
      <td class="${statusCls}">${o.status}</td>
      <td class="${stratCls}">${o.strategy}</td>
    </tr>`;
  }).join('');
}

// ── Trade Log ──
async function refreshLog() {
  const data = await fetchJSON('/api/log');
  if (data.error || !Array.isArray(data)) return;
  const body = $('log-body');
  if (!data.length) {
    body.innerHTML = '<div class="log-entry"><span class="dim">Loading trade history...</span></div>';
    return;
  }
  body.innerHTML = data.map(e => {
    const c = {'fill-buy':'log-fill-buy','fill-sell':'log-fill-sell','new':'log-new','cancel':'log-cancel','strat':'log-strat','info':'log-info'}[e.style] || 'dim';
    return `<div class="log-entry"><span class="log-ts">${e.ts}</span><span class="${c}">${e.msg}</span></div>`;
  }).join('');
  body.scrollTop = body.scrollHeight;
}

// ── Main tick ──
async function tick() {
  tickNum++;
  await Promise.all([refreshAccount(), refreshPositions(), refreshWatchlist(), refreshOrders(), refreshStrategies(), refreshLog()]);
  $('tick-count').textContent = 'tick #' + tickNum;
  $('status-time').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
}

tick();
setInterval(tick, 5000);
setInterval(() => { Object.keys(barCache).forEach(k => delete barCache[k]); }, 60000);

// ── Drag-to-swap panels (any panel ↔ any panel via innerHTML swap) ──
(function() {
  let dragSrc = null;

  document.querySelectorAll('.panel').forEach(panel => {
    panel.addEventListener('dragstart', e => {
      dragSrc = panel;
      panel.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', panel.dataset.panel);
    });
    panel.addEventListener('dragend', () => {
      panel.classList.remove('dragging');
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('drag-over'));
      dragSrc = null;
    });
    panel.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (dragSrc && dragSrc !== panel) {
        panel.classList.add('drag-over');
      }
    });
    panel.addEventListener('dragleave', () => {
      panel.classList.remove('drag-over');
    });
    panel.addEventListener('drop', e => {
      e.preventDefault();
      panel.classList.remove('drag-over');
      if (!dragSrc || dragSrc === panel) return;
      // Swap innerHTML — containers stay in place, content moves
      const tmpHTML = panel.innerHTML;
      panel.innerHTML = dragSrc.innerHTML;
      dragSrc.innerHTML = tmpHTML;
      // Swap data-panel attribute
      const tmpAttr = panel.dataset.panel;
      panel.dataset.panel = dragSrc.dataset.panel;
      dragSrc.dataset.panel = tmpAttr;
      saveLayout();
    });
  });

  function saveLayout() {
    const layout = {};
    document.querySelectorAll('.panel').forEach(p => {
      layout[p.id] = p.dataset.panel;
    });
    localStorage.setItem('oc-layout', JSON.stringify(layout));
  }

  function restoreLayout() {
    try {
      const layout = JSON.parse(localStorage.getItem('oc-layout'));
      if (!layout) return;
      // Collect current state: panelName -> innerHTML
      const contentByName = {};
      document.querySelectorAll('.panel').forEach(p => {
        contentByName[p.dataset.panel] = p.innerHTML;
      });
      // Apply saved mapping: containerId -> panelName
      Object.entries(layout).forEach(([containerId, panelName]) => {
        const container = document.getElementById(containerId);
        if (!container || !contentByName[panelName]) return;
        container.innerHTML = contentByName[panelName];
        container.dataset.panel = panelName;
      });
    } catch(e) {}
  }
  restoreLayout();
})();

// ── Resizable dividers (row and column) ──
(function() {
  function saveSizes() {
    const state = {};
    document.querySelectorAll('[data-resize-id]').forEach(el => {
      state[el.dataset.resizeId] = { w: el.style.width || '', h: el.style.height || '', flex: el.style.flex || '' };
    });
    localStorage.setItem('oc-sizes', JSON.stringify(state));
  }

  function createDivider(direction) {
    const isCol = direction === 'col'; // col-resize = vertical bar, drag left/right
    const div = document.createElement('div');
    div.className = 'resize-divider';
    div.style.cssText = isCol
      ? 'width:1px;min-width:1px;cursor:col-resize;background:var(--border);flex-shrink:0;z-index:10;'
      : 'height:1px;min-height:1px;cursor:row-resize;background:var(--border);flex-shrink:0;z-index:10;';
    div.title = 'Drag to resize';

    div.addEventListener('mousedown', e => {
      e.preventDefault();
      // Dynamically find neighbors at drag time (survives panel swaps)
      const prev = div.previousElementSibling;
      const next = div.nextElementSibling;
      if (!prev || !next) return;

      const startPos = isCol ? e.clientX : e.clientY;
      const startPrev = isCol ? prev.getBoundingClientRect().width : prev.getBoundingClientRect().height;
      const startNext = isCol ? next.getBoundingClientRect().width : next.getBoundingClientRect().height;

      prev.style.flex = 'none';
      next.style.flex = 'none';
      if (isCol) { prev.style.width = startPrev + 'px'; next.style.width = startNext + 'px'; }
      else { prev.style.height = startPrev + 'px'; next.style.height = startNext + 'px'; }

      function onMove(ev) {
        const d = (isCol ? ev.clientX : ev.clientY) - startPos;
        const newPrev = Math.max(60, startPrev + d);
        const newNext = Math.max(60, startNext - d);
        if (isCol) { prev.style.width = newPrev + 'px'; next.style.width = newNext + 'px'; }
        else { prev.style.height = newPrev + 'px'; next.style.height = newNext + 'px'; }
      }
      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        saveSizes();
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    return div;
  }

  // Tag resizable elements
  const rowEls = [
    document.getElementById('tables-row'),
    document.getElementById('strat-area'),
    document.getElementById('log-area'),
  ];
  rowEls.forEach((el, i) => { el.dataset.resizeId = 'row-' + i; });

  // Row dividers (horizontal bar — drag up/down)
  for (let i = 0; i < rowEls.length - 1; i++) {
    rowEls[i].after(createDivider('row'));
    rowEls[i].style.borderBottom = 'none';
  }

  // Column dividers (vertical bar — drag left/right)
  [['watchlist-pane','positions-pane'], ['strat-left','strat-right']].forEach(([lId, rId]) => {
    const l = document.getElementById(lId), r = document.getElementById(rId);
    if (!l || !r) return;
    l.dataset.resizeId = lId;
    r.dataset.resizeId = rId;
    l.style.borderRight = 'none';
    l.after(createDivider('col'));
  });

  // Restore saved sizes
  try {
    const state = JSON.parse(localStorage.getItem('oc-sizes'));
    if (!state) return;
    Object.entries(state).forEach(([id, s]) => {
      const el = document.querySelector(`[data-resize-id="${id}"]`);
      if (!el) return;
      if (s.w) { el.style.flex = 'none'; el.style.width = s.w; }
      if (s.h) { el.style.flex = 'none'; el.style.height = s.h; }
    });
  } catch(e) {}
})();
</script>
</body>
</html>
"""

# ── Auto-reload ────────────────────────────────────────────

def _run_with_reload(host, port):
    """Run the dashboard with auto-reload on file changes.

    Uses a subprocess approach: the parent process watches for file changes
    and restarts the child server process when .py files are modified.
    Uses a subprocess approach: the parent process watches for file changes
    and restarts the child server process when .py files are modified.
    """
    import os
    import socket
    import subprocess
    import time

    watch_dir = SKILL_DIR
    watch_extensions = {".py", ".json"}

    def _snapshot():
        snap = {}
        for ext in watch_extensions:
            for f in watch_dir.rglob(f"*{ext}"):
                parts = f.parts
                if ".venv" in parts or "__pycache__" in parts or "node_modules" in parts:
                    continue
                try:
                    snap[str(f)] = f.stat().st_mtime
                except OSError:
                    pass
        return snap

    def _wait_for_port_free(h, p, timeout=10):
        """Wait until the port is available for binding."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind((h, p))
                    return True
                except OSError:
                    time.sleep(0.3)
        return False

    def _start_child():
        env = os.environ.copy()
        env["_DASHBOARD_CHILD"] = "1"
        cmd = [sys.executable, __file__, "--port", str(port), "--host", host]
        return subprocess.Popen(cmd, env=env)

    print(f"\n  📊 Alpaca Paper Trading Dashboard (auto-reload)")
    print(f"  ─────────────────────────────────────────────────")
    print(f"  Local:  http://{host}:{port}")
    print(f"  Reload: watching {watch_dir} for changes")
    print(f"  Tip:    Edit any .py file — dashboard reloads automatically")
    print(f"          The tunnel stays alive, no URL change.\n")

    # Kill any existing dashboard on this port (but NOT tunnel processes)
    try:
        import subprocess as _sp
        pids = _sp.check_output(
            ["lsof", "-ti", f":{port}"], text=True, stderr=_sp.DEVNULL
        ).strip().split()
        my_pid = str(os.getpid())
        for pid in pids:
            if pid and pid != my_pid:
                os.kill(int(pid), 9)
        if pids:
            time.sleep(1)
    except (subprocess.CalledProcessError, OSError, ValueError):
        pass
    _wait_for_port_free(host, port)

    prev = _snapshot()
    proc = _start_child()
    crash_count = 0

    try:
        while True:
            time.sleep(1.5)
            # Check child is alive
            if proc.poll() is not None:
                crash_count += 1
                backoff = min(2 ** crash_count, 30)
                print(f"  ⚠️  Dashboard process exited, restarting in {backoff}s...")
                time.sleep(backoff)
                _wait_for_port_free(host, port)
                proc = _start_child()
                prev = _snapshot()
                continue
            else:
                crash_count = 0  # reset on successful run

            # Check for file changes
            curr = _snapshot()
            changed = []
            for path, mtime in curr.items():
                if path not in prev or prev[path] != mtime:
                    changed.append(Path(path).name)
            if changed:
                names = ", ".join(changed[:3])
                if len(changed) > 3:
                    names += f" +{len(changed)-3} more"
                print(f"  🔄 Detected change in {names} — reloading...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                _wait_for_port_free(host, port)
                proc = _start_child()
                prev = _snapshot()
            else:
                prev = curr
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


# ── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Alpaca Paper Trading Web Dashboard")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", 8888)),
                        help="Port to listen on (default: 8888, or $PORT env var)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--reload", action="store_true",
                        help="Auto-reload on file changes")
    args = parser.parse_args()

    # If --reload and not the child process, run the watcher
    if args.reload and not os.environ.get("_DASHBOARD_CHILD"):
        _run_with_reload(args.host, args.port)
    else:
        if not os.environ.get("_DASHBOARD_CHILD"):
            print(f"\n  📊 Alpaca Paper Trading Dashboard")
            print(f"  ─────────────────────────────────")
            print(f"  Local:  http://{args.host}:{args.port}")
            print(f"  Cache:  background refresh every 2s")
            print(f"  Tip:    Deploy to Render for a permanent public URL\n")

        from waitress import serve
        serve(app, host=args.host, port=args.port)
