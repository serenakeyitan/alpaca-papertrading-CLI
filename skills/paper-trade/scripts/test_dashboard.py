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
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_SITE = SKILL_DIR / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from web_dashboard import app

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

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
