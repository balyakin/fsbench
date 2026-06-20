from pathlib import Path

from fsbench.adapters.aider import AiderAdapter


def test_aider_usage_parser() -> None:
    # ARRANGE
    text = Path("tests/adapters/fixtures/aider_token_line.txt").read_text(encoding="utf-8")
    adapter = AiderAdapter()

    # ACT
    usage = adapter.parse_usage(text, "")

    # ASSERT
    assert usage.tokens_in == 100
    assert usage.tokens_out == 40
    assert usage.cost_usd == 0.034
