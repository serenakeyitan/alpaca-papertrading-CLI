"""Configuration commands – set up API keys and preferences."""

import click

from alpaca_cli.utils.config import (
    load_config,
    save_config,
    get_api_key,
    get_secret_key,
    get_strategies_dir,
    CONFIG_DIR,
    CONFIG_FILE,
    ENV_FILE,
    validate_keys,
)
from alpaca_cli.utils.output import echo_success, echo_error, echo_info


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON")
@click.pass_context
def configure(ctx: click.Context, json_mode: bool) -> None:
    """Configure API keys and CLI settings."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode


@configure.command("init")
def init_config() -> None:
    """Interactive configuration setup.

    Creates ~/.alpaca-cli/ directory with config and .env file.
    """
    echo_info("Setting up Alpaca Paper Trading CLI...")
    echo_info(f"Config directory: {CONFIG_DIR}")
    click.echo()

    api_key = click.prompt("Alpaca API Key", default=get_api_key() or "")
    secret_key = click.prompt("Alpaca Secret Key", hide_input=True, default="")
    default_asset = click.prompt(
        "Default asset class",
        type=click.Choice(["us_equity", "crypto"]),
        default="us_equity",
    )

    # Save to config
    config = load_config()
    config["api_key"] = api_key
    config["secret_key"] = secret_key
    config["default_asset_class"] = default_asset
    save_config(config)

    # Also create .env file
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    env_content = (
        f"ALPACA_API_KEY={api_key}\n"
        f"ALPACA_SECRET_KEY={secret_key}\n"
    )
    ENV_FILE.write_text(env_content)

    # Create strategies directory
    strat_dir = get_strategies_dir()
    strat_dir.mkdir(parents=True, exist_ok=True)

    echo_success("Configuration saved!")
    echo_info(f"  Config file: {CONFIG_FILE}")
    echo_info(f"  Env file:    {ENV_FILE}")
    echo_info(f"  Strategies:  {strat_dir}")
    echo_info(f"  Asset class: {default_asset}")
    echo_info(f"  API Key:     ****{api_key[-4:] if len(api_key) > 4 else '****'}")

    # Test connection
    click.echo()
    echo_info("Testing connection...")
    try:
        from alpaca_cli.utils.client import get_trading_client

        client = get_trading_client()
        acct = client.get_account()
        echo_success(f"Connected! Account: {acct.account_number} (Status: {acct.status.value})")
        echo_info(f"Equity: ${float(acct.equity):,.2f}")
    except Exception as e:
        echo_error(f"Connection failed: {e}")
        echo_info("Check your API keys and try again.")


@configure.command("show")
def show_config() -> None:
    """Show current configuration."""
    config = load_config()
    if not config:
        echo_info("No configuration found. Run 'alpaca configure init' to set up.")
        return

    echo_info("Current configuration:")
    for key, value in config.items():
        if key in ("api_key", "secret_key") and value:
            masked = "****" + value[-4:] if len(value) > 4 else "****"
            click.echo(f"  {key}: {masked}")
        else:
            click.echo(f"  {key}: {value or '(not set)'}")

    click.echo(f"\n  Config dir:  {CONFIG_DIR}")
    click.echo(f"  Config file: {CONFIG_FILE}")
    click.echo(f"  Env file:    {ENV_FILE}")
    click.echo(f"  Strategies:  {get_strategies_dir()}")


@configure.command("set")
@click.argument("key", type=click.Choice(["api_key", "secret_key", "default_asset_class", "strategies_dir"]))
@click.argument("value")
def set_config(key: str, value: str) -> None:
    """Set a configuration value.

    Example: alpaca configure set default_asset_class crypto
    """
    config = load_config()
    config[key] = value
    save_config(config)
    display_value = f"****{value[-4:]}" if "key" in key.lower() and len(value) > 4 else value
    echo_success(f"Set '{key}' = '{display_value}'")


@configure.command("test")
def test_connection() -> None:
    """Test the Alpaca API connection."""
    valid, msg = validate_keys()
    if not valid:
        echo_error(msg)
        return

    try:
        from alpaca_cli.utils.client import get_trading_client

        client = get_trading_client()
        acct = client.get_account()

        echo_success("Connection successful!")
        echo_info(f"  Account:    {acct.account_number}")
        echo_info(f"  Status:     {acct.status.value}")
        echo_info(f"  Equity:     ${float(acct.equity):,.2f}")
        echo_info(f"  Cash:       ${float(acct.cash):,.2f}")
        echo_info(f"  Buy Power:  ${float(acct.buying_power):,.2f}")
        echo_info(f"  PDT:        {acct.pattern_day_trader}")
    except Exception as e:
        echo_error(f"Connection failed: {e}")
