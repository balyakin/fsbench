"""Oracle pseudo-adapter."""

import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from fsbench.adapters.base import Usage
from fsbench.logging import SecretScrubber
from fsbench.models import AgentResult, Limits, ProviderProfile, RunErrorKind
from fsbench.sandbox.base import SandboxContext


def overlay_solution(solution_dir: Path, workspace_root: Path) -> None:
    """Copies solution files over the workspace without deleting files."""
    for path in sorted(solution_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(solution_dir)
        target = workspace_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


class OracleAdapter:
    """Applies the task's reference solution as a pseudo-agent."""

    name = "oracle"
    provider_name = "oracle"

    def __init__(self, solution_dir: Path) -> None:
        """Stores the solution directory for a task."""
        self.solution_dir = solution_dir

    async def available(self) -> Tuple[bool, str]:
        """Checks whether the task reference solution exists."""
        if not self.solution_dir.exists():
            return False, "solution directory missing"
        return True, "built-in"

    async def smoke_test(self, env: Dict[str, str], provider_profile: Optional[ProviderProfile]) -> Tuple[bool, str]:
        """Always reports oracle availability when solution_dir exists."""
        available, reason = await self.available()
        if not available:
            return False, reason
        return True, "ok"

    async def version(self, env: Dict[str, str], scrubber: SecretScrubber) -> str:
        """Returns the oracle adapter version string."""
        return "oracle"

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Returns an empty command because oracle does not spawn a process."""
        return []

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
        """Applies solution files to the workspace."""
        started = time.monotonic()
        overlay_solution(solution_dir=self.solution_dir, workspace_root=workspace_root)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "stdout.txt").write_text("", encoding="utf-8")
        (artifact_dir / "stderr.txt").write_text("", encoding="utf-8")
        return AgentResult(
            agent=self.name,
            agent_version="oracle",
            exit_code=0,
            timed_out=False,
            duration_s=time.monotonic() - started,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            stdout_tail="",
            stderr_tail="",
            error_kind=RunErrorKind.NONE,
            error_detail=None,
        )

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Oracle has no usage to parse."""
        return Usage(cost_usd=0.0, tokens_in=0, tokens_out=0)
