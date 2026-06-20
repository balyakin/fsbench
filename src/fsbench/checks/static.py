"""Static-analysis checks."""

import json
import re
import time

from fsbench.checks.base import CheckContext, check_result
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult


async def ruff_check(context: CheckContext) -> CheckResult:
    """Runs `ruff check --isolated --output-format json` in the workspace."""
    started = time.monotonic()
    argv = ["ruff", "check", "--isolated", "--output-format", "json"]
    argv.extend(context.check.args)
    stdout_path = context.artifact_dir / f"{context.check.name}-stdout.txt"
    result = await context.sandbox_context.run_process(
        argv,
        cwd=context.workspace.root,
        env=context.check_env,
        timeout_s=context.check.check_timeout_s,
        limits=context.task.spec.limits,
        stdout_path=stdout_path,
        stderr_path=context.artifact_dir / f"{context.check.name}-stderr.txt",
    )
    stdout_text = result.stdout_tail
    if stdout_path.exists():
        stdout_text = stdout_path.read_text(encoding="utf-8")
    violations = _parse_ruff_count(stdout_text)
    execution_ok = result.exit_code in {0, 1} and not result.timed_out
    passed = execution_ok and violations <= context.check.allow
    if not execution_ok:
        score = 0.0
    elif violations == 0:
        score = 1.0
    else:
        score = max(0.0, 1.0 - violations / context.check.threshold)
    return check_result(context, passed, score, {"violations": violations, "exit_code": result.exit_code}, started)


async def mypy_check(context: CheckContext) -> CheckResult:
    """Runs mypy with workspace config disabled."""
    started = time.monotonic()
    argv = ["mypy", "--config-file", "/dev/null"]
    if context.check.strict:
        argv.append("--strict")
    argv.extend(context.check.args)
    if not context.check.args:
        argv.append(".")
    result = await context.sandbox_context.run_process(
        argv,
        cwd=context.workspace.root,
        env=context.check_env,
        timeout_s=context.check.check_timeout_s,
        limits=context.task.spec.limits,
        stdout_path=context.artifact_dir / f"{context.check.name}-stdout.txt",
        stderr_path=context.artifact_dir / f"{context.check.name}-stderr.txt",
    )
    errors = _parse_mypy_error_count(result.stdout_tail)
    passed = result.exit_code == 0 and not result.timed_out
    score = 1.0 if errors == 0 else max(0.0, 1.0 - errors / context.check.threshold)
    return check_result(context, passed, score, {"errors": errors, "exit_code": result.exit_code}, started)


def _parse_ruff_count(stdout: str) -> int:
    try:
        payload = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as error:
        raise CheckExecutionError("ruff did not return JSON output") from error
    if isinstance(payload, list):
        return len(payload)
    raise CheckExecutionError("ruff JSON output must be a list")


def _parse_mypy_error_count(stdout: str) -> int:
    match = re.search(r"Found\s+([0-9]+)\s+errors?", stdout)
    if match is not None:
        return int(match.group(1))
    if "Success: no issues found" in stdout:
        return 0
    return len([line for line in stdout.splitlines() if ": error:" in line])
