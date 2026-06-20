from app import solve


def test_zero_days() -> None:
    assert solve("2026-01-01", 0) == []
