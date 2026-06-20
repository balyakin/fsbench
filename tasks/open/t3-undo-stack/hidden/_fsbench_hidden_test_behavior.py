from app import solve


def test_new_edit_clears_redo() -> None:
    ops = [("append", "a"), ("append", "b"), ("undo", ""), ("append", "c"), ("redo", "")]
    assert solve(ops) == "ac"
