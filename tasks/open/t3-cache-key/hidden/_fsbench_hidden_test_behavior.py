from app import solve


def test_nested_stable_key() -> None:
    assert solve({"z": [2, 1], "a": {"b": 1, "a": 2}}) == '{"a":{"a":2,"b":1},"z":[2,1]}'
