"""Base classes and helpers for CLI agent adapters."""

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, Optional, Protocol, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from fsbench.errors import AdapterUnavailableError
from fsbench.logging import SecretScrubber
from fsbench.models import AgentResult, Limits, ProviderProfile, RunErrorKind
from fsbench.sandbox.base import SandboxContext
from fsbench.sandbox.environment import binary_path


class Usage(BaseModel):
    """Stores best-effort cost and token usage parsed from an adapter output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cost_usd: Optional[float] = Field(default=None, ge=0.0)
    tokens_in: Optional[int] = Field(default=None, ge=0)
    tokens_out: Optional[int] = Field(default=None, ge=0)


class AgentAdapter(Protocol):
    """Describes an agent adapter."""

    name: str
    provider_name: str

    async def available(self) -> Tuple[bool, str]:
        """Checks adapter binary or local implementation availability."""

    async def smoke_test(self, env: Dict[str, str], provider_profile: Optional[ProviderProfile]) -> Tuple[bool, str]:
        """Checks adapter availability without making a benchmark run."""

    async def version(self, env: Dict[str, str], scrubber: SecretScrubber) -> str:
        """Returns a scrubbed adapter version string."""

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds the agent command line."""

    async def run(
        self,
        sandbox_context: SandboxContext,
        workspace_root: Path,
        env: Dict[str, str],
        timeout_s: int,
        limits: Limits,
        artifact_dir: Path,
        scrubber: SecretScrubber,
    ) -> AgentResult:
        """Runs the agent in a sandbox."""

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses usage from sanitized output."""


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


class CliAgentAdapter:
    """Reusable implementation for simple file-workspace CLI agents."""

    name = "base"
    provider_name = "base"
    binary = ""
    version_args = ("--version",)

    async def available(self) -> Tuple[bool, str]:
        """Checks whether the adapter binary exists on the safe PATH."""
        executable = binary_path(self.binary)
        if executable is None:
            return False, f"{self.binary} binary not found"
        return True, executable

    async def smoke_test(self, env: Dict[str, str], provider_profile: Optional[ProviderProfile]) -> Tuple[bool, str]:
        """Checks binary availability and required provider env presence."""
        available, reason = await self.available()
        if not available:
            return False, reason
        if provider_profile is not None:
            missing = [name for name in provider_profile.required_env if name not in env]
            if missing:
                return False, f"missing required env: {', '.join(sorted(missing))}"
        version = await self.version(env=env, scrubber=SecretScrubber())
        if version == "version_unknown":
            return True, "ok"
        return True, "ok"

    async def version(self, env: Dict[str, str], scrubber: SecretScrubber) -> str:
        """Returns a scrubbed version string or `version_unknown`."""
        executable = binary_path(self.binary)
        if executable is None:
            return "version_unknown"
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *self.version_args,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output = await _communicate_with_timeout(process, 10)
            stdout = output[0]
            stderr = output[1]
        except (OSError, asyncio.TimeoutError):
            return "version_unknown"
        text = scrubber.scrub_bytes(stdout + stderr).strip().splitlines()
        if not text:
            return "version_unknown"
        return text[0][:200]

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds a command line for the adapter."""
        raise NotImplementedError

    async def run(
        self,
        sandbox_context: SandboxContext,
        workspace_root: Path,
        env: Dict[str, str],
        timeout_s: int,
        limits: Limits,
        artifact_dir: Path,
        scrubber: SecretScrubber,
    ) -> AgentResult:
        """Runs the CLI adapter and returns sanitized execution data."""
        executable = binary_path(self.binary)
        if executable is None:
            raise AdapterUnavailableError(f"{self.binary} binary not found")
        prompt = (workspace_root / "task.md").read_text(encoding="utf-8")
        argv = list(self.build_argv(prompt=prompt, workspace_root=workspace_root))
        if argv[0] == self.binary:
            argv[0] = executable
        process_result = await sandbox_context.run_process(
            argv,
            cwd=workspace_root,
            env=env,
            timeout_s=timeout_s,
            limits=limits,
            stdout_path=artifact_dir / "stdout.txt",
            stderr_path=artifact_dir / "stderr.txt",
        )
        usage = self.parse_usage(process_result.stdout_tail, process_result.stderr_tail)
        version = await self.version(env=env, scrubber=scrubber)
        error_kind = RunErrorKind.TIMEOUT if process_result.timed_out else RunErrorKind.NONE
        error_detail = None
        if process_result.exit_code not in {0, None}:
            error_detail = f"agent exited with code {process_result.exit_code}"
        return AgentResult(
            agent=self.name,
            agent_version=version,
            exit_code=process_result.exit_code,
            timed_out=process_result.timed_out,
            duration_s=process_result.duration_s,
            cost_usd=usage.cost_usd,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            stdout_tail=scrubber.scrub_text(process_result.stdout_tail),
            stderr_tail=scrubber.scrub_text(process_result.stderr_tail),
            error_kind=error_kind,
            error_detail=error_detail,
        )

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses usage from stdout and stderr."""
        return Usage()


def parse_json_usage_text(text: str) -> Usage:
    """Parses common JSON and JSONL usage shapes."""
    cost = 0.0
    tokens_in = 0
    tokens_out = 0
    saw_cost = False
    saw_tokens_in = False
    saw_tokens_out = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        usage = payload.get("usage", payload)
        if "message" in payload and isinstance(payload["message"], dict):
            usage = payload["message"].get("usage", usage)
        parsed_cost = _float_from_keys(payload, ["cost_usd", "total_cost_usd", "cost"])
        usage_cost = _float_from_keys(usage, ["cost_usd", "total_cost_usd", "cost"])
        if parsed_cost is not None or usage_cost is not None:
            cost += parsed_cost if parsed_cost is not None else usage_cost if usage_cost is not None else 0.0
            saw_cost = True
        parsed_tokens_in = _int_from_keys(usage, ["tokens_in", "input_tokens", "prompt_tokens"])
        parsed_tokens_out = _int_from_keys(usage, ["tokens_out", "output_tokens", "completion_tokens"])
        if parsed_tokens_in is not None:
            tokens_in += parsed_tokens_in
            saw_tokens_in = True
        if parsed_tokens_out is not None:
            tokens_out += parsed_tokens_out
            saw_tokens_out = True
    return Usage(
        cost_usd=cost if saw_cost else None,
        tokens_in=tokens_in if saw_tokens_in else None,
        tokens_out=tokens_out if saw_tokens_out else None,
    )


def parse_text_usage(text: str) -> Usage:
    """Parses cost and tokens from human-oriented adapter text."""
    cost_match = re.search(r"(?:cost|cost_usd|total)\D+\$?([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    tokens_in_match = re.search(r"([0-9][0-9,]*)\s+(?:input|prompt|sent|tokens in)", text, flags=re.IGNORECASE)
    tokens_out_match = re.search(
        r"([0-9][0-9,]*)\s+(?:output|completion|received|tokens out)", text, flags=re.IGNORECASE
    )
    return Usage(
        cost_usd=float(cost_match.group(1)) if cost_match is not None else None,
        tokens_in=_parse_int_match(tokens_in_match),
        tokens_out=_parse_int_match(tokens_out_match),
    )


def _parse_int_match(match: Optional[re.Match[str]]) -> Optional[int]:
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


def _float_from_keys(payload: object, keys: Sequence[str]) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) or isinstance(value, float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.removeprefix("$"))
            except ValueError:
                continue
    return None


def _int_from_keys(payload: object, keys: Sequence[str]) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.replace(",", ""))
            except ValueError:
                continue
    return None
