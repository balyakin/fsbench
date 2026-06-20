"""Sandbox Protocol contracts and workspace extraction."""

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, TypedDict, Unpack
from zipfile import ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict

from fsbench.errors import SandboxExecutionError, TaskValidationError
from fsbench.models import Limits
from fsbench.sandbox.snapshots import FileSnapshot, TestMetrics, build_snapshot, collect_test_metrics


class ProcessRunKwargs(TypedDict, total=False):
    """Stores optional arguments for sandbox process execution."""

    cwd: Path
    env: Dict[str, str]
    timeout_s: int
    stdin_text: Optional[str]
    limits: Limits
    stdout_path: Path
    stderr_path: Path


class ProcessResult(Protocol):
    """Describes the process result returned by a sandbox."""

    exit_code: Optional[int]
    timed_out: bool
    duration_s: float
    stdout_tail: str
    stderr_tail: str


class SandboxContext(Protocol):
    """Runs commands inside one prepared workspace."""

    async def run_process(
        self,
        argv: Sequence[str],
        **kwargs: Unpack[ProcessRunKwargs],
    ) -> ProcessResult:
        """Runs argv with timeout, limits and output capture."""


class SandboxBackend(Protocol):
    """Creates sandbox contexts for workspaces."""

    async def enter(self, root: Path) -> SandboxContext:
        """Prepares sandbox context for a workspace."""


class CompletedProcessResult(BaseModel):
    """Stores sanitized subprocess execution output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: Optional[int]
    timed_out: bool
    duration_s: float
    stdout_tail: str
    stderr_tail: str


class Workspace(BaseModel):
    """Stores paths and immutable baseline data for one cell workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    task_md: Path
    base_snapshot: FileSnapshot
    base_test_metrics: Dict[str, TestMetrics]


def _is_zip_symlink_or_hardlink(info: ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode in {0o120000, 0o10000}


def validate_zip_member(info: ZipInfo) -> str:
    """Validates one workspace.zip member and returns its normalized POSIX path."""
    filename = info.filename
    if "\\" in filename:
        raise TaskValidationError(f"zip entry uses backslash: {filename}")
    relative = PurePosixPath(filename)
    if relative.is_absolute():
        raise TaskValidationError(f"zip entry is absolute: {filename}")
    if ".." in relative.parts:
        raise TaskValidationError(f"zip entry escapes workspace: {filename}")
    if _is_zip_symlink_or_hardlink(info):
        raise TaskValidationError(f"zip entry is symlink or hardlink: {filename}")
    normalized = relative.as_posix()
    if normalized in {"", "."}:
        raise TaskValidationError("zip entry is empty")
    return normalized


def validate_workspace_zip(workspace_zip: Path) -> List[str]:
    """Validates all workspace.zip entries and returns file paths."""
    files: List[str] = []
    with ZipFile(workspace_zip) as archive:
        for info in archive.infolist():
            normalized = validate_zip_member(info)
            if not info.is_dir():
                files.append(normalized)
    return sorted(files)


def make_workspace(
    run_dir: Path,
    task_id: str,
    agent: str,
    repeat: int,
    workspace_zip: Path,
    prompt_path: Path,
    protected_test_paths: Optional[Iterable[str]] = None,
) -> Workspace:
    """Creates an isolated workspace from workspace.zip and writes task.md."""
    workspaces_root = run_dir / "workspaces"
    workspaces_root.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(tempfile.mkdtemp(prefix=f"{task_id}-{agent}-{repeat}-", dir=workspaces_root)).resolve()
    try:
        with ZipFile(workspace_zip) as archive:
            for info in archive.infolist():
                normalized = validate_zip_member(info)
                target = (workspace_path / normalized).resolve()
                target.relative_to(workspace_path)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle:
                    with target.open("wb") as target_handle:
                        shutil.copyfileobj(source_handle, target_handle)
        home_dir = workspace_path / ".fsbench_home"
        (home_dir / ".config").mkdir(parents=True, exist_ok=True)
        (workspace_path / ".hypothesis").mkdir(parents=True, exist_ok=True)
        task_md = workspace_path / "task.md"
        task_md.write_text(prompt_path.read_text(encoding="utf-8"), encoding="utf-8")
        base_snapshot = build_snapshot(workspace_path)
        base_test_metrics = collect_test_metrics(
            workspace_path,
            base_snapshot.files.keys(),
            forced_test_paths=protected_test_paths,
        )
        return Workspace(
            root=workspace_path,
            task_md=task_md,
            base_snapshot=base_snapshot,
            base_test_metrics=base_test_metrics,
        )
    except Exception as error:
        shutil.rmtree(workspace_path, ignore_errors=True)
        if isinstance(error, (SandboxExecutionError, TaskValidationError)):
            raise
        raise SandboxExecutionError(f"cannot create workspace for task {task_id}") from error
