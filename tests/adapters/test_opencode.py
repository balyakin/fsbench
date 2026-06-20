from pathlib import Path

from fsbench.adapters.opencode import OpencodeAdapter


def test_opencode_build_argv() -> None:
    # ARRANGE
    adapter = OpencodeAdapter()

    # ACT
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert argv == [
        "opencode",
        "run",
        "--format",
        "json",
        "--dangerously-skip-permissions",
        "Fix the task",
    ]


def test_opencode_usage_parser() -> None:
    # ARRANGE
    adapter = OpencodeAdapter()

    # ACT
    usage = adapter.parse_usage('{"usage":{"input_tokens":10,"output_tokens":5,"cost_usd":0.01}}', "")

    # ASSERT
    assert usage.tokens_in == 10
    assert usage.tokens_out == 5
    assert usage.cost_usd == 0.01


def test_opencode_build_argv_with_model() -> None:
    # ARRANGE
    adapter = OpencodeAdapter(name="opencode_kimi25", model="moonshot/kimi-k2.5")

    # ACT
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert adapter.name == "opencode_kimi25"
    assert argv == [
        "opencode",
        "run",
        "--model",
        "moonshot/kimi-k2.5",
        "--format",
        "json",
        "--dangerously-skip-permissions",
        "Fix the task",
    ]
