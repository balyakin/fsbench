from pathlib import Path

import pytest

from fsbench.checks.base import CheckContext
from fsbench.checks.tests import _parse_junit, pytest_check
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckSpec, CheckType
from fsbench.sandbox.base import CompletedProcessResult, Workspace
from fsbench.sandbox.snapshots import build_snapshot, collect_test_metrics
from fsbench.tasks.loader import load_task


class _PytestSandboxContext:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    async def run_process(self, argv, **kwargs):
        cwd = kwargs["cwd"]
        junit_arg = next(arg for arg in argv if arg.startswith("--junitxml="))
        sandbox_junit_path = Path(junit_arg.removeprefix("--junitxml="))
        assert cwd.is_relative_to(self.workspace_root)
        assert sandbox_junit_path.is_relative_to(self.workspace_root)
        sandbox_junit_path.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0"></testsuite>',
            encoding="utf-8",
        )
        return CompletedProcessResult(
            exit_code=0,
            timed_out=False,
            duration_s=0.1,
            stdout_tail="",
            stderr_tail="",
        )


def test_parse_junit_testsuite(tmp_path: Path) -> None:
    # ARRANGE
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite tests="2" failures="1" errors="0" skipped="0"></testsuite>', encoding="utf-8")

    # ACT
    total, failures, errors, skipped = _parse_junit(junit)

    # ASSERT
    assert total == 2
    assert failures == 1
    assert errors == 0
    assert skipped == 0


def test_parse_junit_rejects_malformed_xml(tmp_path: Path) -> None:
    # ARRANGE
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite", encoding="utf-8")

    # ACT / ASSERT
    with pytest.raises(CheckExecutionError):
        _parse_junit(junit)


def test_parse_junit_rejects_non_integer_counts(tmp_path: Path) -> None:
    # ARRANGE
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite tests="many" failures="0" errors="0" skipped="0"></testsuite>', encoding="utf-8")

    # ACT / ASSERT
    with pytest.raises(CheckExecutionError):
        _parse_junit(junit)


async def test_pytest_check_uses_paths_inside_workspace_for_sandbox(tmp_path: Path) -> None:
    # ARRANGE
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    test_path = workspace_root / "test_app.py"
    test_path.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    snapshot = build_snapshot(workspace_root)
    workspace = Workspace(
        root=workspace_root,
        task_md=workspace_root / "task.md",
        base_snapshot=snapshot,
        base_test_metrics=collect_test_metrics(workspace_root, snapshot.files.keys()),
    )
    context = CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=workspace,
        sandbox_context=_PytestSandboxContext(workspace_root),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=CheckSpec(name="unit", type=CheckType.PYTEST),
        required=True,
    )

    # ACT
    result = await pytest_check(context)

    # ASSERT
    assert result.passed is True
    assert (context.artifact_dir / "junit.xml").exists()
