"""Task validation command implementation."""

import asyncio
import fnmatch
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from fsbench.adapters.oracle import overlay_solution
from fsbench.checks.registry import run_all_checks
from fsbench.constants import HIDDEN_PREFIX, MAX_CHECKS_PER_TASK
from fsbench.errors import TaskValidationError
from fsbench.models import RunErrorKind
from fsbench.sandbox.base import make_workspace, validate_workspace_zip
from fsbench.sandbox.environment import build_check_env
from fsbench.sandbox.process import ProcessBackend
from fsbench.scoring import score_run
from fsbench.seed import build_check_seed
from fsbench.tasks.loader import TaskBundle, discover_tasks, load_task, protected_test_paths


class TaskValidationReport(BaseModel):
    """Stores validation outcome for one task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    valid: bool
    base_passed: bool
    oracle_passed: bool
    oracle_score: float = Field(ge=0.0, le=1.0)
    errors: List[str] = Field(default_factory=list)


def _validate_prompt_hidden_mentions(task: TaskBundle) -> None:
    prompt = task.prompt_path.read_text(encoding="utf-8")
    forbidden_terms = ["hidden", HIDDEN_PREFIX]
    for hidden_file in sorted(task.hidden_dir.rglob("*")):
        if hidden_file.is_dir():
            continue
        forbidden_terms.append(hidden_file.stem)
    lowered_prompt = prompt.lower()
    for term in forbidden_terms:
        if term.lower() in lowered_prompt:
            raise TaskValidationError(f"prompt mentions forbidden hidden-test term: {term}")


def _validate_hidden_files(task: TaskBundle) -> None:
    for path in sorted(task.hidden_dir.rglob("*")):
        if path.is_dir():
            continue
        if not path.name.startswith(HIDDEN_PREFIX):
            raise TaskValidationError(f"hidden file must start with {HIDDEN_PREFIX}: {path.name}")


def _validate_editable_files(task: TaskBundle) -> None:
    workspace_files = set(validate_workspace_zip(task.workspace_zip))
    for path in task.spec.editable_files:
        if path.as_posix() not in workspace_files:
            raise TaskValidationError(f"editable file is absent from workspace.zip: {path.as_posix()}")


def _validate_inject_files(task: TaskBundle) -> None:
    for check in task.spec.checks:
        for path in check.inject:
            if not (task.hidden_dir / path).exists():
                raise TaskValidationError(f"inject file is missing from hidden/: {path.as_posix()}")


def _validate_forbid_conflicts(task: TaskBundle) -> None:
    editable_paths = [path.as_posix() for path in task.spec.editable_files]
    for check in task.spec.checks:
        for pattern in check.forbid_changes:
            for editable_path in editable_paths:
                if fnmatch.fnmatch(editable_path, pattern):
                    raise TaskValidationError(f"forbid_changes conflicts with editable_files: {pattern}")


async def validate_task(task_path: Path) -> TaskValidationReport:
    """Validates one task by checking base failure and oracle success."""
    errors: List[str] = []
    task: Optional[TaskBundle] = None
    try:
        task = load_task(task_path)
        if len(task.spec.checks) > MAX_CHECKS_PER_TASK:
            raise TaskValidationError("too many checks")
        _validate_hidden_files(task)
        _validate_prompt_hidden_mentions(task)
        _validate_editable_files(task)
        _validate_inject_files(task)
        _validate_forbid_conflicts(task)
    except Exception as error:
        return TaskValidationReport(
            task_id=task_path.name,
            valid=False,
            base_passed=False,
            oracle_passed=False,
            oracle_score=0.0,
            errors=[str(error)],
        )

    with tempfile.TemporaryDirectory(prefix="fsbench-validate-") as run_temp:
        run_dir = Path(run_temp)
        seed = build_check_seed(42, task.spec.id)
        process_backend = ProcessBackend()
        base_workspace = make_workspace(
            run_dir=run_dir,
            task_id=task.spec.id,
            agent="base",
            repeat=0,
            workspace_zip=task.workspace_zip,
            prompt_path=task.prompt_path,
            protected_test_paths=protected_test_paths(task),
        )
        base_context = await process_backend.enter(base_workspace.root)
        base_checks = await run_all_checks(
            task=task,
            workspace=base_workspace,
            sandbox_context=base_context,
            check_env=build_check_env(base_workspace.root, seed),
            artifact_dir=run_dir / "base-artifacts",
        )
        base_passed, _base_score = score_run(base_checks)
        oracle_workspace = make_workspace(
            run_dir=run_dir,
            task_id=task.spec.id,
            agent="oracle",
            repeat=0,
            workspace_zip=task.workspace_zip,
            prompt_path=task.prompt_path,
            protected_test_paths=protected_test_paths(task),
        )
        overlay_solution(solution_dir=task.solution_dir, workspace_root=oracle_workspace.root)
        oracle_context = await process_backend.enter(oracle_workspace.root)
        oracle_checks = await run_all_checks(
            task=task,
            workspace=oracle_workspace,
            sandbox_context=oracle_context,
            check_env=build_check_env(oracle_workspace.root, seed),
            artifact_dir=run_dir / "oracle-artifacts",
        )
        oracle_passed, oracle_score = score_run(oracle_checks)
        oracle_checks_second = await run_all_checks(
            task=task,
            workspace=oracle_workspace,
            sandbox_context=oracle_context,
            check_env=build_check_env(oracle_workspace.root, seed),
            artifact_dir=run_dir / "oracle-artifacts-second",
        )
        oracle_passed_second, oracle_score_second = score_run(oracle_checks_second)
        if base_passed:
            errors.append("base state passes all required checks")
        if not oracle_passed or oracle_score < 0.99:
            errors.append("oracle does not pass all checks with score >= 0.99")
        if oracle_passed != oracle_passed_second or oracle_score != oracle_score_second:
            errors.append("oracle checks are not deterministic")
        for check in oracle_checks:
            if check.error_kind not in {RunErrorKind.NONE, RunErrorKind.CHECK_FAILED}:
                errors.append(f"check {check.name} returned unexpected error kind {check.error_kind.value}")
        shutil.rmtree(run_dir / "workspaces", ignore_errors=True)
        return TaskValidationReport(
            task_id=task.spec.id,
            valid=not errors,
            base_passed=base_passed,
            oracle_passed=oracle_passed,
            oracle_score=oracle_score,
            errors=errors,
        )


async def validate_tasks(paths: List[str]) -> List[TaskValidationReport]:
    """Validates all tasks selected by paths."""
    reports: List[TaskValidationReport] = []
    for task in discover_tasks(paths):
        reports.append(await validate_task(task.root))
    return reports


async def _git_output(args: List[str], cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        raise TaskValidationError(f"git command failed: {' '.join(args)}")
    return stdout.decode("utf-8").strip()


async def changed_task_paths(cwd: Path) -> List[Path]:
    """Returns task directories affected by git changes."""
    try:
        root = Path(await _git_output(["rev-parse", "--show-toplevel"], cwd=cwd))
    except TaskValidationError as error:
        raise TaskValidationError("validate --changed requires a git working tree") from error
    try:
        main_ref = await _git_output(["merge-base", "HEAD", "origin/main"], cwd=root)
        diff_args = ["diff", "--name-only", main_ref]
    except TaskValidationError:
        diff_args = ["diff", "--name-only", "HEAD"]
    changed = await _git_output(diff_args, cwd=root)
    task_dirs = set()
    for line in changed.splitlines():
        path = root / line
        for parent in [path, *path.parents]:
            if parent == root.parent:
                break
            if (parent / "task.yaml").exists():
                task_dirs.add(parent)
                break
    return sorted(task_dirs)


async def validate_changed(cwd: Path) -> List[TaskValidationReport]:
    """Validates only changed task directories."""
    task_dirs = await changed_task_paths(cwd)
    reports: List[TaskValidationReport] = []
    for task_dir in task_dirs:
        reports.append(await validate_task(task_dir))
    return reports
