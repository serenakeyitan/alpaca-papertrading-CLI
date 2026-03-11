#!/usr/bin/env python3
"""OpenClaw Live Trading Terminal — multi-strategy real-time dashboard."""

import json
import os
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

from candlestick_chart import Candle, Chart as CandleChart
from rich.ansi import AnsiDecoder

from strategy_manager import StrategyManager

CONFIG_PATH = Path(__file__).parent / "config.json"
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"

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

# ── CSS ───────────────────────────────────────────────────

CSS = """
Screen { background: #000000; color: #c8d6e5; scrollbar-size: 0 0; }
* { scrollbar-size: 0 0; scrollbar-color: #000000; scrollbar-background: #000000; }

#title-bar {
    dock: top; height: 1;
    background: #00d4aa; color: #000000; text-style: bold;
    padding: 0 1;
}
#account-bar { height: 3; background: #0c0c0c; padding: 0 1; }

#tables-row { height: auto; max-height: 14; }
#watchlist-pane { width: 1fr; background: #000000; border-right: solid #1a2332; }
#positions-pane { width: 1fr; background: #000000; }

#chart-pane { height: 1fr; min-height: 8; background: #000000; }
#chart-display { height: 1fr; background: #000000; padding: 0 0; }

#strat-area { height: auto; min-height: 4; max-height: 10; }
#strat-left { width: 2fr; background: #000000; border-right: solid #1a2332; }
#strat-right { width: 1fr; background: #000000; }

#log-area { height: 1fr; min-height: 6; }
#trades-pane { width: 1fr; background: #000000; }

.pane-title {
    height: 1; padding: 0 1;
    background: #111111; color: #00d4aa; text-style: bold;
}

DataTable { height: 1fr; background: #000000; }
DataTable > .datatable--header { background: #111111; color: #00d4aa; text-style: bold; }
DataTable > .datatable--cursor { background: #0a1a2a; }
#watch-table { height: auto; max-height: 12; }

RichLog { height: 1fr; background: #000000; padding: 0 1; scrollbar-size: 1 1; }

#command-bar { dock: bottom; height: 3; background: #0c0c0c; padding: 0 1; }
#cmd-input { background: #111111; color: #c8d6e5; border: none; }

#status-line { dock: bottom; height: 1; background: #111111; color: #576a7e; padding: 0 1; }
"""

# ── App ───────────────────────────────────────────────────

