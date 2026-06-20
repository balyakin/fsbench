import asyncio

from fsbench.adapters import base as base_module
from fsbench.adapters.base import CliAgentAdapter
from fsbench.adapters.codex import CodexAdapter
from fsbench.logging import SecretScrubber


class _VersionAdapter(CliAgentAdapter):
    name = "version"
    provider_name = "version"
    binary = "version"

    def build_argv(self, prompt: str, workspace_root):
        return []


class _TimeoutProcess:
    def __init__(self) -> None:
        self.killed = False
        self.waited = False

    async def communicate(self):
        return b"", b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        self.waited = True


async def test_missing_real_adapter_smoke_skips() -> None:
    # ARRANGE
    adapter = CodexAdapter()

    # ACT
    available, reason = await adapter.smoke_test(env={}, provider_profile=None)

    # ASSERT
    assert available is False
    assert "not found" in reason


async def test_cli_adapter_version_kills_process_on_timeout(monkeypatch) -> None:
    # ARRANGE
    adapter = _VersionAdapter()
    process = _TimeoutProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    async def fake_wait_for(coroutine, timeout: float):
        coroutine.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(base_module, "binary_path", lambda binary: "/bin/version")
    monkeypatch.setattr(base_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(base_module.asyncio, "wait_for", fake_wait_for)

    # ACT
    version = await adapter.version(env={}, scrubber=SecretScrubber())

    # ASSERT
    assert version == "version_unknown"
    assert process.killed is True
    assert process.waited is True
