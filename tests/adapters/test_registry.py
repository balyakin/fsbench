from pathlib import Path

import pytest

from fsbench.adapters.opencode import OpencodeAdapter
from fsbench.adapters.pi import PiAdapter
from fsbench.adapters.registry import (
    available_adapter_names,
    get_adapter_for_task,
    get_real_adapter,
    resolve_adapter_target,
)
from fsbench.errors import ConfigurationError


def test_registry_includes_opencode_and_pi() -> None:
    # ARRANGE
    adapter_names = available_adapter_names()

    # ACT
    has_opencode = "opencode" in adapter_names
    has_pi = "pi" in adapter_names

    # ASSERT
    assert has_opencode is True
    assert has_pi is True


def test_registry_returns_opencode_adapter() -> None:
    # ARRANGE
    adapter_name = "opencode"

    # ACT
    adapter = get_real_adapter(adapter_name)

    # ASSERT
    assert isinstance(adapter, OpencodeAdapter)


def test_registry_returns_pi_adapter() -> None:
    # ARRANGE
    adapter_name = "pi"

    # ACT
    adapter = get_adapter_for_task(adapter_name, Path("solution"))

    # ASSERT
    assert isinstance(adapter, PiAdapter)


def test_registry_rejects_unknown_adapter() -> None:
    # ARRANGE
    adapter_name = "missing"

    # ACT
    with pytest.raises(ConfigurationError):
        get_real_adapter(adapter_name)


def test_registry_resolves_alias_with_model() -> None:
    # ARRANGE
    agent_aliases = {"pi_kimi25": "pi:kimi-k2.5"}

    # ACT
    adapter = get_real_adapter("pi_kimi25", agent_aliases)
    argv = adapter.build_argv("Fix the task", Path("workspace"))

    # ASSERT
    assert isinstance(adapter, PiAdapter)
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


def test_registry_resolves_model_with_colon() -> None:
    # ARRANGE
    agent_aliases = {"pi_sonnet_high": "pi:sonnet:high"}

    # ACT
    target = resolve_adapter_target("pi_sonnet_high", agent_aliases)

    # ASSERT
    assert target == ("pi", "sonnet:high")