class TradingTerminal(App):
    CSS = CSS
    TITLE = "OpenClaw Terminal"

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
        self.prev_prices = {}
        self.last_order_ids = set()
        self.tick_count = 0
        self.selected_symbol = self.watchlist[0] if self.watchlist else "NVDA"
        self.bars_cache = {}  # symbol -> list of Candle
        self.mini_bars = {}   # symbol -> list of {open,close,high,low} for sparklines

    def compose(self) -> ComposeResult:
        yield Static("", id="title-bar")
        yield Static("", id="account-bar")

        with Horizontal(id="tables-row"):
            with Vertical(id="watchlist-pane"):
                yield Static(" MARKET", classes="pane-title")
                yield DataTable(id="watch-table")
            with Vertical(id="positions-pane"):
                yield Static(" POSITIONS", classes="pane-title")
                yield DataTable(id="pos-table")

        with Vertical(id="chart-pane"):
            yield Static(" CANDLESTICK", classes="pane-title", id="chart-title")
            yield Static("Select a symbol...", id="chart-display")

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
                placeholder=" strat add grid my-grid NVDA | strat pause X | buy AAPL 10 | sell TSLA | close all",
                id="cmd-input"
            )

    def on_mount(self):
        # Watchlist columns
        wt = self.query_one("#watch-table", DataTable)
        wt.cursor_type = "row"
        wt.add_columns("#", "Symbol", "Price", "Chg", "Bid", "Ask", "Trend")

        # Positions columns
        pt = self.query_one("#pos-table", DataTable)
        pt.cursor_type = "row"
        pt.add_columns("Symbol", "Qty", "Entry", "Price", "Value", "P&L", "P&L%", "Trend")

        # Strategy columns
        st = self.query_one("#strat-table", DataTable)
        st.cursor_type = "row"
        st.add_columns("Name", "Type", "Status", "Capital", "Used", "Real P&L", "Unrl P&L", "Total P&L", "Fills", "Last Tick")

        # Orders columns
        ot = self.query_one("#order-table", DataTable)
        ot.cursor_type = "row"
        ot.add_columns("Time", "Side", "Symbol", "Qty", "Type", "Limit", "Status", "Strategy")

        self._log("Terminal started")
        self.refresh_all()

        self.set_interval(5, self.refresh_prices)
        self.set_interval(10, self.refresh_account)
        self.set_interval(10, self.refresh_positions)
        self.set_interval(8, self.poll_orders)
        self.set_interval(15, self.refresh_strategies)
        self.set_interval(1, self.update_clock)
        self.set_interval(30, self.refresh_chart)
        self.refresh_chart()

    def update_clock(self):
        now = datetime.now().strftime("%H:%M:%S")
        dot = "●" if self.tick_count % 2 == 0 else "○"
        try:
            clock = self.api.get_clock()
            mkt = "[green]OPEN[/]" if clock.is_open else "[red]CLOSED[/]"
        except Exception:
            mkt = "?"
        active = sum(1 for s in self.sm.strategies.values() if s.status == "active")
        total = len(self.sm.strategies)
        self.query_one("#title-bar", Static).update(
            f" OPENCLAW TERMINAL  │  {now} {dot}  │  Market {mkt}  │  "
            f"Strategies {active}/{total}  │  Press [bold]/[/] command"
        )
        self.query_one("#status-line", Static).update(
            f" q Quit  r Refresh  / Command  │  "
            f"strat add <type> <name> <symbol>  │  strat pause/resume/remove <name>  │  "
            f"buy/sell SYMBOL [QTY]  │  tick #{self.tick_count}"
        )
        self.tick_count += 1

    # ── Data fetching ─────────────────────────────────────

    @work(thread=True)
    def refresh_all(self):
        self._fetch_account()
        self._fetch_prices()
        self._fetch_positions()
        self._fetch_orders()
        self._fetch_strategies()

    @work(thread=True)
    def refresh_prices(self):
        self._fetch_prices()

    @work(thread=True)
    def refresh_account(self):
        self._fetch_account()

    @work(thread=True)
    def refresh_positions(self):
        self._fetch_positions()

    @work(thread=True)
    def poll_orders(self):
        self._poll_new_fills()
        self._fetch_orders()

    @work(thread=True)
    def refresh_strategies(self):
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
            f"\n"
            f"  [bold white]EQUITY[/] [bold]{fmt(eq)}[/]   "
            f"[dim]CASH[/] {fmt(cash)}   "
            f"[dim]BP[/] {fmt(bp)}   "
            f"[dim]DAY P&L[/] [{c}]{arr} {s}{fmt(pnl)} ({s}{pnl_pct:.2f}%)[/]   "
            f"[dim]STRAT P&L[/] [{sc}]{ss}{fmt(strat_pnl)}[/]   "
            f"[dim]CAPITAL DEPLOYED[/] {fmt(summary['total_used'])}/{fmt(summary['total_allocated'])}   "
            f"[green]{status}[/]"
        )

    def _fetch_prices(self):
        rows = []
        for i, sym in enumerate(self.watchlist):
            try:
                trade = self.api.get_latest_trade(sym)
                quote = self.api.get_latest_quote(sym)
                price = float(trade.price)
                bid = float(quote.bid_price) if quote.bid_price else None
                ask = float(quote.ask_price) if quote.ask_price else None

                if sym not in self.price_history:
                    self.price_history[sym] = deque(maxlen=30)
                self.price_history[sym].append(price)

                prev = self.prev_prices.get(sym, price)
                chg = (price - prev) / prev if prev else 0
                self.prev_prices[sym] = price

                rows.append((i+1, sym, price, chg, bid, ask, list(self.price_history[sym])))
            except Exception:
                rows.append((i+1, sym, None, 0, None, None, []))
        self.app.call_from_thread(self._render_prices, rows)

    def _render_prices(self, rows):
        wt = self.query_one("#watch-table", DataTable)
        wt.clear()
        for idx, sym, price, chg, bid, ask, hist in rows:
            trend = spark_trend(self.mini_bars.get(sym, []))
            if price is None:
                wt.add_row(Text(str(idx), style="dim"), Text(sym, style="bold"),
                           *[Text("---", style="dim")]*4, trend)
                continue
            if chg > 0.001: ps, cs = "bold #00d4aa", "#00d4aa"
            elif chg < -0.001: ps, cs = "bold #ff6b6b", "#ff6b6b"
            else: ps, cs = "bold white", "dim"

            arr = delta_arrow(chg)
            sel = "▸ " if sym == self.selected_symbol else "  "

            wt.add_row(
                Text(f"{sel}{idx}", style="dim"),
                Text(sym, style="bold white"),
                Text(fmt(price), style=ps),
                Text(f"{arr}{chg*100:+.2f}%", style=cs),
                Text(fmt(bid), style="cyan") if bid else Text("---", style="dim"),
                Text(fmt(ask), style="cyan") if ask else Text("---", style="dim"),
                trend,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """When a watchlist row is clicked, update the big chart."""
        if event.data_table.id != "watch-table":
            return
        try:
            row_cells = event.data_table.get_row(event.row_key)
            sym_text = row_cells[1]
            sym = sym_text.plain.strip() if hasattr(sym_text, "plain") else str(sym_text).strip()
            if sym and sym != "---":
                self.selected_symbol = sym
                # Only refresh the big chart, don't re-render the table
                if sym in self.bars_cache:
                    self._render_chart(sym, self.bars_cache[sym])
                else:
                    self.refresh_chart()
        except Exception:
            pass

    # ── Candlestick chart ──────────────────────────────────

    @work(thread=True)
    def refresh_chart(self):
        self._fetch_bars(self.selected_symbol)

    def _fetch_bars(self, symbol):
        try:
            from datetime import timedelta
            end = datetime.now()
            start = end - timedelta(days=30)

            # Fetch bars for ALL watchlist + position symbols in one call
            pos_syms = set()
            try:
                for p in self.api.list_positions():
                    if p.asset_class == "us_equity":
                        pos_syms.add(p.symbol)
            except Exception:
                pass
            # Only include equity-like symbols (skip crypto, options)
            all_syms = []
            for s in set(self.watchlist) | pos_syms | set(self.mini_bars.keys()):
                if s.isalpha() and len(s) <= 5:
                    all_syms.append(s)
            if symbol not in all_syms:
                all_syms.append(symbol)

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

            # Parse per-symbol bars
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
                    mini[sym] = ohlc[-14:]  # last 14 for sparklines

                    # Build Candle objects for the big chart
                    candles = [Candle(open=b["open"], close=b["close"],
                                     high=b["high"], low=b["low"]) for b in ohlc]
                    self.bars_cache[sym] = candles
                except Exception:
                    pass

            self.mini_bars = mini

            # Re-render tables so sparklines appear
            self.app.call_from_thread(self.refresh_prices)
            self.app.call_from_thread(self.refresh_positions)

            # Render the big chart for the selected symbol
            if symbol in self.bars_cache:
                self.app.call_from_thread(
                    self._render_chart, symbol, self.bars_cache[symbol]
                )
        except Exception as e:
            self.app.call_from_thread(
                self._render_chart_error, symbol, str(e)
            )

    def _render_chart(self, symbol, candles):
        if not candles:
            return
        try:
            chart_widget = self.query_one("#chart-display", Static)
            # Get approximate pane size, use sensible defaults
            w = chart_widget.size.width
            h = chart_widget.size.height
            if w < 20:
                w = 50
            if h < 5:
                h = 12
            chart = CandleChart(candles, width=w, height=h)
            chart.set_name(f"{symbol} (30D)")
            chart.set_bear_color(234, 74, 90)
            chart.set_bull_color(52, 208, 88)
            chart.set_volume_pane_enabled(False)
            rendered = chart._render()
            # Convert ANSI escape codes to Rich Text for Textual
            decoder = AnsiDecoder()
            lines = rendered.split("\n")
            from rich.text import Text as RText
            result = RText()
            for i, line in enumerate(lines):
                if i > 0:
                    result.append("\n")
                result.append_text(decoder.decode_line(line))
            chart_widget.update(result)
            self.query_one("#chart-title", Static).update(f" {symbol} CANDLESTICK (30D)")
        except Exception as e:
            chart_widget = self.query_one("#chart-display", Static)
            chart_widget.update(f"Chart error: {e}")
            self._log(f"[red]Chart render error: {e}[/]")

    def _render_chart_error(self, symbol, error):
        chart_widget = self.query_one("#chart-display", Static)
        chart_widget.update(f"[red]Chart error for {symbol}: {error}[/]")

    def _fetch_positions(self):
        try:
            positions = self.api.list_positions()
            rows = []
            for p in positions:
                # Detect which strategy owns this symbol
                strat_name = "manual"
                for s in self.sm.strategies.values():
                    sp = s.get_positions()
                    if p.symbol in sp:
                        strat_name = s.name
                        break

                rows.append({
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "entry": float(p.avg_entry_price),
                    "price": float(p.current_price),
                    "value": float(p.market_value),
                    "pnl": float(p.unrealized_pl),
                    "pnl_pct": float(p.unrealized_plpc),
                    "strategy": strat_name,
                })
            self.app.call_from_thread(self._render_positions, rows)
        except Exception:
            pass

    def _render_positions(self, rows):
        pt = self.query_one("#pos-table", DataTable)
        pt.clear()
        if not rows:
            pt.add_row(Text("No positions", style="dim"), *[Text("")]*7)
            return

        total_val = total_pnl = 0
        for p in rows:
            pnl = p["pnl"]
            pnl_pct = p["pnl_pct"] * 100
            total_val += p["value"]
            total_pnl += pnl
            c = "#00d4aa" if pnl >= 0 else "#ff6b6b"
            s = "+" if pnl >= 0 else ""
            a = delta_arrow(pnl)
            pt.add_row(
                Text(p["symbol"], style="bold white"),
                Text(f"{p['qty']:g}"),
                Text(fmt(p["entry"]), style="dim"),
                Text(fmt(p["price"]), style="bold white"),
                Text(fmt(p["value"])),
                Text(f"{a}{s}{fmt(pnl)}", style=c),
                Text(f"{s}{pnl_pct:.2f}%", style=c),
                spark_trend(self.mini_bars.get(p["symbol"], [])),
            )
        tc = "#00d4aa" if total_pnl >= 0 else "#ff6b6b"
        ts = "+" if total_pnl >= 0 else ""
        pt.add_row(
            Text("TOTAL", style="bold"), Text(""), Text(""), Text(""),
            Text(fmt(total_val), style="bold white"),
            Text(f"{ts}{fmt(total_pnl)}", style=f"bold {tc}"),
            Text(""), Text(""),
        )

    def _fetch_strategies(self):
        # Reload from disk in case bot updated it
        old_statuses = {n: s.status for n, s in self.sm.strategies.items()}
        self.sm = StrategyManager()
        summary = self.sm.get_summary()
        # Log status changes
        for s in summary["strategies"]:
            old = old_statuses.get(s["name"])
            if old and old != s["status"]:
                ts = datetime.now().strftime("%H:%M:%S")
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
            st.add_row(Text("No strategies. Use: strat add <type> <name> <symbol>", style="dim"),
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
                    lt = datetime.fromisoformat(last_tick).strftime("%H:%M:%S")
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
            orders = self.api.list_orders(status="open", limit=20)
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
                    "time": o.submitted_at.strftime("%H:%M:%S") if o.submitted_at else "---",
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

    def _poll_new_fills(self):
        try:
            orders = self.api.list_orders(status="all", limit=50)
            current_ids = {o.id for o in orders}
            new_ids = current_ids - self.last_order_ids

            for o in orders:
                if o.id not in new_ids:
                    continue
                ts = datetime.now().strftime("%H:%M:%S")
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
                    self.app.call_from_thread(
                        self._log,
                        f"[dim]{ts}[/]  [bold {c}]FILL {side}[/]  "
                        f"[bold white]{o.symbol}[/] x{o.qty} @ {price}{strat}"
                    )
                elif o.status in ("accepted", "new"):
                    side = o.side.upper()
                    c = "#00d4aa" if side == "BUY" else "#ff6b6b"
                    lim = fmt(o.limit_price) if o.limit_price else "mkt"
                    self.app.call_from_thread(
                        self._log,
                        f"[dim]{ts}[/]  [#f0c040]NEW[/]  [{c}]{side}[/] "
                        f"[bold]{o.symbol}[/] x{o.qty} @ {lim} {o.type}{strat}"
                    )
                elif o.status == "canceled":
                    self.app.call_from_thread(
                        self._log,
                        f"[dim]{ts}[/]  [dim]CANCEL {o.symbol} {o.side} x{o.qty}[/]{strat}"
                    )

            self.last_order_ids = current_ids
        except Exception:
            pass

    def _log(self, msg):
        self.query_one("#trade-log", RichLog).write(msg)

    # ── Actions ───────────────────────────────────────────

    def action_refresh(self):
        self._log(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/]  [cyan]Refreshing...[/]")
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

        parts = cmd.split()
        action = parts[0].lower()
        ts = datetime.now().strftime("%H:%M:%S")

        try:
            if action == "strat":
                self._do_strat(parts[1:], ts)
            elif action == "buy":
                self._do_buy(parts[1:], ts)
            elif action == "sell":
                self._do_sell(parts[1:], ts)
            elif action == "close":
                self._do_close(parts[1:], ts)
            elif action == "cancel":
                self._do_cancel(parts[1:], ts)
            elif action == "watch":
                self._do_watch(parts[1:], ts)
            elif action == "tick":
                self._do_tick(ts)
            elif action in ("q", "quit", "exit"):
                self.exit()
            elif action in ("r", "refresh"):
                self.action_refresh()
            else:
                self._log(f"[dim]{ts}[/]  [red]Unknown: {cmd}[/]")
        except Exception as e:
            self._log(f"[dim]{ts}[/]  [red]Error: {e}[/]")

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
            else:
                self._log(f"[dim]{ts}[/]  [red]Unknown type: {stype}. Use: grid, dca, momentum, mean_reversion[/]")
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


if __name__ == "__main__":
    app = TradingTerminal()
    app.run()
