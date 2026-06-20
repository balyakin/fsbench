"""Check execution contracts and helpers."""

import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult, CheckSpec, RunErrorKind
from fsbench.sandbox.base import SandboxContext, Workspace
from fsbench.tasks.loader import TaskBundle


class CheckContext:
    """Stores all inputs needed by one check implementation."""

    def __init__(
        self,
        task: TaskBundle,
        workspace: Workspace,
        sandbox_context: SandboxContext,
        check_env: Dict[str, str],
        artifact_dir: Path,
        check: CheckSpec,
        required: bool,
    ) -> None:
        """Initializes a check context."""
        self.task = task
        self.workspace = workspace
        self.sandbox_context = sandbox_context
        self.check_env = check_env
        self.artifact_dir = artifact_dir
        self.check = check
        self.required = required


CheckImplementation = Callable[[CheckContext], Awaitable[CheckResult]]


def check_result(
    context: CheckContext,
    passed: bool,
    score: float,
    detail: Dict[str, Any],
    started_at: float,
    error_kind: RunErrorKind = RunErrorKind.NONE,
    error_detail: Optional[str] = None,
) -> CheckResult:
    """Builds a CheckResult for a check context."""
    bounded_score = max(0.0, min(1.0, score))
    return CheckResult(
        name=context.check.name,
        type=context.check.type,
        required=context.required,
        weight=context.check.weight,
        passed=passed,
        score=bounded_score,
        detail=detail,
        duration_s=max(0.0, time.monotonic() - started_at),
        error_kind=error_kind,
        error_detail=error_detail,
    )


def resolve_workspace_path(root: Path, relative: Optional[Path]) -> Path:
    """Resolves a task path and ensures it remains inside the workspace."""
    if relative is None:
        raise CheckExecutionError("check path is required")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise CheckExecutionError(f"path escapes workspace: {relative.as_posix()}") from error
    return candidate
