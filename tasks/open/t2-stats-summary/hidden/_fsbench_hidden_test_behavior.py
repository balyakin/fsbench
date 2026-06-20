from app import solve


def test_empty_summary() -> None:
    assert solve([]) == {"min": 0, "max": 0, "mean": 0.0}
