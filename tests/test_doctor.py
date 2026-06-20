import asyncio

from fsbench import doctor as doctor_module
from fsbench.config import load_settings
from fsbench.doctor import build_env_manifest, build_env_manifest_hash, run_doctor
from fsbench.models import AgentEnvMode


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


async def test_doctor_oracle_only() -> None:
    # ARRANGE
    settings = load_settings()

    # ACT
    result = await run_doctor(settings, ["oracle"])

    # ASSERT
    assert result.ok is True
    assert any(item.name == "agent:oracle" for item in result.items)


async def test_env_manifest_hash_is_stable() -> None:
    # ARRANGE
    settings = load_settings()

    # ACT
    first = await build_env_manifest_hash(settings, ["oracle"])
    second = await build_env_manifest_hash(settings, ["oracle"])

    # ASSERT
    assert first == second


async def test_env_manifest_uses_agent_alias_target(monkeypatch) -> None:
    # ARRANGE
    settings = load_settings().model_copy(update={"agents": {"pi_kimi25": "pi:kimi-k2.5"}})

    async def fake_probe_binary_version(path: str, args) -> str:
        return "1.0.0"

    monkeypatch.setattr(doctor_module, "binary_path", lambda binary: f"/bin/{binary}")
    monkeypatch.setattr(doctor_module, "probe_binary_version", fake_probe_binary_version)
    monkeypatch.setattr(doctor_module, "_dependency_version", lambda name: "installed")

    # ACT
    manifest = await build_env_manifest(settings, ["pi_kimi25"])

    # ASSERT
    assert manifest["agent:pi_kimi25:adapter"] == "pi"
    assert manifest["agent:pi_kimi25:model"] == "kimi-k2.5"
    assert manifest["agent:pi_kimi25:path"] == "/bin/pi"


async def test_env_manifest_includes_agent_env() -> None:
    # ARRANGE
    settings = load_settings().model_copy(update={"agent_env": AgentEnvMode.HOST})

    # ACT
    manifest = await build_env_manifest(settings, ["oracle"])

    # ASSERT
    assert manifest["agent_env"] == "host"


async def test_probe_binary_version_kills_process_on_timeout(monkeypatch) -> None:
    # ARRANGE
    process = _TimeoutProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    async def fake_wait_for(coroutine, timeout: float):
        coroutine.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(doctor_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(doctor_module.asyncio, "wait_for", fake_wait_for)

    # ACT
    version = await doctor_module.probe_binary_version("binary", ["--version"])

    # ASSERT
    assert version == "version_unknown"
    assert process.killed is True
    assert process.waited is True
