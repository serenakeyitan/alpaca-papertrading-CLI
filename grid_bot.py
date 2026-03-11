#!/usr/bin/env python3
"""OpenClaw Grid Trading Bot — autonomous grid trading on Alpaca paper."""

import json
import sys
import time
import math
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    sys.path.insert(0, str(p))

import alpaca_trade_api as tradeapi

CONFIG_PATH = Path(__file__).parent / "config.json"
STATE_PATH = Path(__file__).parent / "grid_state.json"
LOG_PATH = Path(__file__).parent / "grid_bot.log"

# ── Config ────────────────────────────────────────────────

GRID_CONFIG = {
    # Each symbol: grid_pct (total range %), num_grids, qty_per_grid
    "NVDA": {"grid_pct": 6, "num_grids": 10, "qty_per_grid": 2},
    "AAPL": {"grid_pct": 4, "num_grids": 8, "qty_per_grid": 3},
    "SPY":  {"grid_pct": 3, "num_grids": 8, "qty_per_grid": 2},
}

# ── Helpers ───────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def get_api():
    cfg = json.loads(CONFIG_PATH.read_text())
    return tradeapi.REST(
        cfg["api_key"], cfg["secret_key"],
        base_url="https://paper-api.alpaca.markets",
        api_version="v2"
    )

def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))

def is_market_open(api):
    try:
        clock = api.get_clock()
        return clock.is_open
    except Exception:
        return False

# ── Grid Logic ────────────────────────────────────────────

def compute_grid_levels(center_price, grid_pct, num_grids):
    """Compute grid price levels above and below center."""
    half = num_grids // 2
    step = (center_price * grid_pct / 100) / num_grids
    levels = []
    for i in range(-half, half + 1):
        if i == 0:
            continue  # skip center
        price = round(center_price + i * step, 2)
        side = "buy" if i < 0 else "sell"
        levels.append({"price": price, "side": side, "grid_idx": i})
    return levels

def get_open_orders_for_symbol(api, symbol):
    """Get all open orders for a symbol."""
    orders = api.list_orders(status="open", limit=100)
    return [o for o in orders if o.symbol == symbol]

def get_position_qty(api, symbol):
    """Get current position quantity, 0 if none."""
    try:
        pos = api.get_position(symbol)
        return float(pos.qty)
    except Exception:
        return 0

def sync_grid(api, symbol, config, state):
    """Sync grid orders for a symbol. Core logic."""
    grid_pct = config["grid_pct"]
    num_grids = config["num_grids"]
    qty = config["qty_per_grid"]

    sym_state = state.get(symbol, {})
    center = sym_state.get("center_price")
    fills = sym_state.get("total_fills", 0)
    profit = sym_state.get("realized_profit", 0.0)

    # Get current price
    try:
        trade = api.get_latest_trade(symbol)
        current_price = float(trade.price)
    except Exception as e:
        log(f"  {symbol}: Cannot get price: {e}")
        return state

    # Initialize or re-center if price drifted too far
    recenter = False
    if center is None:
        recenter = True
    else:
        drift_pct = abs(current_price - center) / center * 100
        if drift_pct > grid_pct * 0.8:
            recenter = True
            log(f"  {symbol}: Price drifted {drift_pct:.1f}% from center, re-centering")

    if recenter:
        # Cancel all existing orders for this symbol
        existing = get_open_orders_for_symbol(api, symbol)
        for o in existing:
            try:
                api.cancel_order(o.id)
            except Exception:
                pass
        center = current_price
        log(f"  {symbol}: Center set to ${center:.2f}")
        sym_state["center_price"] = center
        sym_state["grid_levels"] = []

    # Compute desired grid levels
    levels = compute_grid_levels(center, grid_pct, num_grids)

    # Check existing open orders
    existing_orders = get_open_orders_for_symbol(api, symbol)
    existing_prices = set()
    for o in existing_orders:
        if o.limit_price:
            existing_prices.add(round(float(o.limit_price), 2))

    # Check for filled orders since last run
    prev_order_ids = set(sym_state.get("open_order_ids", []))
    current_order_ids = {o.id for o in existing_orders}
    filled_ids = prev_order_ids - current_order_ids

    if filled_ids:
        # Some orders got filled — count them
        for oid in filled_ids:
            try:
                filled_order = api.get_order(oid)
                if filled_order.status == "filled" and filled_order.filled_avg_price:
                    fills += 1
                    fill_price = float(filled_order.filled_avg_price)
                    side = filled_order.side
                    fill_qty = float(filled_order.filled_qty)

                    # Estimate profit: each grid fill earns ~1 grid step
                    step = (center * grid_pct / 100) / num_grids
                    profit += step * fill_qty
                    log(f"  {symbol}: FILLED {side.upper()} {fill_qty}x @ ${fill_price:.2f} (grid profit ~${step * fill_qty:.2f})")
            except Exception:
                pass

    sym_state["total_fills"] = fills
    sym_state["realized_profit"] = round(profit, 2)

    # Get current position to decide which sides to place
    pos_qty = get_position_qty(api, symbol)

    # Place missing grid orders
    new_order_ids = list(current_order_ids)
    orders_placed = 0
    for level in levels:
        price = level["price"]
        side = level["side"]

        # Skip if order already exists at this price
        if price in existing_prices:
            continue

        # Skip sell orders if we don't have enough shares
        if side == "sell" and pos_qty < qty:
            continue

        # Skip buy orders if price is above current (would execute immediately as market)
        if side == "buy" and price >= current_price:
            continue

        # Skip sell orders if price is below current
        if side == "sell" and price <= current_price:
            continue

        try:
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="limit",
                limit_price=price,
                time_in_force="day",
            )
            new_order_ids.append(order.id)
            orders_placed += 1
        except Exception as e:
            log(f"  {symbol}: Failed to place {side} @ ${price:.2f}: {e}")

    sym_state["open_order_ids"] = new_order_ids
    sym_state["last_price"] = current_price
    sym_state["last_sync"] = datetime.now().isoformat()

    if orders_placed > 0:
        log(f"  {symbol}: Placed {orders_placed} new grid orders (center=${center:.2f}, price=${current_price:.2f})")
    else:
        log(f"  {symbol}: Grid in sync (center=${center:.2f}, price=${current_price:.2f}, pos={pos_qty})")

    state[symbol] = sym_state
    return state

