from pathlib import Path

from fsbench.adapters.pi import PiAdapter


def test_pi_build_argv() -> None:
    # ARRANGE
    adapter = PiAdapter()

    # ACT
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert argv == [
        "pi",
        "-p",
        "--mode",
        "json",
        "--approve",
        "--no-session",
        "Fix the task",
    ]


def test_pi_usage_parser() -> None:
    # ARRANGE
    adapter = PiAdapter()

    # ACT
    usage = adapter.parse_usage('{"usage":{"input_tokens":10,"output_tokens":5,"cost_usd":0.01}}', "")

    # ASSERT
    assert usage.tokens_in == 10
    assert usage.tokens_out == 5
    assert usage.cost_usd == 0.01


def test_pi_build_argv_with_model() -> None:
    # ARRANGE
    adapter = PiAdapter(name="pi_kimi25", model="kimi-k2.5")

    # ACT
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert adapter.name == "pi_kimi25"
    assert argv == [
        "pi",
        "-p",
        "--mode",
        "json",
        "--model",
        "kimi-k2.5",
        "--approve",
        "--no-session",
        "Fix the task",
    ]
