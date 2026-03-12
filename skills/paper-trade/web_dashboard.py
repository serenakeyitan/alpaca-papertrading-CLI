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

# ── In-memory trade log ─────────────────────────────────────
_trade_log = []
_seen_order_ids = set()
_history_loaded = False


def _load_config():
    for p in (CONFIG_PATH, HOME_CONFIG):
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError("No Alpaca config found. Run: alpaca configure init")


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


def _log_entry(msg, style="dim"):
    ts = datetime.now().strftime("%m/%d %H:%M:%S")
    _trade_log.append({"ts": ts, "msg": msg, "style": style})
    if len(_trade_log) > 200:
        _trade_log.pop(0)
    # Also persist to file
    try:
        with open(TRADE_LOG_PATH, "a") as f:
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass


def _get_strategy_manager():
    try:
        from strategy_manager import StrategyManager
        return StrategyManager()
    except Exception:
        return None


# ── API endpoints ──────────────────────────────────────────

@app.route("/api/account")
def api_account():
    try:
        api = _get_api()
        acct = api.get_account()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity)
        pnl = equity - last_equity
        pnl_pct = (pnl / last_equity * 100) if last_equity else 0
        clock = api.get_clock()

        # Strategy summary
        strat_pnl = 0
        strat_deployed = 0
        strat_allocated = 0
        strat_active = 0
        strat_total = 0
        sm = _get_strategy_manager()
        if sm:
            try:
                summary = sm.account_summary()
                strat_pnl = summary.get("total_pnl", 0)
                strat_deployed = summary.get("total_used", 0)
                strat_allocated = summary.get("total_allocated", 0)
                strat_active = summary.get("active_count", 0)
                strat_total = summary.get("total_strategies", 0)
            except Exception:
                pass

        return jsonify({
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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions")
def api_positions():
    try:
        api = _get_api()
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
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchlist")
def api_watchlist():
    try:
        symbols = _load_watchlist()
        stocks = [s for s in symbols if "/" not in s]
        cryptos = [s for s in symbols if "/" in s]
        result = []

        cfg = _load_config()
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
                for sym in cryptos:
                    norm = sym.replace("/", "")
                    price = 0
                    if "trades" in trades and sym in trades["trades"]:
                        price = trades["trades"][sym].get("p", 0)
                    elif "trades" in trades and norm in trades["trades"]:
                        price = trades["trades"][norm].get("p", 0)
                    result.append({
                        "symbol": sym, "price": price,
                        "change_pct": 0, "type": "crypto",
                    })
            except Exception:
                pass

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders")
def api_orders():
    global _seen_order_ids
    try:
        api = _get_api()
        orders = api.list_orders(status="open", limit=50)
        result = []
        current_ids = set()
        for o in orders:
            current_ids.add(o.id)
            # Extract strategy name from client_order_id
            strategy = "manual"
            if o.client_order_id:
                coid = str(o.client_order_id)
                for prefix in ("grid_", "dca_", "momentum_", "mean_reversion_", "dip_buyer_"):
                    if coid.startswith(prefix):
                        parts = coid.split("_", 2)
                        strategy = f"{parts[0]}-{parts[1]}" if len(parts) > 1 else parts[0]
                        break

            submitted = str(o.submitted_at)
            try:
                dt = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
                time_str = dt.strftime("%m/%d %H:%M")
            except Exception:
                time_str = submitted[:16]

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
        if _seen_order_ids:
            new_ids = current_ids - _seen_order_ids
            for o in result:
                if o["id"] in new_ids:
                    side_txt = o["side"].upper()
                    price_txt = f"@ ${o['limit_price']:.2f}" if o["limit_price"] else "MKT"
                    _log_entry(
                        f"NEW {side_txt} {o['symbol']} x{o['qty']:.0f} {price_txt} {o['type']} [{o['strategy']}]",
                        "new"
                    )
        _seen_order_ids = current_ids

        # Also check recent filled orders for the log
        try:
            filled = api.list_orders(status="closed", limit=20)
            for o in filled:
                if o.status == "filled" and o.id not in _seen_order_ids:
                    _seen_order_ids.add(o.id)
                    if o.filled_at:
                        side_txt = o.side.upper()
                        price = float(o.filled_avg_price) if o.filled_avg_price else 0
                        _log_entry(
                            f"FILL {side_txt} {o.symbol} x{float(o.qty):.0f} @ ${price:.2f}",
                            "fill-buy" if o.side == "buy" else "fill-sell"
                        )
        except Exception:
            pass

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/strategies")
def api_strategies():
    try:
        sm = _get_strategy_manager()
        if not sm:
            return jsonify([])
        strategies = sm.list_strategies()
        result = []
        for s in strategies:
            last_tick = ""
            if s.get("last_tick"):
                try:
                    dt = datetime.fromisoformat(str(s["last_tick"]))
                    last_tick = dt.strftime("%H:%M:%S")
                except Exception:
                    last_tick = "---"

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
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/log")
def api_log():
    global _history_loaded
    if not _history_loaded:
        _history_loaded = True
        _load_order_history()
    return jsonify(_trade_log[-100:])


def _load_order_history():
    """Load recent filled orders from Alpaca into the trade log on first request."""
    import re
    try:
        api = _get_api()
        orders = api.list_orders(status="all", limit=200)
        fills = [o for o in orders if o.status == "filled"]
        # Sort oldest first
        fills.sort(key=lambda o: str(o.filled_at or o.submitted_at or ""))

        for o in fills:
            _seen_order_ids.add(o.id)
            ts_obj = o.filled_at or o.submitted_at
            if ts_obj:
                try:
                    if hasattr(ts_obj, 'strftime'):
                        ts = ts_obj.strftime("%m/%d %H:%M:%S")
                    else:
                        ts = str(ts_obj)[:19]
                except Exception:
                    ts = str(ts_obj)[:19]
            else:
                ts = "---"

            side_txt = o.side.upper()
            qty = float(o.qty) if o.qty else 0
            price = float(o.filled_avg_price) if o.filled_avg_price else 0
            sym = o.symbol

            # Extract strategy tag
            cid = o.client_order_id or ""
            strat_tag = ""
            m = re.match(r'^(grid|dca|momentum|mean_reversion|dip_buyer|momentum_scalper)_([^_]+)_', cid)
            if m:
                strat_tag = f" [{m.group(2)}]"

            style = "fill-buy" if o.side == "buy" else "fill-sell"
            qty_fmt = f"{qty:.6f}".rstrip("0").rstrip(".") if qty % 1 else f"{qty:.0f}"
            msg = f"FILL {side_txt} {sym} x{qty_fmt} @ ${price:,.2f}{strat_tag}"
            _trade_log.append({"ts": ts, "msg": msg, "style": style})

        if fills:
            _log_entry(f"Loaded {len(fills)} historical fills from Alpaca", "info")
    except Exception as e:
        _log_entry(f"Error loading history: {e}", "dim")


@app.route("/api/bars/<symbol>")
def api_bars(symbol):
    try:
        api = _get_api()
        end = datetime.now()
        start = end - timedelta(days=30)
        bars = api.get_bars(
            symbol, tradeapi.TimeFrame.Day,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            limit=30, feed="iex",
        ).df
        result = []
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
    --bg: #000000;
    --dark-bg: #0c0c0c;
    --panel-bg: #000000;
    --header-bg: #111111;
    --border: #1a2332;
    --text: #c8d6e5;
    --dim: #576a7e;
    --white: #ffffff;
    --green: #00d4aa;
    --red: #ff6b6b;
    --yellow: #f0c040;
    --cyan: cyan;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    background: var(--bg); color: var(--text);
    font-size: 13px; line-height: 1.3;
    overflow: hidden; height: 100vh;
    display: flex; flex-direction: column;
  }

  /* ── Title Bar — matches: background #00d4aa, color #000, height 1 line ── */
  #title-bar {
    height: 24px; display: flex; align-items: center;
    padding: 0 8px; background: var(--green); color: #000000;
    font-weight: 700; font-size: 13px;
    flex-shrink: 0; white-space: nowrap; overflow: hidden;
  }
  #title-bar .sep { margin: 0 6px; opacity: 0.4; }

  /* ── Account Bar — matches: background #0c0c0c, height 1 line ── */
  #account-bar {
    height: 24px; display: flex; align-items: center;
    padding: 0 8px; background: var(--dark-bg);
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

  /* ── Pane title — matches: bg #111111, color #00d4aa, bold ── */
  .pane-title {
    height: 22px; padding: 0 8px; font-size: 13px; font-weight: 700;
    color: var(--green); background: var(--header-bg);
    display: flex; align-items: center; flex-shrink: 0;
    border-bottom: 1px solid var(--border);
  }

  /* ── Tables ── */
  .tbl-wrap { flex: 1; overflow-y: auto; overflow-x: hidden; }
  table { width: 100%; border-collapse: collapse; }
  /* Header — matches DataTable header: bg #111111, color #00d4aa, bold */
  th {
    position: sticky; top: 0; z-index: 1;
    padding: 2px 8px; text-align: left;
    font-size: 13px; font-weight: 700;
    color: var(--green); background: var(--header-bg);
    border-bottom: 1px solid var(--border);
  }
  th.r, td.r { text-align: right; }
  td {
    padding: 2px 8px;
    white-space: nowrap; font-size: 13px;
  }
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
    flex: 1; overflow-y: auto; padding: 0 8px; font-size: 13px;
  }
  .log-entry { line-height: 1.4; }
  .log-ts { color: var(--dim); margin-right: 8px; }
  .log-fill-buy { color: var(--green); font-weight: 700; }
  .log-fill-sell { color: var(--red); font-weight: 700; }
  .log-new { color: var(--yellow); }
  .log-cancel { color: var(--dim); }
  .log-strat { color: var(--green); }
  .log-info { color: var(--cyan); }

  /* ── Status Line — matches: bg #111111, color #576a7e, height 1 line ── */
  #status-line {
    height: 22px; display: flex; align-items: center;
    padding: 0 8px; background: var(--header-bg);
    color: var(--dim); font-size: 13px;
    flex-shrink: 0;
    white-space: nowrap; overflow: hidden;
  }
  #status-line .sep { margin: 0 6px; }

  /* ── Empty state ── */
  .empty { padding: 8px; color: var(--dim); font-size: 13px; }

  /* ── Scrollbar — matches: scrollbar-color #1a2332 on #000 ── */
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
  <span id="ab-status" style="color:var(--green);margin-left:auto;font-weight:700"></span>
