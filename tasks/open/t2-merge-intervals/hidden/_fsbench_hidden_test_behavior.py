from app import solve


def test_touching_intervals_merge() -> None:
    assert solve([(1, 2), (2, 3), (10, 11)]) == [(1, 3), (10, 11)]
