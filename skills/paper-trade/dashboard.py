#!/usr/bin/env python3
"""OpenClaw Live Trading Terminal — multi-strategy real-time dashboard."""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from collections import deque

# Force truecolor support for bright greens/reds
os.environ.setdefault("COLORTERM", "truecolor")

VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    sys.path.insert(0, str(p))

SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import alpaca_trade_api as tradeapi
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Static, Input, DataTable, RichLog
from textual.binding import Binding
from textual import work
from rich.text import Text


from strategy_manager import StrategyManager

CONFIG_PATH = Path(__file__).parent / "config.json"
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
TRADE_LOG_PATH = Path(__file__).parent / "trade_log.txt"
RELOAD_FLAG = Path(__file__).parent / ".reload"

DEFAULT_WATCHLIST = ["NVDA", "AAPL", "SPY", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "QQQ"]

SPARK_BLOCKS = "▁▂▃▄▅▆▇█"

def spark_trend(bars, width=10):
    """Render close prices as a single-line trend sparkline.

    Green segments = price going up, red = going down.
    Returns a Rich Text fitting in one DataTable cell.
    """
    if not bars:
        return Text("  ···  ", style="dim")
    closes = [b["close"] for b in bars[-width:]]
    n = len(closes)
    if n != width:
        step = max(n / width, 1)
        closes = [closes[min(int(i * step), n - 1)] for i in range(width)]
    lo, hi = min(closes), max(closes)
    rng = hi - lo if hi != lo else 1
    result = Text()
    for i, v in enumerate(closes):
        idx = min(int((v - lo) / rng * 7), 7)
        color = "#00d4aa" if i == 0 or v >= closes[i - 1] else "#ff6b6b"
        result.append(SPARK_BLOCKS[idx], style=color)
    return result

# ── Helpers ───────────────────────────────────────────────

def get_api():
    cfg = json.loads(CONFIG_PATH.read_text())
    return tradeapi.REST(
        cfg["api_key"], cfg["secret_key"],
        base_url="https://paper-api.alpaca.markets", api_version="v2"
    )

def load_watchlist():
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text())
    return list(DEFAULT_WATCHLIST)

def save_watchlist(syms):
    WATCHLIST_PATH.write_text(json.dumps(syms, indent=2))

def fmt(v):
    v = float(v)
    if abs(v) >= 1e6: return f"${v/1e6:,.1f}M"
    if abs(v) >= 1e5: return f"${v/1e3:,.1f}K"
    return f"${v:,.2f}"

def fmt_pct(v):
    return f"{float(v)*100:+.2f}%"

def fmt_option_symbol(sym):
    """Parse OCC option symbol like QQQ260331P00450000 into 'QQQ $450P 3/31'."""
    m = re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$', sym)
    if not m:
        return sym
    underlying, yy, mm, dd, cp, strike_raw = m.groups()
    strike = int(strike_raw) / 1000
    strike_str = f"${strike:g}"
    return f"{underlying} {strike_str}{cp} {int(mm)}/{int(dd)}"

def delta_arrow(v):
    v = float(v)
    if v > 0.001: return "▲"
    if v < -0.001: return "▼"
    return "─"

STATUS_STYLES = {
    "active": ("● ACTIVE", "#00d4aa"),
    "pending": ("◌ PENDING", "#f0c040"),
    "initializing": ("◎ INIT", "#f0c040"),
    "paused": ("|| PAUSED", "#576a7e"),
    "stopped": ("■ STOPPED", "#576a7e"),
    "error": ("X ERROR", "#ff6b6b"),
}

# ── Intent Parser ────────────────────────────────────────

# Symbol extraction: 1-5 uppercase alpha chars, or preceded by "of"/"on"/"for"
_SYM_RE = r'(?:of|on|for)?\s*\$?([A-Za-z]{1,5})\b'
# Quantity: bare number, or "N shares", or "$N worth"
_QTY_NUM = r'(\d+(?:\.\d+)?)'
_QTY_SHARES = r'(\d+(?:\.\d+)?)\s*(?:shares?|units?|contracts?|lots?)'
_QTY_DOLLAR = r'\$\s*(\d+(?:\.\d+)?)\s*(?:worth|of)?'

# Stop words that are not symbols
_STOP_WORDS = {
    "buy", "sell", "close", "cancel", "watch", "add", "remove", "drop",
    "get", "grab", "pick", "long", "short", "all", "my", "the", "some",
    "put", "market", "limit", "order", "orders", "position", "positions",
    "portfolio", "strat", "strategy", "pause", "resume", "stop", "start",
    "run", "grid", "dca", "momentum", "mean", "reversion", "from", "to",
    "of", "on", "for", "in", "at", "with", "and", "shares", "share",
    "stock", "stocks", "worth", "up", "set", "show", "list", "refresh",
    "tick", "quit", "exit", "watchlist", "capital", "every", "min",
    "minutes", "sec", "seconds", "new", "create", "delete", "back",
    "purchase", "acquire", "dump", "offload", "unload", "liquidate",
    "flatten", "out", "everything", "please", "now", "it", "this",
    "that", "just", "also", "lets", "let", "can", "you", "i", "me",
    "nvidia", "apple", "tesla", "google", "amazon", "microsoft", "meta",
}

# Common name -> ticker mapping
_TICKER_ALIASES = {
    "nvidia": "NVDA", "apple": "AAPL", "tesla": "TSLA", "google": "GOOGL",
    "alphabet": "GOOGL", "amazon": "AMZN", "microsoft": "MSFT", "meta": "META",
    "facebook": "META", "netflix": "NFLX", "amd": "AMD", "intel": "INTC",
    "spy": "SPY", "qqq": "QQQ", "arkk": "ARKK", "coinbase": "COIN",
    "palantir": "PLTR", "disney": "DIS", "uber": "UBER", "snap": "SNAP",
    "shopify": "SHOP", "roku": "ROKU", "square": "SQ", "block": "SQ",
    "paypal": "PYPL", "boeing": "BA", "jpmorgan": "JPM", "goldman": "GS",
    "berkshire": "BRK.B", "visa": "V", "mastercard": "MA",
}

def _extract_symbol(text):
    """Extract a ticker symbol from natural language text."""
    words = text.lower().split()
    # First check for crypto pairs like BTC/USD, ETH/USD
    for word in text.split():
        clean = word.strip("$,.!?")
        if "/" in clean and len(clean) <= 10:
            parts = clean.split("/")
            if all(p.isalpha() for p in parts):
                return clean.upper()
    # Then check for company name aliases
    for word in words:
        if word in _TICKER_ALIASES:
            return _TICKER_ALIASES[word]
    # Then look for uppercase tickers in original text
    for word in text.split():
        clean = word.strip("$,.!?")
        if clean.isalpha() and 2 <= len(clean) <= 8 and clean.upper() == clean and clean.lower() not in _STOP_WORDS:
            return clean.upper()
    # Then look for any word that could be a ticker (not a stop word)
    for word in words:
        clean = word.strip("$,.!?")
        if clean.isalpha() and 2 <= len(clean) <= 8 and clean not in _STOP_WORDS:
            return clean.upper()
    return None