</div>

<div class="main">
  <!-- Row 1: Watchlist | Positions -->
  <div id="tables-row">

    <div id="watchlist-pane">
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>&nbsp;#</th><th>MARKET</th><th class="r">Price</th><th class="r">Chg</th><th>Trend</th></tr></thead>
          <tbody id="watchlist-body"></tbody>
        </table>
      </div>
    </div>

    <div id="positions-pane">
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>POSITIONS</th><th class="r">Qty</th><th class="r">Price</th><th class="r">P&amp;L</th><th class="r">P&amp;L%</th></tr></thead>
          <tbody id="positions-body"></tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Row 2: Strategies | Open Orders -->
  <div id="strat-area">

    <div id="strat-left">
      <div class="pane-title">&nbsp;STRATEGIES</div>
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

    <div id="strat-right">
      <div class="pane-title">&nbsp;OPEN ORDERS</div>
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
  <div id="log-area">
    <div class="pane-title">&nbsp;TRADING LOG</div>
    <div id="log-body">
      <div class="log-entry"><span class="log-ts">--/-- --:--:--</span><span class="log-info">Terminal started — loading recent orders...</span></div>
    </div>
  </div>
</div>

<!-- Status Line: " q Quit  r Refresh  / Command  │  strat add <type> <name> <symbol>  │  strat pause/resume/remove <name>  │  buy/sell SYMBOL [QTY]  │  tick #N" -->
<div id="status-line">
  <span>q Quit&nbsp;&nbsp;r Refresh&nbsp;&nbsp;/ Command</span>
  <span class="sep">│</span>
  <span>strat add &lt;type&gt; &lt;name&gt; &lt;symbol&gt;</span>
  <span class="sep">│</span>
  <span>strat pause/resume/remove &lt;name&gt;</span>
  <span class="sep">│</span>
  <span>buy/sell SYMBOL [QTY]</span>
  <span class="sep">│</span>
  <span id="tick-count">tick #0</span>
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
  $('title-strat').textContent = `Strategies ${d.strat_active}/${d.strat_total}`;

  $('title-market').textContent = d.market_open ? 'OPEN' : 'CLOSED';
}

// ── Watchlist — columns: #, MARKET, Price, Chg, Trend ──
async function refreshWatchlist() {
  const data = await fetchJSON('/api/watchlist');
  if (data.error || !Array.isArray(data)) return;

  for (const item of data) {
    if (!barCache[item.symbol] && item.type === 'stock') {
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
    const [statusTxt, sCls] = statusMap[s.status] || ['?', 'dim'];
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
  if (data.error || !Array.isArray(data) || !data.length) return;
  const body = $('log-body');
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
}

tick();
setInterval(tick, 5000);
setInterval(() => { Object.keys(barCache).forEach(k => delete barCache[k]); }, 60000);
</script>
</body>
</html>
"""

# ── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Alpaca Paper Trading Web Dashboard")
    parser.add_argument("--port", type=int, default=8888, help="Port to listen on (default: 8888)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"\n  📊 Alpaca Paper Trading Dashboard")
    print(f"  ─────────────────────────────────")
    print(f"  Local:  http://{args.host}:{args.port}")
    print(f"  Tip:    Run 'bash scripts/start-web.sh' for auto-tunnel\n")

    from waitress import serve
    serve(app, host=args.host, port=args.port)
