"""Configuration management for alpaca-cli.

Resolution order:
  1. .env file in project directory or ~/.alpaca-cli/.env
  2. Environment variables (ALPACA_API_KEY, ALPACA_SECRET_KEY)
  3. ~/.alpaca-cli/config.json
"""

import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]


CONFIG_DIR = Path.home() / ".alpaca-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
ENV_FILE = CONFIG_DIR / ".env"

# Paper trading base URL (hardcoded for safety)
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"


def _load_env() -> None:
    """Load environment variables from .env files."""
    if load_dotenv is None:
        return

    # Try project-local .env first, then global
    local_env = Path.cwd() / ".env"
    if local_env.exists():
        load_dotenv(local_env)
    elif ENV_FILE.exists():
        load_dotenv(ENV_FILE)


def load_config() -> dict[str, Any]:
    """Load configuration from ~/.alpaca-cli/config.json."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to ~/.alpaca-cli/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_api_key() -> str:
    """Get Alpaca API key. Resolution: env -> config -> empty."""
    _load_env()
    config = load_config()
    return (
        os.environ.get("ALPACA_API_KEY")
        or config.get("api_key")
        or ""
    )


def get_secret_key() -> str:
    """Get Alpaca secret key. Resolution: env -> config -> empty."""
    _load_env()
    config = load_config()
    return (
        os.environ.get("ALPACA_SECRET_KEY")
        or config.get("secret_key")
        or ""
    )


def get_default_asset_class() -> str:
    """Get default asset class (us_equity or crypto)."""
    config = load_config()
    return config.get("default_asset_class", "us_equity")


def get_strategies_dir() -> Path:
    """Get the directory for custom strategies."""
    config = load_config()
    custom = config.get("strategies_dir")
    if custom:
        return Path(custom)
    return CONFIG_DIR / "strategies"


def validate_keys() -> tuple[bool, str]:
    """Check if API keys are configured. Returns (valid, message)."""
    api_key = get_api_key()
    secret_key = get_secret_key()
    if not api_key or not secret_key:
        return False, (
            "API keys not configured. Run 'alpaca configure init' or "
            "set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables."
        )
    return True, "OK"
