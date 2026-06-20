from pathlib import Path

import pytest

from fsbench.checks.base import CheckContext
from fsbench.checks.static import _parse_mypy_error_count, _parse_ruff_count
from fsbench.checks.static import ruff_check
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckSpec, CheckType
from fsbench.sandbox.base import CompletedProcessResult, Workspace
from fsbench.sandbox.snapshots import build_snapshot
from fsbench.tasks.loader import load_task


class _RuffSandboxContext:
    async def run_process(self, argv, **kwargs):
        stdout_path = kwargs["stdout_path"]
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text('[{"code": "F401"}, {"code": "E501"}]', encoding="utf-8")
        return CompletedProcessResult(
            exit_code=1,
            timed_out=False,
            duration_s=0.1,
            stdout_tail='{"code":',
            stderr_tail="",
        )


def test_parse_ruff_count() -> None:
    # ARRANGE
    payload = '[{"code": "F401"}, {"code": "E501"}]'

    # ACT
    count = _parse_ruff_count(payload)

    # ASSERT
    assert count == 2


def test_parse_mypy_error_count() -> None:
    # ARRANGE
    output = "Found 3 errors in 2 files (checked 5 source files)"

    # ACT
    count = _parse_mypy_error_count(output)

    # ASSERT
    assert count == 3


def test_parse_ruff_count_rejects_non_json() -> None:
    # ARRANGE
    payload = "ruff crashed"

    # ACT / ASSERT
    with pytest.raises(CheckExecutionError):
        _parse_ruff_count(payload)


async def test_ruff_check_parses_full_stdout_artifact(tmp_path: Path) -> None:
    # ARRANGE
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    snapshot = build_snapshot(workspace_root)
    context = CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=Workspace(
            root=workspace_root,
            task_md=workspace_root / "task.md",
            base_snapshot=snapshot,
            base_test_metrics={},
        ),
        sandbox_context=_RuffSandboxContext(),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=CheckSpec(name="ruff_ok", type=CheckType.RUFF, allow=2),
        required=True,
    )

    # ACT
    result = await ruff_check(context)

    # ASSERT
    assert result.passed is True
    assert result.detail["violations"] == 2
