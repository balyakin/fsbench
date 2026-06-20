from pathlib import Path

from fsbench.adapters.codex import CodexAdapter


def test_codex_usage_parser() -> None:
    # ARRANGE
    text = Path("tests/adapters/fixtures/codex_usage_event.jsonl").read_text(encoding="utf-8")
    adapter = CodexAdapter()

    # ACT
    usage = adapter.parse_usage(text, "")

    # ASSERT
    assert usage.tokens_in == 123
    assert usage.tokens_out == 45
    assert usage.cost_usd == 0.067


def test_codex_invalid_usage_does_not_crash() -> None:
    # ARRANGE
    adapter = CodexAdapter()

    # ACT
    usage = adapter.parse_usage("not-json", "")

    # ASSERT
    assert usage.cost_usd is None


def test_codex_build_argv_with_model() -> None:
    # ARRANGE
    adapter = CodexAdapter(name="codex_kimi25", model="kimi-k2.5")

    # ACT
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert adapter.name == "codex_kimi25"
    assert argv == [
        "codex",
        "exec",
        "--model",
        "kimi-k2.5",
        "--json",
        "--sandbox",
        "workspace-write",
        "--approval-policy",
        "never",
        "Fix the task",
    ]
