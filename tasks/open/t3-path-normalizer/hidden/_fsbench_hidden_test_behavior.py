from app import solve


def test_clamps_root() -> None:
    assert solve("/../../a") == "/a"
