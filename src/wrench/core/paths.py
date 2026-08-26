"""FR-11.2: Platform path abstraction via platformdirs."""

from pathlib import Path

import platformdirs

APP_NAME = "wrench"


def data_dir() -> Path:
    """Where Wrench stores its own data (DB, snapshot archives)."""
    return Path(platformdirs.user_data_dir(APP_NAME))


def config_dir() -> Path:
    """Where Wrench stores user configuration."""
    return Path(platformdirs.user_config_dir(APP_NAME))


def state_dir() -> Path:
    """Where Wrench stores runtime state (log files, etc)."""
    return Path(platformdirs.user_state_dir(APP_NAME))
