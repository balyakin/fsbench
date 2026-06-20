"""Custom check placeholder for v1.0 trusted tasks."""

from fsbench.errors import CheckExecutionError


async def custom_check_disabled() -> None:
    """Raises because custom task checks are disabled in the MVP."""
    raise CheckExecutionError("custom checks are disabled in fsbench MVP")
