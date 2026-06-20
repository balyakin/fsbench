import pytest
from app import solve


def test_cycle_raises() -> None:
    with pytest.raises(ValueError):
        solve({"a": ["b"], "b": ["a"]})