def _extract_quantity(text):
    """Extract quantity from text. Returns (qty, is_dollar_amount)."""
    # Dollar amount: "$500 of", "$500 worth"
    m = re.search(r'\$\s*(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1)), True
    # "N shares" / "N units"
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:shares?|units?|lots?)', text, re.I)
    if m:
        return float(m.group(1)), False
    # Bare number (not part of a ticker)
    tokens = text.split()
    for t in tokens:
        t = t.strip("$,")
        if re.match(r'^\d+(\.\d+)?$', t):
            return float(t), False
    return None, False

def _extract_strategy_name(text, known_names=None):
    """Extract a strategy name from text."""
    if known_names:
        for name in known_names:
            if name.lower() in text.lower():
                return name
    # Look for quoted names
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # Look for a hyphenated word (common strategy name pattern like "my-grid")
    m = re.search(r'\b([a-z][\w-]*-[\w-]+)\b', text, re.I)
    if m and m.group(1).lower() not in _STOP_WORDS:
        return m.group(1)
    return None

def parse_intent(cmd, known_strategy_names=None):
    """
    Parse a natural language command into an intent dict.
    Returns: {"action": str, "symbol": str|None, "qty": float|None,
              "dollar_amt": float|None, "strategy_name": str|None,
              "strategy_type": str|None, "capital": float|None,
              "raw_args": list, "raw": str}
    """
    raw = cmd.strip()
    # Strip leading / (the focus key often gets typed into the command)
    if raw.startswith("/"):
        raw = raw[1:].strip()
    lower = raw.lower()
    words = lower.split()

    result = {
        "action": None, "symbol": None, "qty": None, "dollar_amt": None,
        "strategy_name": None, "strategy_type": None, "capital": None,
        "raw_args": raw.split()[1:] if raw.split() else [],
        "raw": raw,
    }

    # ── Quit / Refresh ──
    if lower in ("q", "quit", "exit", "bye", "done"):
        result["action"] = "quit"
        return result
    if lower in ("r", "refresh", "update", "reload"):
        result["action"] = "refresh"
        return result
    if lower in ("tick", "run tick", "run strategies", "tick all"):
        result["action"] = "tick"
        return result

    # ── Auto-tick ──
    if re.match(r'^auto\b', lower):
        result["action"] = "auto"
        # Parse "auto off", "auto on", "auto 5", "auto on 5"
        m = re.search(r'\b(on|off|start|stop)\b', lower)
        if m:
            result["strategy_name"] = m.group(1)  # reuse field for on/off
        m = re.search(r'(\d+)', lower)
        if m:
            result["qty"] = float(m.group(1))  # reuse field for interval
        return result

    # ── Buy intent ──
    buy_pat = r'\b(buy|purchase|acquire|get|grab|pick\s*up|go\s*long|long)\b'
    if re.search(buy_pat, lower):
        result["action"] = "buy"
        result["symbol"] = _extract_symbol(raw)
        qty, is_dollar = _extract_quantity(raw)
        if is_dollar:
            result["dollar_amt"] = qty
        else:
            result["qty"] = qty
        return result

    # ── Sell intent ──
    sell_pat = r'\b(sell|dump|offload|unload|short|go\s*short)\b'
    if re.search(sell_pat, lower):
        result["action"] = "sell"
        result["symbol"] = _extract_symbol(raw)
        qty, is_dollar = _extract_quantity(raw)
        if is_dollar:
            result["dollar_amt"] = qty
        else:
            result["qty"] = qty
        return result

    # ── Close intent ──
    close_pat = r'\b(close|liquidate|flatten|exit\s*position|close\s*out)\b'
    if re.search(close_pat, lower):
        result["action"] = "close"
        if re.search(r'\b(all|everything|every)\b', lower):
            result["symbol"] = "ALL"
        else:
            result["symbol"] = _extract_symbol(raw)
        return result

    # ── Cancel intent ──
    cancel_pat = r'\b(cancel|revoke|kill|scratch)\b'
    if re.search(cancel_pat, lower):
        result["action"] = "cancel"
        if re.search(r'\b(all|everything|every)\b', lower):
            result["symbol"] = "ALL"
        else:
            # Look for order ID (hex-like or uuid-like)
            m = re.search(r'([0-9a-f]{8,})', lower)
            if m:
                result["strategy_name"] = m.group(1)  # reuse field for order_id
            else:
                result["symbol"] = _extract_symbol(raw)
        return result

    # ── Watch intent ──
    watch_add = r'\b(watch|track|monitor|follow)\b|add\b.*\bwatch'
    watch_rm = r'\b(unwatch|untrack|stop\s*watch)\b|remove\b.*\bwatch|drop\b.*\bwatch'
    if re.search(watch_rm, lower):
        result["action"] = "unwatch"
        result["symbol"] = _extract_symbol(raw)
        return result
    if re.search(watch_add, lower):
        result["action"] = "watch"
        result["symbol"] = _extract_symbol(raw)
        return result

    # ── Strategy intents ──
    strat_add = r'\b(create|add|new|set\s*up|launch|deploy|start)\s*(a\s+)?(strategy|strat|grid|dca|momentum|mean.?rev|dip.?buy|long.?only)'
    strat_rm = r'\b(remove|delete|destroy|kill)\s*(strategy|strat)'
    strat_pause = r'\b(pause|halt|freeze|disable)\s*(strategy|strat)?'
    strat_resume = r'\b(resume|unpause|enable|restart|reactivate)\s*(strategy|strat)?'
    strat_stop = r'\b(stop)\s*(strategy|strat|all\s*strat)'
    strat_list = r'\b(list|show|display)\s*(strateg\w*|strats?)\b'

    if re.search(strat_add, lower):
        result["action"] = "strat_add"
        # Detect type
        for stype in ("grid", "dca", "momentum", "mean_reversion", "mean reversion", "dip_buyer", "dip buyer", "dip", "long_only", "long only"):
            if stype in lower:
                result["strategy_type"] = stype.replace(" ", "_")
                break
        result["strategy_name"] = _extract_strategy_name(raw, known_strategy_names)
        result["symbol"] = _extract_symbol(raw)
        # Capital
        m = re.search(r'(?:capital|budget|with)\s*\$?\s*(\d+(?:\.\d+)?)', lower)
        if m:
            result["capital"] = float(m.group(1))
        return result

    if re.search(strat_rm, lower):
        result["action"] = "strat_remove"
        result["strategy_name"] = _extract_strategy_name(raw, known_strategy_names)
        return result

    if re.search(strat_pause, lower):
        result["action"] = "strat_pause"
        result["strategy_name"] = _extract_strategy_name(raw, known_strategy_names)
        return result

    if re.search(strat_resume, lower):
        result["action"] = "strat_resume"
        result["strategy_name"] = _extract_strategy_name(raw, known_strategy_names)
        return result

    if re.search(strat_stop, lower):
        result["action"] = "strat_pause"
        result["strategy_name"] = _extract_strategy_name(raw, known_strategy_names)
        return result

    if re.search(strat_list, lower):
        result["action"] = "strat_list"
        return result

    # ── Show/display intents ──
    if re.search(r'\b(show|display|list)\s*(positions?|portfolio|holdings?)\b', lower):
        result["action"] = "refresh"
        return result
    if re.search(r'\b(show|display|list)\s*(orders?)\b', lower):
        result["action"] = "refresh"
        return result

    # ── Fallback: try first word as legacy command ──
    if words:
        first = words[0]
        if first in ("buy", "sell", "close", "cancel", "watch", "strat", "tick"):
            result["action"] = first
            result["symbol"] = _extract_symbol(" ".join(words[1:])) if len(words) > 1 else None
            qty, is_dollar = _extract_quantity(raw)
            if is_dollar:
                result["dollar_amt"] = qty
            else:
                result["qty"] = qty
            return result

    return result  # action=None means unrecognized

