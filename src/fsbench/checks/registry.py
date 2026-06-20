"""Check registry and safe execution loop."""

import asyncio
import time
from pathlib import Path
from typing import Dict, List

from fsbench.checks.anticheat import integrity, no_test_tamper
from fsbench.checks.ast_checks import ast_defines, ast_no_import, ast_signature
from fsbench.checks.base import CheckContext, CheckImplementation
from fsbench.checks.content import content_absent, content_present, file_absent, file_exists
from fsbench.checks.diff_scope import diff_scope
from fsbench.checks.static import mypy_check, ruff_check
from fsbench.checks.tests import pytest_check
from fsbench.errors import CheckExecutionError
from fsbench.logging import get_logger
from fsbench.models import CheckResult, CheckType, RunErrorKind
from fsbench.sandbox.base import SandboxContext, Workspace
from fsbench.tasks.loader import TaskBundle


def build_registry() -> Dict[CheckType, CheckImplementation]:
    """Builds the static MVP check registry."""
    return {
        CheckType.RUFF: ruff_check,
        CheckType.MYPY: mypy_check,
        CheckType.PYTEST: pytest_check,
        CheckType.AST_DEFINES: ast_defines,
        CheckType.AST_SIGNATURE: ast_signature,
        CheckType.AST_NO_IMPORT: ast_no_import,
        CheckType.CONTENT_PRESENT: content_present,
        CheckType.CONTENT_ABSENT: content_absent,
        CheckType.FILE_EXISTS: file_exists,
        CheckType.FILE_ABSENT: file_absent,
        CheckType.DIFF_SCOPE: diff_scope,
        CheckType.INTEGRITY: integrity,
        CheckType.NO_TEST_TAMPER: no_test_tamper,
    }


async def run_all_checks(
    task: TaskBundle,
    workspace: Workspace,
    sandbox_context: SandboxContext,
    check_env: Dict[str, str],
    artifact_dir: Path,
) -> List[CheckResult]:
    """Runs all task checks in manifest order and converts failures to CheckResult."""
    logger = get_logger("fsbench.checks")
    registry = build_registry()
    results: List[CheckResult] = []
    for check in task.spec.checks:
        required = check.name in task.spec.required_checks
        context = CheckContext(
            task=task,
            workspace=workspace,
            sandbox_context=sandbox_context,
            check_env=check_env,
            artifact_dir=artifact_dir,
            check=check,
            required=required,
        )
        implementation = registry.get(check.type)
        if implementation is None:
            results.append(
                CheckResult(
                    name=check.name,
                    type=check.type,
                    required=required,
                    weight=check.weight,
                    passed=False,
                    score=0.0,
                    error_kind=RunErrorKind.CHECK_FAILED,
                    error_detail=f"check type is not registered: {check.type.value}",
                )
            )
            continue
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(implementation(context), timeout=check.check_timeout_s)
            results.append(result)
        except asyncio.TimeoutError:
            results.append(
                CheckResult(
                    name=check.name,
                    type=check.type,
                    required=required,
                    weight=check.weight,
                    passed=False,
                    score=0.0,
                    duration_s=time.monotonic() - started,
                    error_kind=RunErrorKind.CHECK_TIMEOUT,
                    error_detail="check timed out",
                )
            )
        except asyncio.CancelledError:
            raise
        except CheckExecutionError as error:
            logger.exception("check_execution_failed", check_name=check.name, check_type=check.type.value)
            results.append(
                CheckResult(
                    name=check.name,
                    type=check.type,
                    required=required,
                    weight=check.weight,
                    passed=False,
                    score=0.0,
                    duration_s=time.monotonic() - started,
                    error_kind=RunErrorKind.CHECK_FAILED,
                    error_detail=str(error),
                )
            )
        except Exception as error:
            logger.exception("check_crashed", check_name=check.name, check_type=check.type.value)
            results.append(
                CheckResult(
                    name=check.name,
                    type=check.type,
                    required=required,
                    weight=check.weight,
                    passed=False,
                    score=0.0,
                    duration_s=time.monotonic() - started,
                    error_kind=RunErrorKind.CHECK_CRASH,
                    error_detail=f"check crashed: {error}",
                )
            )
    return results
