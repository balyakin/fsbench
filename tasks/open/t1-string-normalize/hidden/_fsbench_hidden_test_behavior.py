from app import solve


def test_empty_and_mixed_case() -> None:
    assert solve("  MiXeD  ") == "mixed"
