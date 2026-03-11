"""Strategy commands – define and run custom trading strategies.

Strategies are Python files stored in ~/.alpaca-cli/strategies/.
Each strategy extends the BaseStrategy class.

Built-in strategies:
- DCA (Dollar-Cost Averaging)
- RSI-based (buy oversold, sell overbought)
- Rebalance (target allocation)
"""

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import click

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.common.exceptions import APIError

from alpaca_cli.utils.client import get_trading_client, get_stock_data_client, get_crypto_data_client
from alpaca_cli.utils.config import get_strategies_dir
from alpaca_cli.utils.output import (
    format_table,
    format_json,
    echo_success,
    echo_error,
    echo_info,
    echo_warn,
)
from alpaca_cli.utils.indicators import rsi as calc_rsi


# ── Base Strategy ─────────────────────────────────────────────────────


class BaseStrategy:
    """Base class for custom strategies.

    Override `run()` to implement your strategy logic.
    Use self.client (TradingClient) and self.params (dict) inside run().
    """

    name: str = "base"
    description: str = "Base strategy (override this)"

    def __init__(self, client, params: dict):
        self.client = client
        self.params = params

    def run(self) -> dict:
        """Execute the strategy. Return a dict with results/orders placed."""
        raise NotImplementedError("Override run() in your strategy.")

    def buy(self, symbol: str, qty: float, tif: str = "gtc") -> None:
        """Helper: place a market buy order."""
        tif_enum = TimeInForce.GTC if tif == "gtc" else TimeInForce.DAY
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=tif_enum,
        )
        self.client.submit_order(req)

    def sell(self, symbol: str, qty: float, tif: str = "gtc") -> None:
        """Helper: place a market sell order."""
        tif_enum = TimeInForce.GTC if tif == "gtc" else TimeInForce.DAY
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=tif_enum,
        )
        self.client.submit_order(req)

    def get_position(self, symbol: str):
        """Helper: get current position for a symbol (None if no position)."""
        try:
            return self.client.get_open_position(symbol.upper())
        except APIError:
            return None

    def get_account(self):
        """Helper: get account info."""
        return self.client.get_account()


# ── Built-in Strategies ──────────────────────────────────────────────


