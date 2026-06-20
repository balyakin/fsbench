"""Pytest check with hidden-test injection into a copy."""

import shutil
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

from fsbench.checks.base import CheckContext, check_result
from fsbench.constants import HIDDEN_PREFIX
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult, RunErrorKind

JUNIT_MAX_BYTES = 1024 * 1024


async def pytest_check(context: CheckContext) -> CheckResult:
    """Runs pytest in a temporary copy of the workspace with hidden files injected."""
    started = time.monotonic()
    home_dir = context.workspace.root / ".fsbench_home"
    copy_parent = home_dir / "pytest"
    copy_parent.mkdir(parents=True, exist_ok=True)
    copy_root = copy_parent / f"{context.check.name}-{uuid.uuid4().hex}"
    sandbox_junit_path = home_dir / f"{context.check.name}-{uuid.uuid4().hex}.xml"
    junit_path = context.artifact_dir / "junit.xml"
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            context.workspace.root,
            copy_root,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".fsbench_home", ".hypothesis", ".pytest_cache", ".mypy_cache", ".ruff_cache"
            ),
        )
        for inject_path in context.check.inject:
            if not inject_path.name.startswith(HIDDEN_PREFIX):
                raise CheckExecutionError(f"hidden file must start with {HIDDEN_PREFIX}: {inject_path.as_posix()}")
            source = context.task.hidden_dir / inject_path
            if not source.exists():
                raise CheckExecutionError(f"hidden inject file missing: {inject_path.as_posix()}")
            target = copy_root / inject_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        argv = ["pytest", "-q", f"--junitxml={sandbox_junit_path}"]
        argv.extend(context.check.args)
        pytest_env = dict(context.check_env)
        pytest_env["PYTHONPATH"] = str(copy_root)
        result = await context.sandbox_context.run_process(
            argv,
            cwd=copy_root,
            env=pytest_env,
            timeout_s=context.check.check_timeout_s,
            limits=context.task.spec.limits,
            stdout_path=context.artifact_dir / f"{context.check.name}-stdout.txt",
            stderr_path=context.artifact_dir / f"{context.check.name}-stderr.txt",
        )
        if sandbox_junit_path.exists():
            shutil.copy2(sandbox_junit_path, junit_path)
        total, failures, errors, skipped = _parse_junit(junit_path)
        if total == 0:
            return check_result(
                context,
                False,
                0.0,
                {"total_tests": 0},
                started,
                error_kind=RunErrorKind.CHECK_FAILED,
                error_detail="pytest collected zero tests",
            )
        passed_tests = max(0, total - failures - errors - skipped)
        passed = failures == 0 and errors == 0 and skipped == 0 and result.exit_code == 0 and not result.timed_out
        score = passed_tests / total
        detail = {
            "total_tests": total,
            "passed_tests": passed_tests,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "exit_code": result.exit_code,
        }
        return check_result(context, passed, score, detail, started)
    finally:
        shutil.rmtree(copy_root, ignore_errors=True)


def _parse_junit_int(value: Optional[str], attribute_name: str) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError as error:
        raise CheckExecutionError(f"junit.xml contains non-integer {attribute_name}") from error


def _parse_junit(junit_path: Path) -> Tuple[int, int, int, int]:
    if not junit_path.exists():
        return 0, 0, 1, 0
    if junit_path.stat().st_size > JUNIT_MAX_BYTES:
        raise CheckExecutionError("junit.xml exceeds size limit")
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as error:
        raise CheckExecutionError(f"junit.xml is malformed: {error}") from error
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    total = 0
    failures = 0
    errors = 0
    skipped = 0
    for suite in suites:
        total += _parse_junit_int(suite.attrib.get("tests"), "tests")
        failures += _parse_junit_int(suite.attrib.get("failures"), "failures")
        errors += _parse_junit_int(suite.attrib.get("errors"), "errors")
        skipped += _parse_junit_int(suite.attrib.get("skipped"), "skipped")
    return total, failures, errors, skipped
