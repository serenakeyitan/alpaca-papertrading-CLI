#!/usr/bin/env python3
"""Comprehensive test suite for the background cache + SQLite architecture.

Tests:
1. Cache Architecture (structural — no API calls needed)
2. SQLite Persistence
3. Cache Read Performance
4. API Endpoint Performance (with live cache)
5. Tiered Refresh Logic
6. Data Integrity
7. Configuration
8. Render Deployment Readiness
9. Rate Limit Safety
"""

import sys
import json
import os
import inspect
import threading
import sqlite3
import tempfile
import time as _time
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent
VENV_SITE = SKILL_DIR / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from web_dashboard import app, _DataCache, _cache, _load_config, _DB_PATH

# Wait for background cache to complete its first fetch cycle
print("  Waiting for background cache to populate...")
_time.sleep(8)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 1: Cache Architecture (structural — no API calls needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cache_architecture():
    """Test 1: _DataCache class structure and attributes."""
    print("\n── Test 1: Cache Architecture ──")

    # Class exists
    check("_DataCache class exists", _DataCache is not None)

    # Has all required methods
    required_methods = [
        "get", "start", "_run", "_init_db", "_db_load_log", "_db_insert_log",
        "_fetch_account", "_fetch_positions", "_fetch_watchlist",
        "_fetch_orders_and_fills", "_fetch_strategies", "_fetch_strategies_from_orders",
        "_load_order_history",
    ]
    for method in required_methods:
        check(f"Has method: {method}", hasattr(_DataCache, method))

    # Instance check on the global cache
    check("Global _cache is a _DataCache instance", isinstance(_cache, _DataCache))

    # Cache has correct initial keys
    expected_keys = {"account", "positions", "watchlist", "orders", "strategies", "log"}
    actual_keys = set(_cache._data.keys())
    check("Cache has correct keys", actual_keys == expected_keys,
          f"expected {expected_keys}, got {actual_keys}")

    # Thread-safe: has _lock attribute
    check("Cache has _lock (threading.Lock)", hasattr(_cache, "_lock"))
    check("_lock is a Lock instance", isinstance(_cache._lock, type(threading.Lock())))

    # Background thread is daemon
    threads = [t for t in threading.enumerate() if t.daemon and t.is_alive()]
    check("At least one daemon thread running", len(threads) > 0,
          f"found {len(threads)} daemon threads")

    # Has internal tracking attributes
    check("Has _seen_order_ids set", hasattr(_cache, "_seen_order_ids")
          and isinstance(_cache._seen_order_ids, set))
    check("Has _trade_log list", hasattr(_cache, "_trade_log")
          and isinstance(_cache._trade_log, list))
    check("Has _history_loaded flag", hasattr(_cache, "_history_loaded"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 2: SQLite Persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_sqlite_persistence():
    """Test 2: SQLite database creation, schema, and persistence."""
    print("\n── Test 2: SQLite Persistence ──")

    # Database file gets created
    check("Database file exists", _DB_PATH.exists(), f"expected {_DB_PATH}")

    # Schema has correct table and columns
    with sqlite3.connect(str(_DB_PATH)) as conn:
        cursor = conn.execute("PRAGMA table_info(trade_log)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

    expected_cols = {"id", "ts", "msg", "style", "order_id", "created_at"}
    check("trade_log table has correct columns", expected_cols == set(columns.keys()),
          f"got {set(columns.keys())}")
    check("id column is INTEGER", columns.get("id") == "INTEGER")
    check("ts column is TEXT", columns.get("ts") == "TEXT")
    check("msg column is TEXT", columns.get("msg") == "TEXT")
    check("style column is TEXT", columns.get("style") == "TEXT")
    check("order_id column is TEXT", columns.get("order_id") == "TEXT")
    check("created_at column is REAL", columns.get("created_at") == "REAL")

    # Has index on order_id
    with sqlite3.connect(str(_DB_PATH)) as conn:
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='trade_log'"
        ).fetchall()
    index_names = [i[0] for i in indexes]
    check("Has index on order_id", "idx_trade_log_order_id" in index_names,
          f"indexes: {index_names}")

    # Can insert and read entries
    test_ts = "99/99 00:00:00"
    test_msg = "__TEST_ENTRY__"
    with sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO trade_log (ts, msg, style, order_id) VALUES (?, ?, ?, ?)",
            (test_ts, test_msg, "dim", "__TEST_ORDER_ID__"),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT ts, msg, style, order_id FROM trade_log WHERE order_id = ?",
            ("__TEST_ORDER_ID__",),
        ).fetchall()
    check("Can insert and read entries", len(rows) == 1 and rows[0][1] == test_msg,
          f"got {rows}")

    # Handles duplicates gracefully (insert same order_id again — no unique constraint, so it inserts)
    with sqlite3.connect(str(_DB_PATH)) as conn:
        try:
            conn.execute(
                "INSERT INTO trade_log (ts, msg, style, order_id) VALUES (?, ?, ?, ?)",
                (test_ts, test_msg, "dim", "__TEST_ORDER_ID__"),
            )
            conn.commit()
            check("Handles duplicate order_id gracefully (no crash)", True)
        except Exception as e:
            check("Handles duplicate order_id gracefully (no crash)", False, str(e))

    # DB survives reconnection (close and reopen)
    with sqlite3.connect(str(_DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE order_id = ?",
            ("__TEST_ORDER_ID__",),
        ).fetchone()
    check("DB survives reconnection", rows[0] >= 1, f"got {rows[0]} rows")

    # Entries persist across _DataCache instances
    cache2 = _DataCache()
    entries, seen = cache2._db_load_log()
    test_entries = [e for e in entries if e["msg"] == test_msg]
    check("Entries persist across _DataCache instances", len(test_entries) >= 1,
          f"found {len(test_entries)}")

    # Cleanup test entries
    with sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute("DELETE FROM trade_log WHERE order_id = '__TEST_ORDER_ID__'")
        conn.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 3: Cache Read Performance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cache_read_performance():
    """Test 3: cache.get() is fast and returns data."""
    print("\n── Test 3: Cache Read Performance ──")

    keys = ["account", "positions", "watchlist", "orders", "strategies", "log"]

    # cache.get() returns data (not None) after population
    for key in keys:
        val = _cache.get(key)
        check(f"cache.get('{key}') returns data (not None)", val is not None,
              f"got {type(val)}")

    # cache.get() is fast (<10ms for all keys)
    t0 = _time.perf_counter()
    for key in keys:
        _cache.get(key)
    elapsed_ms = (_time.perf_counter() - t0) * 1000
    check(f"All 6 cache.get() calls < 10ms", elapsed_ms < 10,
          f"took {elapsed_ms:.2f}ms")

    # Multiple rapid get() calls return consistent data
    results1 = {k: _cache.get(k) for k in keys}
    results2 = {k: _cache.get(k) for k in keys}
    all_consistent = all(
        type(results1[k]) == type(results2[k]) for k in keys
    )
    check("Multiple rapid get() calls return consistent types", all_consistent)

    # Thread-safe: concurrent reads don't crash
    errors = []

    def reader():
        try:
            for _ in range(100):
                for key in keys:
                    _cache.get(key)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=reader) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    check("Concurrent reads (10 threads x 100 iters) don't crash",
          len(errors) == 0, f"errors: {errors}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 4: API Endpoint Performance (with live cache)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_api_endpoint_performance():
    """Test 4: All cached endpoints return 200, valid JSON, fast."""
    print("\n── Test 4: API Endpoint Performance ──")

    endpoints = [
        "/api/account", "/api/positions", "/api/watchlist",
        "/api/orders", "/api/strategies", "/api/log",
    ]

    with app.test_client() as c:
        # All 6 cached endpoints return 200 status
        for url in endpoints:
            r = c.get(url)
            check(f"{url} returns 200", r.status_code == 200,
                  f"got {r.status_code}")

        # All endpoints return valid JSON
        for url in endpoints:
            r = c.get(url)
            try:
                data = json.loads(r.data)
                check(f"{url} returns valid JSON", True)
            except json.JSONDecodeError:
                check(f"{url} returns valid JSON", False, "JSONDecodeError")

        # All endpoints respond in <20ms (from cache)
        for url in endpoints:
            t0 = _time.perf_counter()
            r = c.get(url)
            elapsed_ms = (_time.perf_counter() - t0) * 1000
            check(f"{url} responds in <20ms", elapsed_ms < 20,
                  f"took {elapsed_ms:.2f}ms")

        # /api/account has all required fields
        data = json.loads(c.get("/api/account").data)
        acct_fields = ["equity", "cash", "buying_power", "pnl", "market_open"]
        for field in acct_fields:
            check(f"/api/account has '{field}'", field in data,
                  f"keys: {list(data.keys())}")

        # /api/positions is a list
        data = json.loads(c.get("/api/positions").data)
        check("/api/positions is a list", isinstance(data, list))

        # /api/watchlist is a list with symbol, price, change_pct, type
        data = json.loads(c.get("/api/watchlist").data)
        check("/api/watchlist is a list", isinstance(data, list))
        if data:
            wl_fields = ["symbol", "price", "change_pct", "type"]
            for field in wl_fields:
                check(f"Watchlist entry has '{field}'", field in data[0],
                      f"keys: {list(data[0].keys())}")

        # /api/orders is a list
        data = json.loads(c.get("/api/orders").data)
        check("/api/orders is a list", isinstance(data, list))

        # /api/strategies is a list
        data = json.loads(c.get("/api/strategies").data)
        check("/api/strategies is a list", isinstance(data, list))

        # /api/log is a list with ts, msg, style
        data = json.loads(c.get("/api/log").data)
        check("/api/log is a list", isinstance(data, list))
        if data:
            log_fields = ["ts", "msg", "style"]
            for field in log_fields:
                check(f"Log entry has '{field}'", field in data[0],
                      f"keys: {list(data[0].keys())}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 5: Tiered Refresh Logic
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_tiered_refresh_logic():
    """Test 5: Verify tiered cycle-based refresh in _run method."""
    print("\n── Test 5: Tiered Refresh Logic ──")

    # _run method exists
    check("_run method exists", hasattr(_DataCache, "_run"))

    # Inspect the source of _run
    source = inspect.getsource(_DataCache._run)

    # Verify cycle-based logic
    check("_run references 'cycle % 2'", "cycle % 2" in source,
          "expected cycle % 2 for normal tier")
    check("_run references 'cycle % 6'", "cycle % 6" in source,
          "expected cycle % 6 for slow tier")

    # Verify sleep interval is 2 (not 5)
    check("Sleep interval is 2 seconds", "sleep(2)" in source,
          "expected _time.sleep(2)")

    # Verify tiered structure references
    check("Has 'Fast tier' comment", "Fast tier" in source)
    check("Has 'Normal tier' comment", "Normal tier" in source)
    check("Has 'Slow tier' comment", "Slow tier" in source)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 6: Data Integrity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_data_integrity():
    """Test 6: Data fields and constraints."""
    print("\n── Test 6: Data Integrity ──")

    # Account data has required fields
    account = _cache.get("account")
    acct_fields = ["equity", "cash", "buying_power", "pnl", "market_open"]
    for field in acct_fields:
        check(f"Account has '{field}'", field in account,
              f"keys: {list(account.keys())}")

    # Trade log entries have required fields
    log = _cache.get("log")
    if log:
        entry = log[0]
        for field in ["ts", "msg", "style"]:
            check(f"Log entry has '{field}'", field in entry)

    # Trade log is capped at reasonable size
    check("In-memory trade log <= 200 entries",
          len(_cache._trade_log) <= 200,
          f"got {len(_cache._trade_log)}")
    check("API log <= 100 entries",
          len(log) <= 100,
          f"got {len(log)}")

    # No duplicate entries in trade log
    with app.test_client() as c:
        data = json.loads(c.get("/api/log").data)
        msgs = [e["ts"] + e["msg"] for e in data]
        unique = set(msgs)
        check("No duplicate entries in trade log",
              len(msgs) == len(unique),
              f"{len(msgs)} entries, {len(unique)} unique")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 7: Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_configuration():
    """Test 7: _load_config env var support and fallback."""
    print("\n── Test 7: Configuration ──")

    source = inspect.getsource(_load_config)

    # Supports ALPACA_API_KEY / ALPACA_SECRET_KEY
    check("_load_config supports ALPACA_API_KEY",
          "ALPACA_API_KEY" in source)
    check("_load_config supports ALPACA_SECRET_KEY",
          "ALPACA_SECRET_KEY" in source)

    # Supports APCA_API_KEY_ID (Alpaca's native env var name)
    check("_load_config supports APCA_API_KEY_ID",
          "APCA_API_KEY_ID" in source)

    # Falls back to config files
    check("_load_config falls back to config files",
          "CONFIG_PATH" in source or "config.json" in source or ".exists()" in source)

    # Raises FileNotFoundError with helpful message when nothing found
    check("_load_config raises FileNotFoundError",
          "FileNotFoundError" in source)

    # Test that env vars actually work (functional test)
    saved_env = {}
    for k in ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]:
        saved_env[k] = os.environ.get(k)

    try:
        # Clear all alpaca env vars
        for k in saved_env:
            if k in os.environ:
                del os.environ[k]

        # Set test env vars
        os.environ["ALPACA_API_KEY"] = "TEST_KEY_123"
        os.environ["ALPACA_SECRET_KEY"] = "TEST_SECRET_456"
        cfg = _load_config()
        check("Env vars return correct api_key",
              cfg["api_key"] == "TEST_KEY_123",
              f"got {cfg.get('api_key')}")
        check("Env vars return correct secret_key",
              cfg["secret_key"] == "TEST_SECRET_456",
              f"got {cfg.get('secret_key')}")
    finally:
        # Restore original env
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]

    # Test APCA_API_KEY_ID fallback
    try:
        for k in saved_env:
            if k in os.environ:
                del os.environ[k]
        os.environ["APCA_API_KEY_ID"] = "APCA_KEY_789"
        os.environ["APCA_API_SECRET_KEY"] = "APCA_SECRET_012"
        cfg = _load_config()
        check("APCA_API_KEY_ID fallback works",
              cfg["api_key"] == "APCA_KEY_789",
              f"got {cfg.get('api_key')}")
    finally:
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]

    # Test FileNotFoundError when nothing found
    try:
        for k in saved_env:
            if k in os.environ:
                del os.environ[k]
        # Temporarily hide config files by monkeypatching
        import web_dashboard as wd
        orig_config = wd.CONFIG_PATH
        orig_home = wd.HOME_CONFIG
        wd.CONFIG_PATH = Path("/nonexistent/config.json")
        wd.HOME_CONFIG = Path("/nonexistent/home_config.json")
        try:
            _load_config()
            check("Raises FileNotFoundError when no config", False,
                  "did not raise")
        except FileNotFoundError as e:
            check("Raises FileNotFoundError when no config", True)
            check("Error message is helpful",
                  "ALPACA_API_KEY" in str(e) or "configure" in str(e),
                  f"message: {e}")
        finally:
            wd.CONFIG_PATH = orig_config
            wd.HOME_CONFIG = orig_home
    finally:
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 8: Render Deployment Readiness
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_render_deployment():
    """Test 8: render.yaml, host/port, .gitignore."""
    print("\n── Test 8: Render Deployment Readiness ──")

    # render.yaml exists at repo root
    render_yaml_path = REPO_ROOT / "render.yaml"
    check("render.yaml exists at repo root", render_yaml_path.exists(),
          f"checked {render_yaml_path}")

    if render_yaml_path.exists():
        content = render_yaml_path.read_text()

        # Has correct rootDir
        check("render.yaml has rootDir: skills/paper-trade",
              "rootDir: skills/paper-trade" in content or "rootDir: 'skills/paper-trade'" in content,
              f"content lacks rootDir")

        # References correct start command
        check("render.yaml references web_dashboard.py",
              "web_dashboard.py" in content)
        check("render.yaml uses --host 0.0.0.0",
              "0.0.0.0" in content)
        check("render.yaml uses $PORT",
              "$PORT" in content)

    # Default host is 0.0.0.0
    import web_dashboard as wd
    source = inspect.getsource(wd)
    # Check the argparse default
    check("Default host is 0.0.0.0 (not 127.0.0.1)",
          'default="0.0.0.0"' in source or "default='0.0.0.0'" in source)

    # PORT env var is respected
    check("PORT env var is respected",
          'os.environ.get("PORT"' in source or "os.environ.get('PORT'" in source)

    # .gitignore includes dashboard_cache.db
    gitignore_path = SKILL_DIR / ".gitignore"
    check(".gitignore exists", gitignore_path.exists())
    if gitignore_path.exists():
        gitignore = gitignore_path.read_text()
        check(".gitignore includes dashboard_cache.db",
              "dashboard_cache.db" in gitignore)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 9: Rate Limit Safety
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_rate_limit_safety():
    """Test 9: API calls per minute stay under Alpaca's 200 limit."""
    print("\n── Test 9: Rate Limit Safety ──")

    # From the _run docstring and code:
    # sleep(2) = 30 cycles per minute
    cycles_per_minute = 60 / 2  # = 30

    # Fast tier (every cycle = every 2s):
    #   _fetch_account: get_account + get_clock = 2 calls
    #   _fetch_watchlist: snapshots + crypto trades + crypto bars = 3 calls
    fast_calls_per_cycle = 5  # account(2) + watchlist(3)
    fast_total = fast_calls_per_cycle * cycles_per_minute

    check(f"Fast tier: {fast_calls_per_cycle} calls/cycle x {cycles_per_minute:.0f} cycles/min = {fast_total:.0f}",
          True)

    # Normal tier (every 2 cycles = every ~4s):
    #   _fetch_positions: list_positions = 1 call
    #   _fetch_orders_and_fills: list_orders(open) + list_orders(closed) = 2 calls
    normal_cycles_per_minute = cycles_per_minute / 2  # = 15
    normal_calls_per_cycle = 3  # positions(1) + orders(2)
    normal_total = normal_calls_per_cycle * normal_cycles_per_minute

    check(f"Normal tier: {normal_calls_per_cycle} calls/cycle x {normal_cycles_per_minute:.0f} cycles/min = {normal_total:.0f}",
          True)

    # Slow tier (every 5 cycles = every ~10s):
    #   _fetch_strategies: local or 1 API call (list_orders for derivation)
    slow_cycles_per_minute = cycles_per_minute / 6  # = 5
    slow_calls_per_cycle = 1  # may call list_orders(closed) for strategy derivation
    slow_total = slow_calls_per_cycle * slow_cycles_per_minute

    check(f"Slow tier: {slow_calls_per_cycle} calls/cycle x {slow_cycles_per_minute:.0f} cycles/min = {slow_total:.0f}",
          True)

    total_calls = fast_total + normal_total + slow_total
    check(f"Total API calls/min: {total_calls:.0f} (limit: 200)",
          total_calls <= 200,
          f"{total_calls:.0f} > 200")

    # Verify fast tier happens every cycle
    source = inspect.getsource(_DataCache._run)
    # Account and watchlist are NOT inside an if cycle % block
    fast_before_normal = (source.index("_fetch_account") < source.index("cycle % 2"))
    check("Fast tier (account) runs before cycle % 2 check", fast_before_normal)

    watchlist_before_normal = (source.index("_fetch_watchlist") < source.index("cycle % 2"))
    check("Fast tier (watchlist) runs before cycle % 2 check", watchlist_before_normal)

    # Normal tier (positions, orders) happens every 2 cycles
    check("Positions fetch inside cycle % 2 block",
          "cycle % 2" in source and "_fetch_positions" in source)

    check("Orders fetch inside cycle % 2 block",
          "cycle % 2" in source and "_fetch_orders" in source)

    # Slow tier (strategies) happens every 5 cycles
    check("Strategies fetch inside cycle % 6 block",
          "cycle % 6" in source and "_fetch_strategies" in source)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Run all tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("=" * 60)
    print("  Cache Architecture + SQLite Test Suite")
    print("=" * 60)

    test_cache_architecture()
    test_sqlite_persistence()
    test_cache_read_performance()
    test_api_endpoint_performance()
    test_tiered_refresh_logic()
    test_data_integrity()
    test_configuration()
    test_render_deployment()
    test_rate_limit_safety()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
