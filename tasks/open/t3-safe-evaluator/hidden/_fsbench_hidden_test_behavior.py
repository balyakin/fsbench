import pytest
from app import solve


def test_rejects_calls() -> None:
    with pytest.raises(ValueError):
        solve('__import__("os").system("true")')
