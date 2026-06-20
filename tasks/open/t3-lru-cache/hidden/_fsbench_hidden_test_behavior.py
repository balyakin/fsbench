from app import solve


def test_update_refreshes_key() -> None:
    ops = [("put", 1, 1), ("put", 1, 2), ("put", 2, 2), ("put", 3, 3), ("get", 1, None)]
    assert solve(ops, 2) == [-1]
