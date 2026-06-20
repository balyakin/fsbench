from app import solve


def test_empty_average() -> None:
    assert solve([]) == 0.0
