from app import solve


def test_question_mark_and_blank_value() -> None:
    assert solve("?empty=&flag") == {"empty": "", "flag": ""}
