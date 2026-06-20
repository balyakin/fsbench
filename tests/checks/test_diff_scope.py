from pathlib import Path
from typing import cast

from fsbench.checks.base import CheckContext
from fsbench.checks.diff_scope import diff_scope
from fsbench.models import CheckSpec, CheckType
from fsbench.sandbox.base import SandboxContext, Workspace
from fsbench.sandbox.snapshots import build_snapshot
from fsbench.tasks.loader import load_task


async def test_diff_scope_detects_allowed_change(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    snapshot = build_snapshot(tmp_path)
    (tmp_path / "app.py").write_text("new\n", encoding="utf-8")
    workspace = Workspace(
        root=tmp_path,
        task_md=tmp_path / "task.md",
        base_snapshot=snapshot,
        base_test_metrics={},
    )
    check = CheckSpec(name="diff_scope_ok", type=CheckType.DIFF_SCOPE, max_files_changed=1)
    context = CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=workspace,
        sandbox_context=cast(SandboxContext, object()),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=check,
        required=True,
    )

    # ACT
    result = await diff_scope(context)

    # ASSERT
    assert result.passed is True
    assert result.detail["modified"] == ["app.py"]
