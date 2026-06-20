import pytest

from fsbench.checks.custom import custom_check_disabled
from fsbench.errors import CheckExecutionError


async def test_custom_check_disabled_raises() -> None:
    # ARRANGE / ACT / ASSERT
    with pytest.raises(CheckExecutionError):
        await custom_check_disabled()
