from pathlib import Path

import pytest

from fsbench.logging import SecretScrubber
from fsbench.models import AgentEnvMode, EgressSettings, FsbenchSettings, ProviderProfile
from fsbench.sandbox.environment import build_agent_env, build_check_env


def test_build_agent_env_uses_allowlisted_provider_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ARRANGE
    monkeypatch.setenv("FSBENCH_TEST_TOKEN", "secret-value")
    scrubber = SecretScrubber()
    profile = ProviderProfile(env_allowlist=["FSBENCH_TEST_TOKEN"], required_env=["FSBENCH_TEST_TOKEN"])

    # ACT
    env = build_agent_env(tmp_path, FsbenchSettings(), profile, scrubber)

    # ASSERT
    assert env["FSBENCH_TEST_TOKEN"] == "secret-value"
    assert scrubber.scrub_text("secret-value") == "<FSBENCH_TEST_TOKEN>"


def test_build_agent_env_strict_egress_blocks_provider_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ARRANGE
    monkeypatch.setenv("FSBENCH_TEST_TOKEN", "secret-value")
    monkeypatch.setenv("FSBENCH_TEST_BASE_URL", "https://example.invalid")
    scrubber = SecretScrubber()
    profile = ProviderProfile(
        env_allowlist=["FSBENCH_TEST_TOKEN"],
        required_env=["FSBENCH_TEST_TOKEN"],
        base_url_env="FSBENCH_TEST_BASE_URL",
    )
    settings = FsbenchSettings(egress=EgressSettings(strict=True))

    # ACT
    env = build_agent_env(tmp_path, settings, profile, scrubber)

    # ASSERT
    assert "FSBENCH_TEST_TOKEN" not in env
    assert env["FSBENCH_TEST_BASE_URL"] == "https://example.invalid"
    assert scrubber.scrub_text("secret-value") == "<FSBENCH_TEST_TOKEN>"


def test_build_agent_env_host_uses_process_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ARRANGE
    monkeypatch.setenv("HOME", "/tmp/fsbench-real-home")
    monkeypatch.setenv("FSBENCH_TEST_API_KEY", "host-secret-value")
    scrubber = SecretScrubber()
    settings = FsbenchSettings(agent_env=AgentEnvMode.HOST)

    # ACT
    env = build_agent_env(tmp_path, settings, None, scrubber)

    # ASSERT
    assert env["HOME"] == "/tmp/fsbench-real-home"
    assert env["FSBENCH_TEST_API_KEY"] == "host-secret-value"
    assert scrubber.scrub_text("host-secret-value") == "<FSBENCH_TEST_API_KEY>"


def test_build_check_env_has_seed(tmp_path: Path) -> None:
    # ARRANGE
    seed = 123

    # ACT
    env = build_check_env(tmp_path, seed)

    # ASSERT
    assert env["HYPOTHESIS_SEED"] == "123"
