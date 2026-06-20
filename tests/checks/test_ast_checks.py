from pathlib import Path
from typing import cast

from fsbench.checks.ast_checks import ast_defines, ast_no_import, ast_signature
from fsbench.checks.base import CheckContext
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


async def test_ast_defines_and_signature(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("def solve(value: int) -> int:\n    return value\n", encoding="utf-8")
    defines = CheckSpec(
        name="ast_defines_ok",
        type=CheckType.AST_DEFINES,
        symbol="solve",
        kind="function",
        in_file=Path("app.py"),
    )
    signature = CheckSpec(
        name="ast_signature_ok",
        type=CheckType.AST_SIGNATURE,
        symbol="solve",
        kind="function",
        in_file=Path("app.py"),
        signature="(value: int) -> int",
    )

    # ACT
    defines_result = await ast_defines(_context(tmp_path, defines))
    signature_result = await ast_signature(_context(tmp_path, signature))

    # ASSERT
    assert defines_result.passed is True
    assert signature_result.passed is True


async def test_ast_no_import(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("import math\n\nVALUE = math.pi\n", encoding="utf-8")
    check = CheckSpec(name="no_os", type=CheckType.AST_NO_IMPORT, module="os", in_file=Path("app.py"))

    # ACT
    result = await ast_no_import(_context(tmp_path, check))

    # ASSERT
    assert result.passed is True


async def test_ast_no_import_names_do_not_flag_submodule_members(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("from os.path import sep\nVALUE = sep\n", encoding="utf-8")
    check = CheckSpec(
        name="no_os_path",
        type=CheckType.AST_NO_IMPORT,
        module="os",
        names=["path"],
        in_file=Path("app.py"),
    )

    # ACT
    result = await ast_no_import(_context(tmp_path, check))

    # ASSERT
    assert result.passed is True


async def test_ast_no_import_names_flag_imported_submodule(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "app.py").write_text("import os.path\nVALUE = os.path.sep\n", encoding="utf-8")
    check = CheckSpec(
        name="no_os_path",
        type=CheckType.AST_NO_IMPORT,
        module="os",
        names=["path"],
        in_file=Path("app.py"),
    )

    # ACT
    result = await ast_no_import(_context(tmp_path, check))

    # ASSERT
    assert result.passed is False