class DCAStrategy(BaseStrategy):
    """Dollar-Cost Averaging: buy a fixed dollar amount of a symbol periodically."""

    name = "dca"
    description = "Dollar-Cost Averaging – buy a fixed $ amount at market"

    def run(self) -> dict:
        symbol = self.params.get("symbol", "SPY")
        amount = float(self.params.get("amount", 100))

        echo_info(f"DCA: Buying ${amount:,.2f} of {symbol.upper()}")
        try:
            req = MarketOrderRequest(
                symbol=symbol.upper(),
                notional=amount,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = self.client.submit_order(req)
            echo_success(f"DCA order placed: {order.id}")
            return {"status": "success", "order_id": str(order.id), "symbol": symbol, "amount": amount}
        except APIError as e:
            echo_error(f"DCA order failed: {e}")
            return {"status": "error", "error": str(e)}


class RSIStrategy(BaseStrategy):
    """RSI-based strategy: buy when RSI < oversold, sell when RSI > overbought."""

    name = "rsi"
    description = "RSI strategy – buy oversold, sell overbought"

    def run(self) -> dict:
        symbol = self.params.get("symbol", "SPY")
        period = int(self.params.get("period", 14))
        oversold = float(self.params.get("oversold", 30))
        overbought = float(self.params.get("overbought", 70))
        qty = float(self.params.get("qty", 1))

        # Fetch recent data
        is_crypto = "/" in symbol
        start = datetime.now() - timedelta(days=60)

        try:
            if is_crypto:
                client = get_crypto_data_client()
                req = CryptoBarsRequest(
                    symbol_or_symbols=symbol.upper(),
                    timeframe=TimeFrame(1, TimeFrameUnit.Day),
                    start=start,
                )
                bars = client.get_crypto_bars(req)[symbol.upper()]
            else:
                client = get_stock_data_client()
                req = StockBarsRequest(
                    symbol_or_symbols=symbol.upper(),
                    timeframe=TimeFrame(1, TimeFrameUnit.Day),
                    start=start,
                )
                bars = client.get_stock_bars(req)[symbol.upper()]

            closes = [float(b.close) for b in bars]
            rsi_values = calc_rsi(closes, period)
            current_rsi = rsi_values[-1] if rsi_values[-1] is not None else 50

            echo_info(f"RSI({period}) for {symbol}: {current_rsi:.2f}")

            if current_rsi < oversold:
                echo_info(f"RSI < {oversold} (oversold) -> BUY signal")
                self.buy(symbol, qty)
                echo_success(f"Bought {qty} of {symbol}")
                return {"action": "buy", "rsi": current_rsi, "symbol": symbol}
            elif current_rsi > overbought:
                pos = self.get_position(symbol)
                if pos and float(pos.qty) >= qty:
                    echo_info(f"RSI > {overbought} (overbought) -> SELL signal")
                    self.sell(symbol, qty)
                    echo_success(f"Sold {qty} of {symbol}")
                    return {"action": "sell", "rsi": current_rsi, "symbol": symbol}
                else:
                    echo_info(f"RSI > {overbought} but no position to sell")
                    return {"action": "hold", "rsi": current_rsi, "reason": "no position"}
            else:
                echo_info(f"RSI in neutral zone ({oversold}-{overbought}) -> HOLD")
                return {"action": "hold", "rsi": current_rsi}

        except Exception as e:
            echo_error(f"RSI strategy failed: {e}")
            return {"status": "error", "error": str(e)}


class RebalanceStrategy(BaseStrategy):
    """Rebalance portfolio to target allocations."""

    name = "rebalance"
    description = "Rebalance portfolio to target allocations"

    def run(self) -> dict:
        targets_raw = self.params.get("targets", "{}")
        if isinstance(targets_raw, str):
            try:
                targets = json.loads(targets_raw)
            except json.JSONDecodeError:
                echo_error("Invalid targets JSON. Use format: '{\"AAPL\": 0.3, \"MSFT\": 0.3, \"GOOGL\": 0.4}'")
                return {"status": "error"}
        else:
            targets = targets_raw

        if not targets:
            echo_error("No targets specified. Use --param targets='{\"AAPL\":0.5,\"MSFT\":0.5}'")
            return {"status": "error"}

        total_alloc = sum(targets.values())
        if abs(total_alloc - 1.0) > 0.01:
            echo_warn(f"Target allocations sum to {total_alloc:.2f} (should be ~1.0)")

        acct = self.get_account()
        portfolio_value = float(acct.portfolio_value)
        echo_info(f"Portfolio value: ${portfolio_value:,.2f}")

        results = {"trades": [], "portfolio_value": portfolio_value}

        for symbol, target_pct in targets.items():
            target_value = portfolio_value * target_pct
            current_pos = self.get_position(symbol)
            current_value = float(current_pos.market_value) if current_pos else 0

            diff = target_value - current_value

            if abs(diff) < 10:  # Skip tiny adjustments
                echo_info(f"{symbol}: on target (diff: ${diff:,.2f})")
                continue

            try:
                if diff > 0:
                    echo_info(f"{symbol}: need to buy ${diff:,.2f} more")
                    req = MarketOrderRequest(
                        symbol=symbol.upper(),
                        notional=round(diff, 2),
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY,
                    )
                    order = self.client.submit_order(req)
                    results["trades"].append({"symbol": symbol, "action": "buy", "amount": diff})
                    echo_success(f"Buy order placed for {symbol}")
                else:
                    # Need to sell
                    sell_value = abs(diff)
                    if current_pos:
                        current_qty = float(current_pos.qty)
                        current_price = float(current_pos.current_price) if current_pos.current_price else 1
                        sell_qty = min(current_qty, sell_value / current_price)
                        if sell_qty > 0:
                            echo_info(f"{symbol}: need to sell {sell_qty:.2f} units")
                            self.sell(symbol, sell_qty)
                            results["trades"].append({"symbol": symbol, "action": "sell", "qty": sell_qty})
                            echo_success(f"Sell order placed for {symbol}")
            except APIError as e:
                echo_error(f"Rebalance failed for {symbol}: {e}")

        return results


# Strategy registry
BUILTIN_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "dca": DCAStrategy,
    "rsi": RSIStrategy,
    "rebalance": RebalanceStrategy,
}


