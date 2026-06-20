from pathlib import Path

from fsbench.adapters.claude import ClaudeAdapter


def test_claude_usage_parser() -> None:
    # ARRANGE
    text = Path("tests/adapters/fixtures/claude_response.json").read_text(encoding="utf-8")
    adapter = ClaudeAdapter()

    # ACT
    usage = adapter.parse_usage(text, "")

    # ASSERT
    assert usage.tokens_in == 88
    assert usage.tokens_out == 12
    assert usage.cost_usd == 0.021
