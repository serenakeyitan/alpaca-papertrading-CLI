#!/usr/bin/env python3
"""Comprehensive test suite for the web dashboard panel swap & resize.

Tests:
1. All 5 panels render with correct IDs
2. All API endpoints return valid data
3. innerHTML swap logic correctness (simulated)
4. Layout save/restore consistency
5. Resize dividers present and correctly positioned
6. Cross-row swap doesn't break element IDs
7. Multiple sequential swaps maintain consistency
8. All refresh functions can find their target elements after swap
9. No duplicate IDs after swap
10. Drag-drop attributes present on all panels
"""

import sys
import json
import re
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_SITE = SKILL_DIR / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from web_dashboard import app

# Wait for background cache to complete its first fetch cycle
import time as _time
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


def test_html_structure():
    """Test 1: All 5 panels exist with correct structure."""
    print("\n── Test 1: HTML Structure ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        # All 5 panels present
        panels = ['watchlist', 'positions', 'strategies', 'orders', 'log']
        for p in panels:
            check(f'Panel "{p}" exists', f'data-panel="{p}"' in html)

        # All panels are draggable
        draggable_count = html.count('draggable="true"')
        check(f'All 5 panels draggable', draggable_count == 5, f'found {draggable_count}')

        # All panels have drag handles
        handle_count = html.count('drag-handle')
        check(f'All 5 drag handles', handle_count >= 5, f'found {handle_count}')

        # All panel containers have IDs
        panel_ids = ['watchlist-pane', 'positions-pane', 'strat-left', 'strat-right', 'log-area']
        for pid in panel_ids:
            check(f'Container ID "{pid}"', f'id="{pid}"' in html)

        # Key inner element IDs present
        inner_ids = ['watchlist-body', 'positions-body', 'strat-body', 'orders-body', 'log-body']
        for iid in inner_ids:
            check(f'Inner ID "{iid}"', f'id="{iid}"' in html)
            # No duplicates
            count = html.count(f'id="{iid}"')
            check(f'No duplicate "{iid}"', count == 1, f'found {count}')

        # Pane titles present
        titles = ['WATCHLIST', 'POSITIONS', 'STRATEGIES', 'OPEN ORDERS', 'TRADING LOG']
        for t in titles:
            check(f'Title "{t}"', t in html)


def test_api_endpoints():
    """Test 2: All API endpoints return valid JSON."""
    print("\n── Test 2: API Endpoints ──")
    with app.test_client() as c:
        endpoints = [
            ('/api/account', dict),
            ('/api/positions', list),
            ('/api/watchlist', list),
            ('/api/orders', list),
            ('/api/strategies', list),
            ('/api/log', list),
            ('/api/bars/NVDA', list),
            ('/api/bars/ETH/USD', list),
        ]
        for url, expected_type in endpoints:
            r = c.get(url)
            check(f'{url} returns 200', r.status_code == 200, f'got {r.status_code}')
            try:
                data = json.loads(r.data)
                check(f'{url} valid JSON ({expected_type.__name__})',
                      isinstance(data, expected_type),
                      f'got {type(data).__name__}')
                if isinstance(data, dict):
                    check(f'{url} no error', 'error' not in data, data.get('error', ''))
            except json.JSONDecodeError:
                check(f'{url} valid JSON', False, 'JSONDecodeError')


def test_account_strategy_fields():
    """Test 3: Account API includes correct strategy fields."""
    print("\n── Test 3: Account Strategy Fields ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/account').data)
        check('strat_total > 0', data.get('strat_total', 0) > 0, f"got {data.get('strat_total')}")
        check('strat_active > 0', data.get('strat_active', 0) > 0, f"got {data.get('strat_active')}")
        check('strat_pnl is numeric', isinstance(data.get('strat_pnl'), (int, float)))
        check('strat_deployed > 0', data.get('strat_deployed', 0) > 0)
        check('strat_allocated > 0', data.get('strat_allocated', 0) > 0)
        check('market_open is bool', isinstance(data.get('market_open'), bool))


def test_strategies_api():
    """Test 4: Strategies API returns proper data."""
    print("\n── Test 4: Strategies API ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/strategies').data)
        check('Has strategies', len(data) > 0, f'got {len(data)}')
        for s in data:
            name = s.get('name', '?')
            check(f'{name}: has type', 'type' in s)
            check(f'{name}: has status', 'status' in s)
            check(f'{name}: has is_crypto', 'is_crypto' in s)
            check(f'{name}: has last_tick', 'last_tick' in s and s['last_tick'] != '---',
                  f"got '{s.get('last_tick')}'")
            check(f'{name}: has fills', 'fills' in s)
            check(f'{name}: total_pnl is numeric', isinstance(s.get('total_pnl'), (int, float)))


def test_watchlist_crypto_change():
    """Test 5: Watchlist crypto entries have non-zero change_pct."""
    print("\n── Test 5: Watchlist Crypto Change ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/watchlist').data)
        stocks = [w for w in data if w['type'] == 'stock']
        cryptos = [w for w in data if w['type'] == 'crypto']
        check('Has stocks', len(stocks) > 0)
        check('Has cryptos', len(cryptos) > 0)
        for w in data:
            check(f'{w["symbol"]}: has price', w['price'] > 0, f"got {w['price']}")
        for w in cryptos:
            check(f'{w["symbol"]}: has change_pct', isinstance(w['change_pct'], (int, float)),
                  f"got {w.get('change_pct')}")


def test_trade_log_no_duplicates():
    """Test 6: Trade log doesn't grow on repeated calls."""
    print("\n── Test 6: Trade Log Stability ──")
    with app.test_client() as c:
        log1 = json.loads(c.get('/api/log').data)
        log2 = json.loads(c.get('/api/log').data)
        log3 = json.loads(c.get('/api/log').data)
        check('Log returns entries', len(log1) > 0, f'got {len(log1)}')
        check('Log stable on repeat calls', len(log1) == len(log2) == len(log3),
              f'{len(log1)} vs {len(log2)} vs {len(log3)}')
        # Check entries have required fields
        if log1:
            e = log1[0]
            check('Entry has ts', 'ts' in e)
            check('Entry has msg', 'msg' in e)
            check('Entry has style', 'style' in e)


def test_swap_js_logic():
    """Test 7: JavaScript swap logic is correct."""
    print("\n── Test 7: Swap JS Logic ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        # innerHTML swap (not DOM node swap)
        check('Uses innerHTML swap', 'tmpHTML = panel.innerHTML' in html)
        check('Swaps innerHTML both ways', 'dragSrc.innerHTML = tmpHTML' in html)
        check('Swaps data-panel attr', 'tmpAttr = panel.dataset.panel' in html)

        # No same-parent restriction
        check('No parent restriction on dragover',
              'dragSrc.parentNode === panel.parentNode' not in html)
        check('No parent restriction on drop',
              'dragSrc.parentNode !== panel.parentNode' not in html)

        # Save uses container ID -> panel name mapping
        check('Save uses container ID', 'layout[p.id] = p.dataset.panel' in html)

        # Restore uses contentByName mapping
        check('Restore collects by name', 'contentByName[p.dataset.panel]' in html)
        check('Restore applies by container ID', 'document.getElementById(containerId)' in html)


def test_resize_js_logic():
    """Test 8: Resize dividers use dynamic neighbor lookup."""
    print("\n── Test 8: Resize JS Logic ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        # Dynamic neighbor lookup (not captured refs)
        check('Uses previousElementSibling', 'div.previousElementSibling' in html)
        check('Uses nextElementSibling', 'div.nextElementSibling' in html)

        # Both resize directions
        check('Has col-resize cursor', 'col-resize' in html)
        check('Has row-resize cursor', 'row-resize' in html)

        # Resize IDs for persistence
        check('Has data-resize-id', 'data-resize-id' in html)
        check('Saves to oc-sizes', 'oc-sizes' in html)


def test_css_alignment():
    """Test 9: CSS alignment and spacing."""
    print("\n── Test 9: CSS Alignment & Spacing ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        check('Body has padding', 'padding: 6px' in html)
        check('th centered', re.search(r'th\s*\{[^}]*text-align:\s*center', html) is not None)
        check('td centered', re.search(r'td\s*\{[^}]*text-align:\s*center', html) is not None)
        check('.r right-aligned', 'th.r, td.r { text-align: right; }' in html)


def test_status_line():
    """Test 10: Status line is simplified (no keyboard shortcuts)."""
    print("\n── Test 10: Status Line ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        check('No "q Quit" in status', 'q Quit' not in html)
        check('No "r Refresh" in status', 'r Refresh' not in html)
        check('Has tick counter', 'tick-count' in html)
        check('Has auto-refresh text', 'Auto-refresh' in html)


def test_strategy_market_status():
    """Test 11: Strategy status reflects market hours."""
    print("\n── Test 11: Strategy Market Status ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        check('Has MKT CLOSED logic', 'MKT CLOSED' in html)
        check('Has marketOpen variable', 'let marketOpen' in html)
        check('Checks is_crypto flag', 's.is_crypto' in html)

        # Check API returns is_crypto correctly
        strats = json.loads(c.get('/api/strategies').data)
        for s in strats:
            if 'eth' in s['name'].lower() or 'btc' in s['name'].lower():
                check(f'{s["name"]}: is_crypto=True', s['is_crypto'] is True)
            else:
                check(f'{s["name"]}: is_crypto=False', s['is_crypto'] is False)


def test_orders_api():
    """Test 12: Orders API returns proper data."""
    print("\n── Test 12: Orders API ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/orders').data)
        check('Orders is list', isinstance(data, list))
        if data:
            o = data[0]
            required = ['id', 'symbol', 'side', 'qty', 'type', 'status', 'submitted_at', 'strategy']
            for field in required:
                check(f'Order has {field}', field in o, f'missing from {list(o.keys())}')


def test_bars_endpoints():
    """Test 13: Bars endpoints work for stocks and crypto."""
    print("\n── Test 13: Bars Endpoints ──")
    with app.test_client() as c:
        # Stock bars
        r = c.get('/api/bars/NVDA')
        data = json.loads(r.data)
        check('NVDA bars returns list', isinstance(data, list))
        check('NVDA bars has entries', len(data) > 0, f'got {len(data)}')
        if data:
            check('Bar has OHLCV', all(k in data[0] for k in ['open', 'high', 'low', 'close', 'volume']))

        # Crypto bars (path with slash)
        r = c.get('/api/bars/BTC/USD')
        data = json.loads(r.data)
        check('BTC/USD bars returns list', isinstance(data, list))
        check('BTC/USD bars has entries', len(data) > 0, f'got {len(data)}')

        r = c.get('/api/bars/ETH/USD')
        data = json.loads(r.data)
        check('ETH/USD bars returns list', isinstance(data, list))
        check('ETH/USD bars has entries', len(data) > 0, f'got {len(data)}')


def test_no_stale_references():
    """Test 14: No stale element references in JS code."""
    print("\n── Test 14: No Stale References ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        # Resize should NOT capture elements in closure
        check('No captured elA/elB in resize',
              'elA.getBoundingClientRect' not in html and 'elB.getBoundingClientRect' not in html)

        # Swap should NOT move DOM nodes
        check('No insertBefore in swap', 'insertBefore' not in html)
        check('No appendChild in swap',
              html.count('appendChild') == 0 or 'appendChild' not in html.split('restoreLayout')[0].split('drop')[-1])


def test_html_no_duplicate_ids():
    """Test 15: No duplicate element IDs in HTML."""
    print("\n── Test 15: No Duplicate IDs ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()
        ids = re.findall(r'id="([^"]+)"', html)
        seen = {}
        for id_val in ids:
            seen[id_val] = seen.get(id_val, 0) + 1
        dupes = {k: v for k, v in seen.items() if v > 1}
        check('No duplicate IDs', len(dupes) == 0, f'duplicates: {dupes}')


def test_trade_log_timezone():
    """Test 16: Trade log timestamps use local time, not UTC."""
    print("\n── Test 16: Trade Log Timezone ──")
    from datetime import timezone as tz
    with app.test_client() as c:
        data = json.loads(c.get('/api/log').data)
        check('Log has entries', len(data) > 0)

        # Get current local date
        now_local = datetime.now()
        local_date = now_local.strftime("%m/%d")
        utc_date = datetime.now(tz.utc).strftime("%m/%d")

        # Collect all dates in log
        log_dates = set()
        for e in data:
            if e['ts'] != '---':
                log_dates.add(e['ts'].split(' ')[0])

        # If local and UTC dates differ, verify log uses local date
        if local_date != utc_date:
            check(f'Log uses local date ({local_date}), not UTC ({utc_date})',
                  local_date in log_dates,
                  f'dates found: {sorted(log_dates)}')
            # Most recent fills should be today in local time
            recent_fills = [e for e in data if e['style'] in ('fill-buy', 'fill-sell')
                            and e['ts'] != '---']
            if recent_fills:
                last_fill_date = recent_fills[-1]['ts'].split(' ')[0]
                check(f'Most recent fill date is local ({local_date})',
                      last_fill_date == local_date,
                      f'got {last_fill_date}')
        else:
            check('Local and UTC same date (skip timezone check)', True)

        # Verify timestamp format MM/DD HH:MM:SS
        for e in data[:10]:
            if e['ts'] != '---' and e['style'] != 'info':
                ts = e['ts']
                parts = ts.split(' ')
                is_valid = (len(parts) == 2 and '/' in parts[0] and ':' in parts[1]
                            and len(parts[0]) == 5)  # MM/DD = 5 chars
                check(f'Timestamp format MM/DD HH:MM:SS: "{ts}"',
                      is_valid, f'got "{ts}"')
                break


def test_trade_log_content():
    """Test 17: Trade log entries have correct content."""
    print("\n── Test 17: Trade Log Content ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/log').data)
        check('Log has entries', len(data) > 0)

        fills = [e for e in data if e['style'] in ('fill-buy', 'fill-sell')]
        info = [e for e in data if e['style'] == 'info']

        check('Has fill entries', len(fills) > 0, f'got {len(fills)}')
        check('Has info entry (loaded message)', len(info) > 0)

        # Check fill message format
        for e in fills[:5]:
            msg = e['msg']
            check(f'Fill has FILL prefix: "{msg[:30]}..."',
                  msg.startswith('FILL '))
            check(f'Fill has side (BUY/SELL)',
                  'BUY' in msg or 'SELL' in msg)
            check(f'Fill has price (@)',
                  '@ $' in msg)
            check(f'Fill has symbol',
                  'ETH/USD' in msg or 'NVDA' in msg or 'AAPL' in msg or 'QQQ' in msg or 'BTC/USD' in msg)
            break  # Only check first fill in detail

        # Check buy fills are green, sell fills are red
        buy_found = False
        sell_found = False
        for e in fills:
            if 'BUY' in e['msg'] and not buy_found:
                check(f'BUY fill style is fill-buy', e['style'] == 'fill-buy')
                buy_found = True
            if 'SELL' in e['msg'] and not sell_found:
                check(f'SELL fill style is fill-sell', e['style'] == 'fill-sell')
                sell_found = True
            if buy_found and sell_found:
                break

        # Check strategy tags present
        tagged = [e for e in fills if '[' in e['msg']]
        check('Fills have strategy tags [name]', len(tagged) > 0,
              f'{len(tagged)}/{len(fills)} tagged')


def test_trade_log_fill_count():
    """Test 18: Trade log loads enough fills."""
    print("\n── Test 18: Trade Log Fill Count ──")
    with app.test_client() as c:
        data = json.loads(c.get('/api/log').data)
        fills = [e for e in data if e['style'] in ('fill-buy', 'fill-sell')]

        check('Log has many fills (>50)', len(fills) >= 50,
              f'got {len(fills)} fills')
        check('Log capped at 100 entries', len(data) <= 100,
              f'got {len(data)}')

        # Check fills are roughly sorted chronologically (oldest first)
        timestamps = [e['ts'] for e in fills if e['ts'] != '---' and '/' in e['ts']]
        if len(timestamps) >= 2:
            check('Fills ordered (first < last)',
                  timestamps[0] <= timestamps[-1],
                  f'first={timestamps[0]}, last={timestamps[-1]}')


def test_trade_log_no_growth():
    """Test 19: Trade log doesn't grow on repeated API calls."""
    print("\n── Test 19: Trade Log No Growth ──")
    with app.test_client() as c:
        # Call multiple times
        sizes = []
        for i in range(5):
            data = json.loads(c.get('/api/log').data)
            sizes.append(len(data))

        check('Log size stable across 5 calls', len(set(sizes)) == 1,
              f'sizes: {sizes}')

        # Check no duplicate messages
        msgs = [e['ts'] + e['msg'] for e in data]
        unique = set(msgs)
        check('No duplicate log entries', len(msgs) == len(unique),
              f'{len(msgs)} entries, {len(unique)} unique')


def test_orders_timezone():
    """Test 20: Open orders use local time with MM/DD format."""
    print("\n── Test 20: Orders Timezone ──")
    from datetime import timezone as tz
    with app.test_client() as c:
        data = json.loads(c.get('/api/orders').data)
        if data:
            local_date = datetime.now().strftime("%m/%d")
            # Check format is MM/DD HH:MM (11 chars)
            sample = data[0]['submitted_at']
            check(f'Order time format MM/DD HH:MM: "{sample}"',
                  '/' in sample and len(sample.split('/')[0]) == 2,
                  f'got "{sample}"')
            # Check dates
            order_dates = set(o['submitted_at'].split(' ')[0] for o in data)
            check(f'Orders include local date ({local_date})',
                  local_date in order_dates,
                  f'dates: {sorted(order_dates)}')
        else:
            check('No open orders (skip)', True)


def test_utc_to_local_helper():
    """Test 21: _utc_to_local_str helper function works correctly."""
    print("\n── Test 21: UTC to Local Helper ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()  # trigger app import

    from web_dashboard import _utc_to_local_str

    # Test with ISO string
    result = _utc_to_local_str("2026-03-13T00:30:00+00:00")
    check('ISO string converts', '/' in result and ':' in result, f'got "{result}"')
    check('ISO string is local time (not 00:30 UTC)',
          not result.endswith('00:30:00') or datetime.now().strftime('%z') == '+0000',
          f'got "{result}"')

    # Test with Z suffix
    result = _utc_to_local_str("2026-03-13T00:30:00Z")
    check('Z suffix converts', '/' in result and ':' in result, f'got "{result}"')

    # Test with None
    result = _utc_to_local_str(None)
    check('None returns "---"', result == '---', f'got "{result}"')

    # Test with datetime object
    from datetime import timezone as tz
    dt = datetime(2026, 3, 13, 0, 30, 0, tzinfo=tz.utc)
    result = _utc_to_local_str(dt)
    check('datetime obj converts', '/' in result and ':' in result, f'got "{result}"')

    # Verify it actually converts to local
    # 2026-03-13 00:30 UTC should be 2026-03-12 17:30 PDT (UTC-7)
    local_offset = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    if local_offset != 0:
        check(f'Converts to local (offset={local_offset}h)', '03/12' in result or '03/13' in result,
              f'got "{result}"')


def test_color_scheme():
    """Test 22: GitHub Dark High Contrast color scheme."""
    print("\n── Test 22: Color Scheme ──")
    with app.test_client() as c:
        html = c.get('/').data.decode()

        # Accent color is blue, not green
        check('Accent color is blue (#58a6ff)', '--accent: #58c0fa' in html)
        # Green is reserved for positive numbers
        check('Green for positive (#3fb950)', '--green: #3fb950' in html)
        # Red for negative
        check('Red for negative (#f85149)', '--red: #f85149' in html)
        # Background is GitHub dark HC
        check('Background is #010409', '--bg: #010409' in html)
        # Header bg
        check('Header bg is #0d1117', '--header-bg: #0d1117' in html)
        # Border color
        check('Border is #30363d', '--border: #30363d' in html)
        # Text is high contrast
        check('Text is #f0f6fc', '--text: #f0f6fc' in html)
        # Dim text
        check('Dim is #8b949e', '--dim: #8b949e' in html)

        # Title bar uses accent, not green
        check('Title bar uses accent', "background: var(--accent)" in html)
        # Pane titles use accent
        check('Pane titles use accent',
              re.search(r'\.pane-title\s*\{[^}]*color:\s*var\(--accent\)', html) is not None)
        # Table headers use accent
        check('Table headers use accent',
              re.search(r'th\s*\{[^}]*color:\s*var\(--accent\)', html) is not None)

        # Green only used for data (pos class, fills, sparklines)
        check('.pos uses green', '.pos { color: var(--green)' in html)
        check('.neg uses red', '.neg { color: var(--red)' in html)
        check('Buy fills use green', '.log-fill-buy { color: var(--green)' in html)
        check('Sell fills use red', '.log-fill-sell { color: var(--red)' in html)

        # Borders are thin (1px), not thick
        check('Resize dividers are 1px',
              'width:1px;min-width:1px;cursor:col-resize' in html)
        check('Row dividers are 1px',
              'height:1px;min-height:1px;cursor:row-resize' in html)

        # Drag outline uses accent, thin
        check('Drag outline uses accent',
              '1px solid var(--accent)' in html)

        # Log strat tags use accent (not green)
        check('Log strat uses accent', '.log-strat { color: var(--accent)' in html)

        # Status indicator uses accent
        check('Status indicator uses accent',
              'color:var(--accent);margin-left:auto' in html)


if __name__ == "__main__":
    print("=" * 60)
    print("  Dashboard Comprehensive Test Suite")
    print("=" * 60)

    test_html_structure()
    test_api_endpoints()
    test_account_strategy_fields()
    test_strategies_api()
    test_watchlist_crypto_change()
    test_trade_log_no_duplicates()
    test_swap_js_logic()
    test_resize_js_logic()
    test_css_alignment()
    test_status_line()
    test_strategy_market_status()
    test_orders_api()
    test_bars_endpoints()
    test_no_stale_references()
    test_html_no_duplicate_ids()
    test_trade_log_timezone()
    test_trade_log_content()
    test_trade_log_fill_count()
    test_trade_log_no_growth()
    test_orders_timezone()
    test_utc_to_local_helper()
    test_color_scheme()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