# ── CSS ───────────────────────────────────────────────────

CSS = """
Screen { background: #000000; color: #c8d6e5; scrollbar-size: 0 0; }
* { scrollbar-color: #1a2332; scrollbar-background: #000000; }

#title-bar {
    dock: top; height: 1;
    background: #00d4aa; color: #000000; text-style: bold;
    padding: 0 1;
}
#account-bar { height: 1; background: #0c0c0c; padding: 0 1; }

#tables-row { height: 9; }
#watchlist-pane { width: 2fr; background: #000000; border-right: solid #1a2332; }
#positions-pane { width: 3fr; background: #000000; }

#strat-area { height: 4; }
#strat-left { width: 2fr; background: #000000; border-right: solid #1a2332; }
#strat-right { width: 1fr; background: #000000; }

#log-area { height: 1fr; min-height: 4; }
#trades-pane { width: 1fr; background: #000000; }

.pane-title {
    height: 1; padding: 0 1;
    background: #111111; color: #00d4aa; text-style: bold;
}

DataTable { height: 1fr; background: #000000; scrollbar-size: 0 1; scrollbar-color: #1a2332; scrollbar-background: #000000; }
DataTable > .datatable--header { background: #111111; color: #00d4aa; text-style: bold; }
DataTable:focus { border: none; }

RichLog { height: 1fr; background: #000000; padding: 0 1; scrollbar-size: 0 1; scrollbar-color: #1a2332; scrollbar-background: #000000; }

#command-bar { dock: bottom; height: 2; background: #0c0c0c; padding: 0; }
#cmd-input { background: #111111; color: #c8d6e5; border: none; }

#status-line { dock: bottom; height: 1; background: #111111; color: #576a7e; padding: 0 1; }
"""

# ── App ───────────────────────────────────────────────────

