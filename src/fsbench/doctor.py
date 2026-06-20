"""Doctor checks and environment manifest hashing."""

import asyncio
import hashlib
import importlib.metadata
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from fsbench.adapters.registry import resolve_adapter_target
from fsbench.models import AgentEnvMode, FsbenchSettings, SandboxKind
from fsbench.sandbox.environment import binary_path, resolved_utf8_locale, safe_path
from fsbench.store import canonical_json

RUNTIME_DEPENDENCIES = ["pydantic", "typer", "PyYAML", "Jinja2", "structlog", "psutil", "aiosqlite"]


class DoctorItem(BaseModel):
    """Stores one doctor check row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: str
    detail: str
    required: bool


class DoctorResult(BaseModel):
    """Stores all doctor rows and overall success."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    items: List[DoctorItem]


async def run_doctor(settings: FsbenchSettings, agents: Sequence[str]) -> DoctorResult:
    """Runs fsbench doctor checks without starting benchmarks."""
    items: List[DoctorItem] = []
    python_ok = sys.version_info.major == 3 and sys.version_info.minor >= 12
    items.append(
        DoctorItem(
            name="python",
            status="ok" if python_ok else "fail",
            detail=sys.version.split()[0],
            required=True,
        )
    )
    for dependency in RUNTIME_DEPENDENCIES:
        version = _dependency_version(dependency)
        items.append(
            DoctorItem(
                name=dependency,
                status="ok" if version != "missing" else "fail",
                detail=version,
                required=True,
            )
        )
    locale_ok = await locale_available(resolved_utf8_locale())
    items.append(
        DoctorItem(
            name="locale",
            status="ok" if locale_ok else "fail",
            detail=resolved_utf8_locale(),
            required=True,
        )
    )
    for binary in ["ruff", "mypy", "pytest"]:
        status, detail = await binary_status(binary)
        items.append(DoctorItem(name=binary, status=status, detail=detail, required=True))
    if settings.sandbox == SandboxKind.BWRAP:
        status, detail = await binary_status("bwrap")
        items.append(DoctorItem(name="bwrap", status=status, detail=detail, required=True))
    else:
        items.append(
            DoctorItem(name=f"sandbox:{settings.sandbox.value}", status="ok", detail="selected", required=True)
        )
    for agent in sorted(agents):
        target = resolve_adapter_target(agent, settings.agents)
        adapter_name = target[0]
        if adapter_name == "oracle":
            items.append(DoctorItem(name=f"agent:{agent}", status="ok", detail="built-in", required=False))
            continue
        status, detail = await binary_status(adapter_name, search_path=_agent_search_path(settings))
        status = "skip" if status == "fail" else status
        items.append(DoctorItem(name=f"agent:{agent}", status=status, detail=detail, required=False))
    ok = all(item.status == "ok" for item in items if item.required)
    return DoctorResult(ok=ok, items=items)


async def binary_status(binary: str, search_path: Optional[str] = None) -> Tuple[str, str]:
    """Returns binary availability and safe version detail."""
    path = binary_path(binary, search_path)
    if path is None:
        return "fail", "not found"
    version = await probe_binary_version(path, ["--version"])
    return "ok", f"{path} {version}"


async def _communicate_with_timeout(
    process: asyncio.subprocess.Process,
    timeout_s: float,
) -> Tuple[bytes, bytes]:
    try:
        output = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError as error:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise error
    stdout = output[0]
    stderr = output[1]
    return stdout, stderr


async def probe_binary_version(path: str, args: Sequence[str]) -> str:
    """Runs a safe version probe and returns a short string."""
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            *args,
            env={"PATH": safe_path()},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output = await _communicate_with_timeout(process, 10)
        stdout = output[0]
        stderr = output[1]
    except (OSError, asyncio.TimeoutError):
        return "version_unknown"
    text = (stdout + stderr).decode("utf-8", errors="replace").strip().splitlines()
    if not text:
        return "version_unknown"
    return text[0][:200]


async def locale_available(locale_name: str) -> bool:
    """Checks whether the selected UTF-8 locale is available."""
    locale_binary = binary_path("locale")
    if locale_binary is None:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            locale_binary,
            "-a",
            env={"PATH": safe_path()},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output = await _communicate_with_timeout(process, 5)
        stdout = output[0]
    except (OSError, asyncio.TimeoutError):
        return False
    locales = {line.strip().lower() for line in stdout.decode("utf-8", errors="replace").splitlines()}
    return locale_name.lower() in locales or locale_name.lower().replace("-", "") in locales


async def build_env_manifest(settings: FsbenchSettings, agents: Sequence[str]) -> Dict[str, str]:
    """Builds the public environment manifest used for resume hashing."""
    manifest: Dict[str, str] = {
        "agent_env": settings.agent_env.value,
        "python": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "resolved_utf8_locale": resolved_utf8_locale(),
        "sandbox": settings.sandbox.value,
    }
    for dependency in RUNTIME_DEPENDENCIES:
        manifest[f"dependency:{dependency}"] = _dependency_version(dependency)
    for binary in ["ruff", "mypy", "pytest"]:
        await _add_binary_manifest(manifest, prefix=f"binary:{binary}", binary=binary)
    if settings.sandbox == SandboxKind.BWRAP:
        await _add_binary_manifest(manifest, prefix="binary:bwrap", binary="bwrap")
    for agent in sorted(agents):
        target = resolve_adapter_target(agent, settings.agents)
        adapter_name = target[0]
        model = target[1]
        manifest[f"agent:{agent}:adapter"] = adapter_name
        if model is not None:
            manifest[f"agent:{agent}:model"] = model
        if adapter_name == "oracle":
            manifest[f"agent:{agent}:path"] = "built-in"
            manifest[f"agent:{agent}:version"] = "oracle"
            continue
        await _add_binary_manifest(
            manifest,
            prefix=f"agent:{agent}",
            binary=adapter_name,
            search_path=_agent_search_path(settings),
        )
    return manifest


async def build_env_manifest_hash(settings: FsbenchSettings, agents: Sequence[str]) -> str:
    """Builds the sha256 hash of the environment manifest."""
    return hashlib.sha256(canonical_json(await build_env_manifest(settings, agents)).encode("utf-8")).hexdigest()


def _agent_search_path(settings: FsbenchSettings) -> Optional[str]:
    if settings.agent_env == AgentEnvMode.HOST:
        return os.environ.get("PATH")
    return None


async def _add_binary_manifest(
    manifest: Dict[str, str],
    prefix: str,
    binary: str,
    search_path: Optional[str] = None,
) -> None:
    path = binary_path(binary, search_path)
    manifest[f"{prefix}:path"] = path or "missing"
    manifest[f"{prefix}:version"] = "missing" if path is None else await probe_binary_version(path, ["--version"])


def _dependency_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"