# ── Initial Position ──────────────────────────────────────

def ensure_base_position(api, symbol, config):
    """Buy initial shares so we can place sell grids."""
    qty = config["qty_per_grid"]
    half_grids = config["num_grids"] // 2
    target_qty = qty * half_grids  # Need shares for sell side

    current_qty = get_position_qty(api, symbol)
    need = target_qty - current_qty

    if need > 0:
        log(f"  {symbol}: Building base position, buying {need} shares")
        try:
            api.submit_order(
                symbol=symbol, qty=need, side="buy",
                type="market", time_in_force="day"
            )
        except Exception as e:
            log(f"  {symbol}: Failed to buy base position: {e}")

# ── Status display ────────────────────────────────────────

def print_status(api, state):
    """Print current grid bot status."""
    print()
    print("  OPENCLAW GRID BOT STATUS")
    print("  " + "─" * 60)

    total_profit = 0
    total_fills = 0

    for symbol, cfg in GRID_CONFIG.items():
        sym_state = state.get(symbol, {})
        center = sym_state.get("center_price", 0)
        fills = sym_state.get("total_fills", 0)
        profit = sym_state.get("realized_profit", 0.0)
        last_price = sym_state.get("last_price", 0)
        total_profit += profit
        total_fills += fills

        pos_qty = get_position_qty(api, symbol)
        open_orders = len(get_open_orders_for_symbol(api, symbol))

        print(f"  {symbol:<6}  center=${center:>8.2f}  price=${last_price:>8.2f}  "
              f"pos={pos_qty:>4g}  orders={open_orders:>2}  "
              f"fills={fills:>3}  profit=${profit:>8.2f}")

    print("  " + "─" * 60)
    print(f"  TOTAL   fills={total_fills}  est. profit=${total_profit:.2f}")
    print()

# ── Main ──────────────────────────────────────────────────

def run_once():
    """Single grid sync pass."""
    api = get_api()
    state = load_state()

    if not is_market_open(api):
        log("Market is closed. Skipping.")
        print_status(api, state)
        return

    log("─── Grid Bot Sync ───")

    for symbol, config in GRID_CONFIG.items():
        # Ensure we have base shares for sell side
        ensure_base_position(api, symbol, config)
        state = sync_grid(api, symbol, config, state)

    save_state(state)
    print_status(api, state)
    log("─── Sync Complete ───")

def run_loop():
    """Continuous loop, syncs every 5 minutes during market hours."""
    log("Grid Bot starting in loop mode (5 min interval)")
    api = get_api()

    while True:
        try:
            if is_market_open(api):
                run_once()
            else:
                state = load_state()
                log("Market closed. Waiting...")
                print_status(api, state)
        except Exception as e:
            log(f"Error in loop: {e}")

        time.sleep(300)  # 5 minutes

def run_status():
    """Just show status."""
    api = get_api()
    state = load_state()
    print_status(api, state)

def main():
    import argparse
    parser = argparse.ArgumentParser(prog="grid-bot", description="OpenClaw Grid Trading Bot")
    parser.add_argument("action", nargs="?", default="once",
                        choices=["once", "loop", "status", "reset"],
                        help="once=single pass, loop=continuous, status=show state, reset=clear state")
    args = parser.parse_args()

    if args.action == "once":
        run_once()
    elif args.action == "loop":
        run_loop()
    elif args.action == "status":
        run_status()
    elif args.action == "reset":
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        log("Grid state reset.")
        # Cancel all grid orders
        api = get_api()
        for symbol in GRID_CONFIG:
            orders = get_open_orders_for_symbol(api, symbol)
            for o in orders:
                try:
                    api.cancel_order(o.id)
                except Exception:
                    pass
        log("All grid orders cancelled.")

if __name__ == "__main__":
    main()
