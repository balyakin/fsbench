from app import solve


def test_adds_negative_numbers() -> None:
    assert solve(-5, 2) == -3
