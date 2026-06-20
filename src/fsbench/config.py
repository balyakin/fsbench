"""Configuration loading for fsbench."""

import tomllib
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from fsbench.errors import ConfigurationError
from fsbench.models import FsbenchSettings


def load_settings(path: Optional[Path] = None) -> FsbenchSettings:
    """Loads `fsbench.toml` and validates it.

    Args:
        path: Optional path to a TOML settings file.

    Returns:
        Validated fsbench settings.

    Raises:
        ConfigurationError: If the TOML cannot be parsed or validated.
    """
    settings_path = path if path is not None else Path("fsbench.toml")
    if not settings_path.exists():
        return FsbenchSettings()

    try:
        with settings_path.open("rb") as handle:
            data = tomllib.load(handle)
        return FsbenchSettings.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigurationError(f"invalid settings file: {settings_path}") from error
