from app import solve


def test_default_quantity_and_rounding() -> None:
    assert solve([{"price": 1.005, "quantity": 2}, {"price": 2.0}]) == 4.01
