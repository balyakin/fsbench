from pathlib import Path
from typing import cast

from fsbench.checks.anticheat import no_test_tamper
from fsbench.checks.base import CheckContext
from fsbench.models import CheckSpec, CheckType
from fsbench.sandbox.base import SandboxContext, Workspace
from fsbench.sandbox.snapshots import build_snapshot, collect_test_metrics
from fsbench.tasks.loader import load_task


async def test_no_test_tamper_checks_forced_nonstandard_test_file(tmp_path: Path) -> None:
    # ARRANGE
    test_path = tmp_path / "verification.py"
    test_path.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    snapshot = build_snapshot(tmp_path)
    base_metrics = collect_test_metrics(
        tmp_path,
        snapshot.files.keys(),
        forced_test_paths=["verification.py"],
    )
    test_path.write_text("def test_value():\n    return None\n", encoding="utf-8")
    workspace = Workspace(
        root=tmp_path,
        task_md=tmp_path / "task.md",
        base_snapshot=snapshot,
        base_test_metrics=base_metrics,
    )
    context = CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=workspace,
        sandbox_context=cast(SandboxContext, object()),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=CheckSpec(name="no_test_tamper_ok", type=CheckType.NO_TEST_TAMPER),
        required=True,
    )

    # ACT
    result = await no_test_tamper(context)

    # ASSERT
    assert result.passed is False
    assert "assert count decreased: verification.py" in result.detail["violations"]


async def test_no_test_tamper_rejects_symlink_test_config(tmp_path: Path) -> None:
    # ARRANGE
    outside_config = tmp_path / "outside.toml"
    outside_config.write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    config_path = tmp_path / "pyproject.toml"
    config_path.symlink_to(outside_config)
    snapshot = build_snapshot(tmp_path)
    workspace = Workspace(
        root=tmp_path,
        task_md=tmp_path / "task.md",
        base_snapshot=snapshot,
        base_test_metrics={},
    )
    context = CheckContext(
        task=load_task(Path("tasks/open/demo-calculator-move")),
        workspace=workspace,
        sandbox_context=cast(SandboxContext, object()),
        check_env={},
        artifact_dir=tmp_path / "artifacts",
        check=CheckSpec(name="no_test_tamper_ok", type=CheckType.NO_TEST_TAMPER),
        required=True,
    )

    # ACT
    result = await no_test_tamper(context)

    # ASSERT
    assert result.passed is False
    assert "unsafe test config path: pyproject.toml" in result.detail["violations"]