class TradingTerminal(App):
    CSS = CSS
    TITLE = "OpenClaw Terminal"
    DARK = True

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("slash", "focus_cmd", "/Cmd", show=True),
        Binding("escape", "unfocus_cmd", "Esc", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.api = get_api()
        self.sm = StrategyManager()
        self.watchlist = load_watchlist()
        self.price_history = {}
        self.prev_prices = {}      # last known price (cache/fallback)
        self.last_order_ids = set()
        self.tick_count = 0
        self.mini_bars = {}   # symbol -> list of {open,close,high,low} for sparklines
        self._shutting_down = False
        self._market_open = False
        self.auto_tick = True
        self.auto_tick_interval = 10  # seconds
        self._tick_running = False
        self._last_auto_tick = None

    def compose(self) -> ComposeResult:
        yield Static("", id="title-bar")
        yield Static("", id="account-bar")

        with Horizontal(id="tables-row"):
            with Vertical(id="watchlist-pane"):
                yield DataTable(id="watch-table")
            with Vertical(id="positions-pane"):
                yield DataTable(id="pos-table")

        with Horizontal(id="strat-area"):
            with Vertical(id="strat-left"):
                yield Static(" STRATEGIES", classes="pane-title")
                yield DataTable(id="strat-table")
            with Vertical(id="strat-right"):
                yield Static(" OPEN ORDERS", classes="pane-title")
                yield DataTable(id="order-table")

        with Vertical(id="log-area"):
            yield Static(" TRADING LOG", classes="pane-title")
            yield RichLog(id="trade-log", wrap=False, markup=True)

        yield Static("", id="status-line")
        with Container(id="command-bar"):
            yield Input(
                placeholder=" Press / to type  |  buy/sell NVDA 10  |  watch apple  |  /quit to exit",
                id="cmd-input"
            )

    def on_mount(self):
        # Disable mouse tracking — prevents escape sequence leaks in split terminals
        import sys
        sys.stdout.write("\033[?1000l\033[?1003l\033[?1006l\033[?1015l")
        sys.stdout.flush()

        # Watchlist columns — no cursor, pure monitor
        wt = self.query_one("#watch-table", DataTable)
        wt.cursor_type = "none"
        wt.add_columns(" #", "MARKET", "Price", "Chg", "Trend")

        # Positions columns
        pt = self.query_one("#pos-table", DataTable)
        pt.cursor_type = "none"
        pt.add_columns("POSITIONS", "Qty", "Price", "P&L", "P&L%")

        # Strategy columns
        st = self.query_one("#strat-table", DataTable)
        st.cursor_type = "none"
        st.add_columns("Name", "Type", "Status", "Capital", "Used", "Real P&L", "Unrl P&L", "Total P&L", "Fills", "Last Tick")

        # Orders columns
        ot = self.query_one("#order-table", DataTable)
        ot.cursor_type = "none"
        ot.add_columns("Time", "Side", "Symbol", "Qty", "Type", "Limit", "Status", "Strategy")

        self._log(f"[dim]{datetime.now().strftime('%m/%d %H:%M:%S')}[/]  Terminal started — loading recent orders...")
        self.refresh_all()
        self._load_history()

        self.set_interval(2, self.refresh_prices)
        self.set_interval(5, self.refresh_account)
        self.set_interval(5, self.refresh_positions)
        self.set_interval(5, self.poll_orders)
        self.set_interval(10, self.refresh_strategies)
        self.set_interval(3, self.update_clock)
        self.set_interval(30, self.refresh_chart)
        self.set_interval(1, self._auto_tick_check)

    def _auto_tick_check(self):
        # Check for reload flag (touched after edits)
        if RELOAD_FLAG.exists():
            try:
                RELOAD_FLAG.unlink()
            except Exception:
                pass
            self._shutting_down = True
            self.workers.cancel_all()
            # Force exit with code 42 — wrapper will restart us
            import os
            os._exit(42)
            return
        if not self.auto_tick or self._shutting_down or self._tick_running:
            return
        now = datetime.now()
        if self._last_auto_tick and (now - self._last_auto_tick).total_seconds() < self.auto_tick_interval:
            return
        self._last_auto_tick = now
        self._tick_running = True
        self._run_auto_tick()

    @work(thread=True)
    def _run_auto_tick(self):
        try:
            self.sm.tick_all(self.api)
            self.app.call_from_thread(self.refresh_all)
        except Exception as e:
            ts = datetime.now().strftime("%m/%d %H:%M:%S")
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [red]Auto-tick error: {e}[/]")
        finally:
            self._tick_running = False

    def update_clock(self):
        if self._shutting_down: return
        now = datetime.now().strftime("%H:%M:%S")
        dot = "●" if self.tick_count % 2 == 0 else "○"
        try:
            clock = self.api.get_clock()
            self._market_open = clock.is_open
            mkt = "[green]OPEN[/]" if clock.is_open else "[red]CLOSED[/]"
        except Exception:
            mkt = "?"
        active = sum(1 for s in self.sm.strategies.values() if s.status == "active")
        total = len(self.sm.strategies)
        auto = f"  │  [green]AUTO {self.auto_tick_interval}s[/]" if self.auto_tick else ""
        self.query_one("#title-bar", Static).update(
            f" OPENCLAW TERMINAL  │  {now} {dot}  │  Stock Market {mkt}  │  "
            f"Strategies {active}/{total}{auto}  │  Press [bold]/[/] command"
        )
        self.query_one("#status-line", Static).update(
            f" q Quit  r Refresh  / Command  │  "
            f"strat add <type> <name> <symbol>  │  strat pause/resume/remove <name>  │  "
            f"buy/sell SYMBOL [QTY]  │  tick #{self.tick_count}"
        )
        self.tick_count += 1

    # ── Data fetching ─────────────────────────────────────

    @work(thread=True)
    def _load_history(self):
        """Load recent fills from API into the trading log on startup."""
        self._load_recent_orders()

    @work(thread=True)
    def refresh_all(self):
        if self._shutting_down: return
        self._fetch_account()
        self._fetch_prices()
        self._fetch_positions()
        self._fetch_orders()
        self._fetch_strategies()

    @work(thread=True)
    def refresh_prices(self):
        if self._shutting_down: return
        self._fetch_prices()

    @work(thread=True)
    def refresh_account(self):
        if self._shutting_down: return
        self._fetch_account()

    @work(thread=True)
    def refresh_positions(self):
        if self._shutting_down: return
        self._fetch_positions()

    @work(thread=True)
    @work(thread=True)
    def poll_orders(self):
        if self._shutting_down: return
        self._poll_new_fills()
        self._fetch_orders()

    @work(thread=True)
    def refresh_strategies(self):
        if self._shutting_down: return
        self._fetch_strategies()

    def _fetch_account(self):
        try:
            a = self.api.get_account()
            eq = float(a.equity)
            cash = float(a.cash)
            bp = float(a.buying_power)
            last_eq = float(a.last_equity)
            pnl = eq - last_eq
            pnl_pct = (pnl / last_eq * 100) if last_eq > 0 else 0

            # Strategy summary
            summary = self.sm.get_summary()

            self.app.call_from_thread(
                self._render_account, eq, cash, bp, pnl, pnl_pct, a.status, summary
            )
        except Exception:
            pass

    def _render_account(self, eq, cash, bp, pnl, pnl_pct, status, summary):
        c = "#00d4aa" if pnl >= 0 else "#ff6b6b"
        s = "+" if pnl >= 0 else ""
        arr = delta_arrow(pnl)

        strat_pnl = summary["total_pnl"]
        sc = "#00d4aa" if strat_pnl >= 0 else "#ff6b6b"
        ss = "+" if strat_pnl >= 0 else ""

        self.query_one("#account-bar", Static).update(
            f" [bold white]EQUITY[/] [bold]{fmt(eq)}[/]  "
            f"[dim]CASH[/] {fmt(cash)}  "
            f"[dim]BP[/] {fmt(bp)}  "
            f"[dim]DAY[/] [{c}]{arr}{s}{fmt(pnl)} ({s}{pnl_pct:.2f}%)[/]  "
            f"[dim]STRAT[/] [{sc}]{ss}{fmt(strat_pnl)}[/]  "
            f"[dim]DEPLOYED[/] {fmt(summary['total_used'])}/{fmt(summary['total_allocated'])}  "
            f"[green]{status}[/]"
        )

    def _fetch_prices(self):
        import requests
        is_crypto = lambda s: "/" in s or s in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD")

        if not hasattr(self, '_api_headers'):
            cfg = json.loads(CONFIG_PATH.read_text())
            self._api_headers = {"APCA-API-KEY-ID": cfg["api_key"], "APCA-API-SECRET-KEY": cfg["secret_key"]}
        headers = self._api_headers

        prices = {}      # sym -> latest price
        day_chg = {}     # sym -> daily % change

        # 1) Stock snapshots — gives latest price + previous close for real daily change
        stock_syms = [s for s in self.watchlist if not is_crypto(s)]
        if stock_syms:
            try:
                url = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(stock_syms)}&feed=iex"
                r = requests.get(url, headers=headers, timeout=10)
                data = r.json()
                for sym, snap in data.items():
                    prices[sym] = float(snap["latestTrade"]["p"])
                    prev_close = float(snap["prevDailyBar"]["c"])
                    if prev_close > 0:
                        day_chg[sym] = (prices[sym] - prev_close) / prev_close
            except Exception:
                pass

        # 2) Position data — only use for crypto and symbols not in snapshot
        try:
            for p in self.api.list_positions():
                sym = p.symbol
                # Don't overwrite stock snapshot prices (IEX is more accurate for display)
                if sym not in prices:
                    prices[sym] = float(p.current_price)
                if sym not in day_chg and p.change_today is not None:
                    day_chg[sym] = float(p.change_today)
                # Map crypto positions (BTCUSD -> BTC/USD)
                if sym in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD"):
                    wsym = f"{sym[:3]}/{sym[3:]}"
                    if wsym not in prices:
                        prices[wsym] = float(p.current_price)
                    if wsym not in day_chg and p.change_today is not None:
                        day_chg[wsym] = float(p.change_today)
        except Exception:
            pass

        # 3) Crypto live prices (freshest)
        crypto_syms = [s for s in self.watchlist if is_crypto(s)]
        if crypto_syms:
            try:
                csyms = [s if "/" in s else f"{s[:3]}/{s[3:]}" for s in crypto_syms]
                url = f"https://data.alpaca.markets/v1beta3/crypto/us/latest/trades?symbols={','.join(csyms)}"
                r = requests.get(url, headers=headers, timeout=5)
                data = r.json()
                for sym in crypto_syms:
                    csym = sym if "/" in sym else f"{sym[:3]}/{sym[3:]}"
                    if csym in data.get("trades", {}):
                        prices[sym] = float(data["trades"][csym]["p"])
            except Exception:
                pass

        # 4) Build rows with real daily change
        rows = []
        for i, sym in enumerate(self.watchlist):
            price = prices.get(sym)

            if price is None:
                price = self.prev_prices.get(sym)
            if price is None:
                rows.append((i+1, sym, None, 0, 0, None, None, []))
                continue

            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=30)
            self.price_history[sym].append(price)

            # Use real daily % change from API, not fake session-start change
            chg = day_chg.get(sym, 0)
            abs_chg = price * chg  # approximate $ change

            self.prev_prices[sym] = price

            rows.append((i+1, sym, price, chg, abs_chg, None, None, list(self.price_history[sym])))

        self.app.call_from_thread(self._render_prices, rows)

    def _render_prices(self, rows):
        wt = self.query_one("#watch-table", DataTable)
        # Build new row data first
        new_rows = []
        for idx, sym, price, chg, abs_chg, bid, ask, hist in rows:
            trend = spark_trend(self.mini_bars.get(sym, []))
            if price is None:
                new_rows.append((Text(str(idx), style="dim"), Text(sym, style="bold"),
                           *[Text("---", style="dim")]*2, trend))
                continue
            if chg > 0.0001: ps, cs = "bold #00d4aa", "#00d4aa"
            elif chg < -0.0001: ps, cs = "bold #ff6b6b", "#ff6b6b"
            else: ps, cs = "bold white", "dim"

            arr = delta_arrow(chg)
            s = "+" if abs_chg >= 0 else ""
            # Show $ change for large prices (crypto), % for stocks
            if abs(price) >= 1000:
                chg_text = f"{arr}{s}${abs_chg:,.0f}"
            else:
                chg_text = f"{arr}{chg*100:+.2f}%"

            new_rows.append((
                Text(f"  {idx}", style="dim"),
                Text(sym, style="bold white"),
                Text(fmt(price), style=ps),
                Text(chg_text, style=cs),
                trend,
            ))
        # Swap in one go — minimal blank time
        wt.clear()
        for r in new_rows:
            wt.add_row(*r)
        try:
            wt.move_cursor(row=0, column=0)
        except Exception:
            pass

    # ── Bars fetch (for sparklines) ─────────────────────────

    @work(thread=True)
    def refresh_chart(self):
        if self._shutting_down: return
        self._fetch_bars()

    def _fetch_bars(self):
        try:
            from datetime import timedelta
            end = datetime.now()
            start = end - timedelta(days=30)

            pos_syms = set()
            try:
                for p in self.api.list_positions():
                    if p.asset_class == "us_equity":
                        pos_syms.add(p.symbol)
            except Exception:
                pass
            all_syms = []
            for s in set(self.watchlist) | pos_syms | set(self.mini_bars.keys()):
                # Only equity symbols for bars API (skip crypto with "/" and options)
                if s.isalpha() and 1 <= len(s) <= 5:
                    all_syms.append(s)
            if not all_syms:
                return

            bars_df = self.api.get_bars(
                all_syms,
                tradeapi.TimeFrame.Day,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                limit=30 * len(all_syms),
                feed='iex',
            ).df
            if bars_df.empty:
                return

            mini = {}
            for sym in all_syms:
                try:
                    if "symbol" in bars_df.columns:
                        sym_df = bars_df[bars_df["symbol"] == sym]
                    else:
                        sym_df = bars_df
                    if sym_df.empty:
                        continue
                    ohlc = []
                    for _, r in sym_df.iterrows():
                        ohlc.append({
                            "open": float(r["open"]),
                            "close": float(r["close"]),
                            "high": float(r["high"]),
                            "low": float(r["low"]),
                        })
                    mini[sym] = ohlc[-14:]
                except Exception:
                    pass

            self.mini_bars = mini
            self.app.call_from_thread(self.refresh_prices)
            self.app.call_from_thread(self.refresh_positions)
        except Exception:
            pass

    def _fetch_positions(self):
        try:
            positions = self.api.list_positions()
            seen_syms = set()
            rows = []
            for p in positions:
                sym = p.symbol
                seen_syms.add(sym)

                price = float(p.current_price)
                entry = float(p.avg_entry_price)
                qty = float(p.qty)

                # Override with live crypto price from our cache
                is_crypto = "/" in sym or sym in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD")
                if is_crypto:
                    for ws in self.watchlist:
                        ws_flat = ws.replace("/", "")
                        if ws_flat == sym and ws in self.prev_prices:
                            price = self.prev_prices[ws]
                            break

                value = qty * price
                pnl = (price - entry) * qty
                pnl_pct = (price - entry) / entry if entry else 0

                rows.append({
                    "symbol": sym,
                    "qty": qty,
                    "entry": entry,
                    "price": price,
                    "value": value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })

            # Include strategy symbols not in current positions (e.g. scalper between trades)
            for s in self.sm.strategies.values():
                if s.status not in ("active", "paused"):
                    continue
                sp = s.get_positions()
                strat_sym = sp.get("symbol", "")
                pos_sym = strat_sym.replace("/", "")
                if pos_sym and pos_sym not in seen_syms:
                    seen_syms.add(pos_sym)
                    price = self.prev_prices.get(strat_sym, 0)
                    rows.append({
                        "symbol": pos_sym,
                        "qty": 0,
                        "entry": 0,
                        "price": price,
                        "value": 0,
                        "pnl": s.realized_pnl,
                        "pnl_pct": 0,
                    })

            self.app.call_from_thread(self._render_positions, rows)
        except Exception:
            pass

    def _render_positions(self, rows):
        pt = self.query_one("#pos-table", DataTable)
        if not rows:
            pt.clear()
            pt.add_row(Text("No positions", style="dim"), *[Text("")]*4)
            return

        new_rows = []
        total_val = total_pnl = 0
        for p in rows:
            pnl = p["pnl"]
            pnl_pct = p["pnl_pct"] * 100
            total_val += p["value"]
            total_pnl += pnl
            c = "#00d4aa" if pnl >= 0 else "#ff6b6b"
            s = "+" if pnl >= 0 else ""
            a = delta_arrow(pnl)
            display_sym = fmt_option_symbol(p["symbol"])
            new_rows.append((
                Text(display_sym, style="bold white"),
                Text(f"{p['qty']:g}"),
                Text(fmt(p["price"]), style="bold white"),
                Text(f"{a}{s}{fmt(pnl)}", style=c),
                Text(f"{s}{pnl_pct:.2f}%", style=c),
            ))
        tc = "#00d4aa" if total_pnl >= 0 else "#ff6b6b"
        ts = "+" if total_pnl >= 0 else ""
        new_rows.append((
            Text("TOTAL", style="bold"), Text(""),
            Text(fmt(total_val), style="bold white"),
            Text(f"{ts}{fmt(total_pnl)}", style=f"bold {tc}"),
            Text(""),
        ))
        pt.clear()
        for r in new_rows:
            pt.add_row(*r)
        pt.scroll_home()

    def _fetch_strategies(self):
        # Reload from disk in case bot updated it
        old_statuses = {n: s.status for n, s in self.sm.strategies.items()}
        self.sm = StrategyManager()
        summary = self.sm.get_summary()
        # Log status changes
        for s in summary["strategies"]:
            old = old_statuses.get(s["name"])
            if old and old != s["status"]:
                ts = datetime.now().strftime("%m/%d %H:%M:%S")
                status_text, sc = STATUS_STYLES.get(s["status"], (s["status"], "white"))
                self.app.call_from_thread(
                    self._log,
                    f"[dim]{ts}[/]  [{sc}]STRAT[/] [bold]{s['name']}[/] {old} → {status_text}"
                )
        self.app.call_from_thread(self._render_strategies, summary["strategies"])

    def _render_strategies(self, strategies):
        st = self.query_one("#strat-table", DataTable)
        st.clear()
        if not strategies:
            st.add_row(Text("No strategies. Use main terminal to add — they will show up here.", style="dim"),
                        *[Text("")]*9)
            return

        for s in strategies:
            status_text, status_color = STATUS_STYLES.get(s["status"], (s["status"], "white"))
            pnl = s["total_pnl"]
            pc = "#00d4aa" if pnl >= 0 else "#ff6b6b"
            ps = "+" if pnl >= 0 else ""
            rpnl = s["realized_pnl"]
            rc = "#00d4aa" if rpnl >= 0 else "#ff6b6b"
            rs = "+" if rpnl >= 0 else ""
            upnl = s["unrealized_pnl"]
            uc = "#00d4aa" if upnl >= 0 else "#ff6b6b"
            us = "+" if upnl >= 0 else ""

            last_tick = s["last_tick"]
            if last_tick:
                try:
                    lt_dt = datetime.fromisoformat(last_tick)
                    if lt_dt.tzinfo is not None:
                        lt_dt = lt_dt.astimezone()
                    lt = lt_dt.strftime("%H:%M:%S")
                except Exception:
                    lt = last_tick[:8]
            else:
                lt = "---"

            err = f" ({s['error_msg'][:20]})" if s["error_msg"] and s["status"] == "error" else ""

            st.add_row(
                Text(s["name"], style="bold white"),
                Text(s["type"], style="cyan"),
                Text(status_text + err, style=status_color),
                Text(fmt(s.get("capital_used", 0) + s.get("realized_pnl", 0)), style="white"),
                Text(fmt(s.get("capital_used", 0)), style="dim"),
                Text(f"{rs}{fmt(rpnl)}", style=rc),
                Text(f"{us}{fmt(upnl)}", style=uc),
                Text(f"{ps}{fmt(pnl)}", style=f"bold {pc}"),
                Text(str(s["total_fills"]), style="white"),
                Text(lt, style="dim"),
            )

    def _fetch_orders(self):
        try:
            orders = self.api.list_orders(status="open", limit=50)
            rows = []
            for o in orders:
                # Detect strategy from client_order_id
                strat = "manual"
                cid = o.client_order_id or ""
                for s in self.sm.strategies.values():
                    prefix = f"{s.type}_{s.name}_"
                    if cid.startswith(prefix):
                        strat = s.name
                        break

                rows.append({
                    "time": o.submitted_at.astimezone().strftime("%m/%d %H:%M") if o.submitted_at else "---",
                    "side": o.side,
                    "symbol": o.symbol,
                    "qty": str(o.qty or "---"),
                    "type": o.type,
                    "limit": fmt(o.limit_price) if o.limit_price else "mkt",
                    "status": o.status,
                    "strategy": strat,
                })
            self.app.call_from_thread(self._render_orders, rows)
        except Exception:
            pass

    def _render_orders(self, rows):
        ot = self.query_one("#order-table", DataTable)
        ot.clear()
        if not rows:
            ot.add_row(Text("No open orders", style="dim"), *[Text("")]*7)
            return
        for o in rows:
            sc = "#00d4aa" if o["side"] == "buy" else "#ff6b6b"
            ot.add_row(
                Text(o["time"], style="dim"),
                Text(o["side"].upper(), style=f"bold {sc}"),
                Text(o["symbol"], style="bold white"),
                Text(o["qty"]),
                Text(o["type"], style="dim"),
                Text(o["limit"]),
                Text(o["status"], style="#f0c040" if o["status"] in ("new","accepted") else "dim"),
                Text(o["strategy"], style="cyan" if o["strategy"] != "manual" else "dim"),
            )

    def _format_order_log(self, o):
        """Format a single order into a log line (with markup)."""
        order_time = o.filled_at or o.updated_at or o.submitted_at
        if order_time:
            try:
                # pandas Timestamp needs .tz_convert, stdlib uses .astimezone
                if hasattr(order_time, 'tz_convert'):
                    order_time = order_time.tz_convert(None).to_pydatetime()
                    from datetime import timezone as tz
                    order_time = order_time.replace(tzinfo=tz.utc).astimezone()
                elif order_time.tzinfo is not None:
                    order_time = order_time.astimezone()
                ts = order_time.strftime("%m/%d %H:%M:%S")
            except Exception:
                ts = str(order_time)[:19]
        else:
            ts = datetime.now().strftime("%m/%d %H:%M:%S")

        cid = o.client_order_id or ""
        strat = ""
        for s in self.sm.strategies.values():
            if cid.startswith(f"{s.type}_{s.name}_"):
                strat = f" [cyan][{s.name}][/]"
                break

        if o.status == "filled":
            side = o.side.upper()
            c = "#00d4aa" if side == "BUY" else "#ff6b6b"
            price = fmt(o.filled_avg_price) if o.filled_avg_price else "mkt"
            return (f"[dim]{ts}[/]  [bold {c}]FILL {side}[/]  "
                    f"[bold white]{o.symbol}[/] x{o.filled_qty or o.qty or '?'} @ {price}{strat}")
        elif o.status in ("accepted", "new"):
            side = o.side.upper()
            c = "#00d4aa" if side == "BUY" else "#ff6b6b"
            lim = fmt(o.limit_price) if o.limit_price else "mkt"
            return (f"[dim]{ts}[/]  [#f0c040]NEW[/]  [{c}]{side}[/] "
                    f"[bold]{o.symbol}[/] x{o.qty or '?'} @ {lim} {o.type}{strat}")
        elif o.status == "canceled":
            return f"[dim]{ts}[/]  [dim]CANCEL {o.symbol} {o.side} x{o.qty or '?'}[/]{strat}"
        return None

    def _load_recent_orders(self):
        """Load recent filled orders into the log on startup."""
        try:
            orders = self.api.list_orders(status="all", limit=100)
            self.last_order_ids = {o.id for o in orders}

            fills = [o for o in orders if o.status == "filled"]
            # Sort by filled_at timestamp (handle pandas Timestamp)
            fills.sort(key=lambda o: str(o.filled_at or o.submitted_at or ""))
            for o in fills[-30:]:
                try:
                    line = self._format_order_log(o)
                    if line:
                        self.app.call_from_thread(self._log, line)
                except Exception as e:
                    self.app.call_from_thread(
                        self._log, f"[red]Log error: {e}[/]"
                    )
            count = len(fills)
            self.app.call_from_thread(
                self._log,
                f"[dim]{datetime.now().strftime('%m/%d %H:%M:%S')}[/]  "
                f"Loaded {min(count, 30)} of {count} recent fills"
            )
        except Exception as e:
            self.app.call_from_thread(
                self._log, f"[red]Failed to load orders: {e}[/]"
            )

    def _poll_new_fills(self):
        try:
            orders = self.api.list_orders(status="all", limit=50)
            current_ids = {o.id for o in orders}
            new_ids = current_ids - self.last_order_ids

            # Sort new orders oldest-first
            new_orders = sorted(
                [o for o in orders if o.id in new_ids],
                key=lambda o: o.filled_at or o.updated_at or o.submitted_at or ""
            )

            for o in new_orders:
                line = self._format_order_log(o)
                if line:
                    self.app.call_from_thread(self._log, line)

            self.last_order_ids = current_ids
        except Exception:
            pass

    def _log(self, msg):
        self.query_one("#trade-log", RichLog).write(msg)
        # Persist to file (strip markup for plain text log)
        try:
            import re as _re
            plain = _re.sub(r'\[/?[^\]]*\]', '', str(msg))
            with open(TRADE_LOG_PATH, "a") as f:
                f.write(plain.strip() + "\n")
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────

    def action_quit(self):
        self._shutting_down = True
        self.workers.cancel_all()
        import os, signal
        os.kill(os.getpid(), signal.SIGTERM)

    def action_refresh(self):
        self._log(f"[dim]{datetime.now().strftime('%m/%d %H:%M:%S')}[/]  [cyan]Refreshing...[/]")
        self.refresh_all()

    def action_focus_cmd(self):
        self.query_one("#cmd-input", Input).focus()

    def action_unfocus_cmd(self):
        self.query_one("#cmd-input", Input).value = ""
        self.screen.focus_next()

    def on_input_submitted(self, event: Input.Submitted):
        cmd = event.value.strip()
        event.input.value = ""
        self.screen.focus_next()
        if not cmd:
            return

        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        known_strats = list(self.sm.strategies.keys()) if hasattr(self, 'sm') else []
        intent = parse_intent(cmd, known_strats)
        action = intent["action"]

        try:
            if action == "quit":
                self._shutting_down = True
                self.workers.cancel_all()
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
            elif action == "refresh":
                self.action_refresh()
            elif action == "tick":
                self._do_tick(ts)
            elif action == "auto":
                self._do_auto(intent, ts)
            elif action == "buy":
                self._intent_buy(intent, ts)
            elif action == "sell":
                self._intent_sell(intent, ts)
            elif action == "close":
                self._intent_close(intent, ts)
            elif action == "cancel":
                self._intent_cancel(intent, ts)
            elif action == "watch":
                self._intent_watch(intent, ts, add=True)
            elif action == "unwatch":
                self._intent_watch(intent, ts, add=False)
            elif action == "strat_add":
                self._intent_strat_add(intent, ts)
            elif action == "strat_remove":
                self._intent_strat_action(intent, ts, "remove")
            elif action == "strat_pause":
                self._intent_strat_action(intent, ts, "pause")
            elif action == "strat_resume":
                self._intent_strat_action(intent, ts, "resume")
            elif action == "strat_list":
                self._do_strat(["list"], ts)
            elif action == "strat":
                # Legacy fallback for "strat add grid ..."
                self._do_strat(cmd.split()[1:], ts)
            elif action is None:
                self._log(f"[dim]{ts}[/]  [red]Unknown: {cmd}[/]")
            else:
                self._log(f"[dim]{ts}[/]  [red]Unknown: {cmd}[/]")
        except Exception as e:
            self._log(f"[dim]{ts}[/]  [red]Error: {e}[/]")

    # ── Intent handlers ──────────────────────────────────

    def _intent_buy(self, intent, ts):
        sym = intent["symbol"]
        if not sym:
            self._log(f"[dim]{ts}[/]  [yellow]What do you want to buy? e.g. \"buy 10 NVDA\" or \"buy $500 of apple\"[/]")
            return
        if intent["dollar_amt"]:
            # Dollar-based buy: fetch price, compute qty
            self._dollar_buy_async(sym, intent["dollar_amt"], ts)
        else:
            qty = intent["qty"] or 1
            self._log(f"[dim]{ts}[/]  [#00d4aa]> BUY[/] [bold]{sym}[/] x{qty}")
            self._submit_async({"symbol": sym, "qty": qty, "side": "buy", "type": "market", "time_in_force": "day"}, ts)

    @work(thread=True)
    def _dollar_buy_async(self, sym, amount, ts):
        try:
            quote = self.api.get_latest_quote(sym)
            price = float(quote.ap) if quote.ap else float(quote.bp)
            qty = int(amount / price)
            if qty < 1:
                self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [red]${amount} not enough for 1 share of {sym} @ ${price:.2f}[/]")
                return
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [#00d4aa]> BUY[/] [bold]{sym}[/] x{qty} (~${amount:.0f} @ ${price:.2f})")
            order = self.api.submit_order(symbol=sym, qty=qty, side="buy", type="market", time_in_force="day")
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [#00d4aa]OK BUY[/] {order.symbol} | [dim]{order.id[:8]}[/]")
            self.app.call_from_thread(self.refresh_all)
        except Exception as e:
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [red]ERR {e}[/]")

    def _intent_sell(self, intent, ts):
        sym = intent["symbol"]
        if not sym:
            self._log(f"[dim]{ts}[/]  [yellow]What do you want to sell? e.g. \"sell TSLA\" or \"sell 5 shares of nvidia\"[/]")
            return
        args = [sym]
        if intent["qty"]:
            args.append(str(intent["qty"]))
        self._do_sell(args, ts)

    def _intent_close(self, intent, ts):
        sym = intent["symbol"]
        if not sym:
            self._log(f"[dim]{ts}[/]  [yellow]Close what? e.g. \"close NVDA\" or \"close all positions\"[/]")
            return
        self._do_close(["all" if sym == "ALL" else sym], ts)

    def _intent_cancel(self, intent, ts):
        if intent["symbol"] == "ALL":
            self._do_cancel(["all"], ts)
        elif intent["strategy_name"]:
            # Order ID was stored in strategy_name field
            self._do_cancel([intent["strategy_name"]], ts)
        else:
            self._log(f"[dim]{ts}[/]  [yellow]Cancel what? e.g. \"cancel all\" or \"cancel ORDER_ID\"[/]")

    def _intent_watch(self, intent, ts, add=True):
        sym = intent["symbol"]
        if not sym:
            self._log(f"[dim]{ts}[/]  [yellow]Which symbol? e.g. \"watch nvidia\" or \"remove TSLA from watchlist\"[/]")
            return
        prefix = "+" if add else "-"
        self._do_watch([f"{prefix}{sym}"], ts)

    def _intent_strat_add(self, intent, ts):
        stype = intent["strategy_type"]
        name = intent["strategy_name"]
        sym = intent["symbol"]
        if not stype:
            self._log(f"[dim]{ts}[/]  [yellow]What type? e.g. \"create a grid strategy on NVDA\" (grid/dca/momentum/mean_reversion)[/]")
            return
        if not sym:
            self._log(f"[dim]{ts}[/]  [yellow]Which symbol? e.g. \"add grid strategy my-grid on NVDA\"[/]")
            return
        if not name:
            name = f"{stype}-{sym.lower()}"
        capital = intent["capital"] or 10000
        args = ["add", stype, name, sym]
        if intent["capital"]:
            args.append(str(int(capital)))
        self._do_strat(args, ts)

    def _intent_strat_action(self, intent, ts, action):
        name = intent["strategy_name"]
        if not name:
            names = list(self.sm.strategies.keys())
            if names:
                self._log(f"[dim]{ts}[/]  [yellow]Which strategy? Known: {', '.join(names)}[/]")
            else:
                self._log(f"[dim]{ts}[/]  [yellow]No strategies found[/]")
            return
        self._do_strat([action, name], ts)

    # ── Strategy commands ─────────────────────────────────

    def _do_strat(self, args, ts):
        if not args:
            self._log(f"[dim]{ts}[/]  [yellow]strat add <type> <name> <symbol> [capital]  │  "
                       f"strat remove/pause/resume <name>[/]")
            return

        sub = args[0].lower()

        if sub == "add" and len(args) >= 4:
            stype = args[1]
            name = args[2]
            symbol = args[3].upper()
            capital = float(args[4]) if len(args) > 4 else 10000

            # Build config based on strategy type
            if stype == "grid":
                config = {"symbol": symbol, "grid_pct": 6, "num_grids": 10, "qty_per_grid": 2}
            elif stype == "dca":
                interval = int(args[5]) if len(args) > 5 else 30
                config = {"symbol": symbol, "amount_per_buy": 500, "interval_minutes": interval}
            elif stype == "momentum":
                syms = [s.upper() for s in args[3:] if not s.replace('.','').isdigit()]
                config = {"symbols": syms or [symbol], "lookback_minutes": 60,
                          "top_n": 3, "amount_per_position": 3000, "rebalance_minutes": 60}
                capital = float(args[-1]) if args[-1].replace('.','').isdigit() else 10000
            elif stype == "mean_reversion":
                config = {"symbol": symbol, "window": 20, "threshold_pct": 2.0, "qty": 5}
            elif stype in ("dip_buyer", "dip", "long_only"):
                stype = "dip_buyer"
                config = {"symbol": symbol, "window": 20, "dip_pct": 1.0,
                          "buy_amount": 100, "max_buys": 10, "cooldown_seconds": 60}
            else:
                self._log(f"[dim]{ts}[/]  [red]Unknown type: {stype}. Use: grid, dca, momentum, mean_reversion, dip_buyer[/]")
                return

            self.sm.add_strategy(stype, name, config, capital)
            self._log(f"[dim]{ts}[/]  [#00d4aa]+ Strategy added:[/] [bold]{name}[/] ({stype}) on {symbol} capital={fmt(capital)}")
            self.refresh_strategies()

        elif sub == "remove" and len(args) >= 2:
            name = args[1]
            self.sm.remove_strategy(name, self.api)
            self._log(f"[dim]{ts}[/]  [#ff6b6b]- Strategy removed:[/] {name}")
            self.refresh_strategies()

        elif sub == "pause" and len(args) >= 2:
            self.sm.pause_strategy(args[1])
            self._log(f"[dim]{ts}[/]  [yellow]|| Paused:[/] {args[1]}")
            self.refresh_strategies()

        elif sub == "resume" and len(args) >= 2:
            self.sm.resume_strategy(args[1])
            self._log(f"[dim]{ts}[/]  [#00d4aa]▶ Resumed:[/] {args[1]}")
            self.refresh_strategies()

        elif sub == "list":
            for s in self.sm.list_strategies():
                status_text, _ = STATUS_STYLES.get(s["status"], (s["status"], ""))
                self._log(f"  [bold]{s['name']}[/] [{s['type']}] {status_text} "
                          f"fills={s['total_fills']} pnl={fmt(s['total_pnl'])}")

        else:
            self._log(f"[dim]{ts}[/]  [yellow]Usage: strat add|remove|pause|resume|list[/]")

    def _do_tick(self, ts):
        """Manually trigger one tick cycle for all strategies."""
        self._log(f"[dim]{ts}[/]  [cyan]Running strategy tick...[/]")
        self._run_tick_async(ts)

    @work(thread=True)
    def _run_tick_async(self, ts):
        try:
            self.sm.tick_all(self.api)
            self.app.call_from_thread(
                self._log,
                f"[dim]{ts}[/]  [#00d4aa]Tick complete[/] — "
                f"{sum(1 for s in self.sm.strategies.values() if s.status=='active')} active strategies"
            )
            self.app.call_from_thread(self.refresh_all)
        except Exception as e:
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [red]Tick error: {e}[/]")

    def _do_auto(self, intent, ts):
        """Toggle auto-tick on/off, optionally set interval."""
        toggle = intent.get("strategy_name")  # "on"/"off" stored here
        interval = intent.get("qty")  # interval seconds stored here

        if interval and interval >= 1:
            self.auto_tick_interval = int(interval)

        if toggle in ("off", "stop"):
            self.auto_tick = False
            self._log(f"[dim]{ts}[/]  [yellow]Auto-tick OFF[/]")
        elif toggle in ("on", "start"):
            self.auto_tick = True
            self._log(f"[dim]{ts}[/]  [green]Auto-tick ON[/] every {self.auto_tick_interval}s")
        elif not toggle and not interval:
            # Toggle
            self.auto_tick = not self.auto_tick
            state = f"[green]ON[/] every {self.auto_tick_interval}s" if self.auto_tick else "[yellow]OFF[/]"
            self._log(f"[dim]{ts}[/]  Auto-tick {state}")
        else:
            # Just changed interval
            self.auto_tick = True
            self._log(f"[dim]{ts}[/]  [green]Auto-tick ON[/] every {self.auto_tick_interval}s")

    # ── Trade commands ────────────────────────────────────

    def _do_buy(self, args, ts):
        if not args:
            self._log(f"[dim]{ts}[/]  [yellow]buy SYMBOL [QTY][/]")
            return
        sym = args[0].upper()
        qty = float(args[1]) if len(args) > 1 and args[1].replace('.','').isdigit() else 1
        self._log(f"[dim]{ts}[/]  [#00d4aa]> BUY[/] [bold]{sym}[/] x{qty}")
        self._submit_async({"symbol": sym, "qty": qty, "side": "buy", "type": "market", "time_in_force": "day"}, ts)

    def _do_sell(self, args, ts):
        if not args:
            self._log(f"[dim]{ts}[/]  [yellow]sell SYMBOL [QTY][/]")
            return
        sym = args[0].upper()
        params = {"symbol": sym, "side": "sell", "type": "market", "time_in_force": "day"}
        if len(args) > 1 and args[1].replace('.','').isdigit():
            params["qty"] = float(args[1])
        else:
            try:
                pos = self.api.get_position(sym)
                params["qty"] = float(pos.qty)
            except Exception:
                self._log(f"[dim]{ts}[/]  [red]No position in {sym}[/]")
                return
        self._log(f"[dim]{ts}[/]  [#ff6b6b]> SELL[/] [bold]{sym}[/] x{params['qty']}")
        self._submit_async(params, ts)

    @work(thread=True)
    def _submit_async(self, params, ts):
        try:
            order = self.api.submit_order(**params)
            c = "#00d4aa" if params["side"] == "buy" else "#ff6b6b"
            self.app.call_from_thread(
                self._log,
                f"[dim]{ts}[/]  [{c}]OK {params['side'].upper()}[/] {order.symbol} | [dim]{order.id[:8]}[/]"
            )
            self.app.call_from_thread(self.refresh_all)
        except Exception as e:
            self.app.call_from_thread(self._log, f"[dim]{ts}[/]  [red]ERR {e}[/]")

    def _do_close(self, args, ts):
        if not args:
            return
        if args[0].lower() == "all":
            self.api.close_all_positions()
            self._log(f"[dim]{ts}[/]  [yellow]All positions closed[/]")
        else:
            self.api.close_position(args[0].upper())
            self._log(f"[dim]{ts}[/]  [yellow]{args[0].upper()} closed[/]")
        self.refresh_all()

    def _do_cancel(self, args, ts):
        if not args:
            return
        if args[0].lower() == "all":
            self.api.cancel_all_orders()
            self._log(f"[dim]{ts}[/]  [yellow]All orders cancelled[/]")
        else:
            self.api.cancel_order(args[0])
            self._log(f"[dim]{ts}[/]  [yellow]Cancelled {args[0][:8]}[/]")
        self.refresh_all()

    def _do_watch(self, args, ts):
        for s in args:
            if s.startswith("+"):
                sym = s[1:].upper()
                if sym not in self.watchlist:
                    self.watchlist.append(sym)
                    self._log(f"[dim]{ts}[/]  [cyan]+{sym}[/]")
            elif s.startswith("-"):
                sym = s[1:].upper()
                if sym in self.watchlist:
                    self.watchlist.remove(sym)
                    self._log(f"[dim]{ts}[/]  [dim]-{sym}[/]")
            else:
                sym = s.upper()
                if sym not in self.watchlist:
                    self.watchlist.append(sym)
                    self._log(f"[dim]{ts}[/]  [cyan]+{sym}[/]")
        save_watchlist(self.watchlist)
        self.refresh_prices()


def _reset_terminal():
    """Force terminal back to sane state — runs on any exit."""
    try:
        fd = sys.stdout.fileno()
        # Exit alternate screen, disable mouse tracking, show cursor, reset attrs
        os.write(fd, b'\033[?1049l\033[?1000l\033[?1003l\033[?1006l\033[?1015l\033[?25h\033[0m\n')
    except Exception:
        pass
    try:
        import termios, tty
        # Restore cooked mode if possible
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW,
                          termios.tcgetattr(sys.stdin.fileno()))
    except Exception:
        pass

import atexit
atexit.register(_reset_terminal)

if __name__ == "__main__":
    app = TradingTerminal()
    app.run()
    _reset_terminal()
    sys.exit(app.return_code or 0)