# ── CLI Commands ──────────────────────────────────────────────────────


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def strategy(ctx: click.Context, json_mode: bool) -> None:
    """Run and manage trading strategies."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@strategy.command("list")
@click.pass_context
def list_strategies(ctx: click.Context) -> None:
    """List all available strategies (built-in + custom)."""
    json_mode = ctx.obj.get("json", False)

    rows = []
    for name, cls in BUILTIN_STRATEGIES.items():
        rows.append({"name": name, "description": cls.description, "type": "built-in"})

    # Scan custom strategies dir
    strategies_dir = get_strategies_dir()
    if strategies_dir.exists():
        for f in strategies_dir.glob("*.py"):
            if f.name.startswith("_"):
                continue
            rows.append({"name": f.stem, "description": f"Custom strategy ({f.name})", "type": "custom"})

    if json_mode:
        format_json(rows)
        return

    format_table(
        rows,
        columns=["name", "type", "description"],
        headers=["Name", "Type", "Description"],
        title="Available Strategies",
    )


@strategy.command("run")
@click.argument("name")
@click.option("--param", "-p", multiple=True, help="Strategy param as key=value (repeatable)")
@click.pass_context
def run_strategy(ctx: click.Context, name: str, param: tuple[str, ...]) -> None:
    """Run a strategy by name.

    Example:
        alpaca strategy run dca -p symbol=AAPL -p amount=100
        alpaca strategy run rsi -p symbol=BTC/USD -p period=14 -p oversold=30
        alpaca strategy run rebalance -p 'targets={"AAPL":0.4,"MSFT":0.3,"GOOGL":0.3}'
    """
    json_mode = ctx.obj.get("json", False)

    # Parse params
    params: dict = {}
    for p in param:
        if "=" in p:
            key, value = p.split("=", 1)
            params[key.strip()] = value.strip()
        else:
            echo_error(f"Invalid param format '{p}'. Use key=value")
            return

    client = get_trading_client()

    # Try built-in first
    if name in BUILTIN_STRATEGIES:
        strat = BUILTIN_STRATEGIES[name](client, params)
        echo_info(f"Running strategy: {strat.description}")
        result = strat.run()
        if json_mode:
            format_json(result)
        return

    # Try custom strategy
    strategies_dir = get_strategies_dir()
    custom_file = strategies_dir / f"{name}.py"
    if custom_file.exists():
        try:
            spec = importlib.util.spec_from_file_location(f"strategy_{name}", custom_file)
            module = importlib.util.module_from_spec(spec)

            # Inject BaseStrategy into module namespace
            module.BaseStrategy = BaseStrategy  # type: ignore[attr-defined]
            spec.loader.exec_module(module)

            # Look for a class that extends BaseStrategy
            strat_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                ):
                    strat_cls = attr
                    break

            if strat_cls is None:
                echo_error(f"No strategy class found in {custom_file}")
                return

            strat = strat_cls(client, params)
            echo_info(f"Running custom strategy: {strat.description}")
            result = strat.run()
            if json_mode:
                format_json(result)
        except Exception as e:
            echo_error(f"Failed to run custom strategy '{name}': {e}")
    else:
        echo_error(f"Strategy '{name}' not found. Use 'alpaca strategy list' to see available strategies.")


@strategy.command("init")
@click.argument("name")
@click.pass_context
def init_strategy(ctx: click.Context, name: str) -> None:
    """Create a new custom strategy template.

    Example: alpaca strategy init my_strategy
    """
    strategies_dir = get_strategies_dir()
    strategies_dir.mkdir(parents=True, exist_ok=True)

    filepath = strategies_dir / f"{name}.py"
    if filepath.exists():
        echo_error(f"Strategy '{name}' already exists at {filepath}")
        return

    template = f'''"""Custom strategy: {name}

This strategy was created with 'alpaca strategy init {name}'.
Edit the run() method to implement your trading logic.
"""


class {name.title().replace("_", "")}Strategy(BaseStrategy):
    """Your custom strategy description here."""

    name = "{name}"
    description = "Custom strategy: {name}"

    def run(self) -> dict:
        """Execute the strategy.

        Available helpers:
            self.client     - Alpaca TradingClient
            self.params     - Dict of --param key=value pairs
            self.buy(symbol, qty)
            self.sell(symbol, qty)
            self.get_position(symbol)
            self.get_account()

        Returns:
            Dict with results/summary.
        """
        # Example: get a parameter
        symbol = self.params.get("symbol", "SPY")

        # Example: check current position
        pos = self.get_position(symbol)
        if pos:
            print(f"Current position in {{symbol}}: {{pos.qty}} shares")

        # TODO: Implement your strategy logic here
        return {{"status": "not_implemented"}}
'''

    filepath.write_text(template)
    echo_success(f"Strategy template created: {filepath}")
    echo_info("Edit the file and run with: alpaca strategy run " + name)


@strategy.command("show")
@click.argument("name")
@click.pass_context
def show_strategy(ctx: click.Context, name: str) -> None:
    """Show the source code of a custom strategy."""
    strategies_dir = get_strategies_dir()
    filepath = strategies_dir / f"{name}.py"

    if not filepath.exists():
        # Check built-in
        if name in BUILTIN_STRATEGIES:
            echo_info(f"'{name}' is a built-in strategy: {BUILTIN_STRATEGIES[name].description}")
            return
        echo_error(f"Strategy '{name}' not found")
        return

    click.echo(filepath.read_text())
