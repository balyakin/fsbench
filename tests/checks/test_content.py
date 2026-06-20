from pathlib import Path
from typing import cast

from fsbench.checks.base import CheckContext
from fsbench.checks.content import content_absent, content_present, file_absent, file_exists
from fsbench.models import CheckSpec, CheckType
from fsbench.sandbox.base import SandboxContext, Workspace
from fsbench.sandbox.snapshots import build_snapshot
from fsbench.tasks.loader import load_task


def _context(tmp_path: Path, check: CheckSpec) -> CheckContext:
    workspace = Workspace(
        root=tmp_path,
        task_md=tmp_path / "task.md",
        base_snapshot=build_snapshot(tmp_path),
        base_test_metrics={},
    )
    return CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=workspace,
        sandbox_context=cast(SandboxContext, object()),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=check,
        required=True,
    )


async def test_content_present_and_absent(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("value = 42\n", encoding="utf-8")
    present = CheckSpec(name="content_present_ok", type=CheckType.CONTENT_PRESENT, path=Path("app.py"), pattern="42")
    absent = CheckSpec(name="content_absent_ok", type=CheckType.CONTENT_ABSENT, path=Path("app.py"), pattern="secret")

    # ACT
    present_result = await content_present(_context(tmp_path, present))
    absent_result = await content_absent(_context(tmp_path, absent))

    # ASSERT
    assert present_result.passed is True
    assert absent_result.passed is True


async def test_file_exists_and_absent(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    exists = CheckSpec(name="file_exists_ok", type=CheckType.FILE_EXISTS, path=Path("app.py"))
    absent = CheckSpec(name="file_absent_ok", type=CheckType.FILE_ABSENT, path=Path("missing.py"))

    # ACT
    exists_result = await file_exists(_context(tmp_path, exists))
    absent_result = await file_absent(_context(tmp_path, absent))

    # ASSERT
    assert exists_result.passed is True
    assert absent_result.passed is True
