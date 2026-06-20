"""Anti-cheat checks for workspace integrity and test tampering."""

import fnmatch
import time
from stat import S_ISREG
from typing import List

from fsbench.checks.base import CheckContext, check_result
from fsbench.models import CheckResult
from fsbench.sandbox.snapshots import build_snapshot, collect_test_metrics, compare_snapshots

SABOTAGE_PATTERNS = [
    "addopts",
    "--ignore",
    "python_files =",
    "testpaths =",
    "filterwarnings",
]
MAX_TEST_CONFIG_BYTES = 256 * 1024


async def integrity(context: CheckContext) -> CheckResult:
    """Checks that forbidden paths were not added, removed, or modified."""
    started = time.monotonic()
    current = build_snapshot(context.workspace.root)
    diff = compare_snapshots(context.workspace.base_snapshot, current)
    changed = diff.changed_paths()
    forbidden = [path for path in changed for pattern in context.check.forbid_changes if fnmatch.fnmatch(path, pattern)]
    passed = not forbidden
    return check_result(context, passed, 1.0 if passed else 0.0, {"forbidden_changed": sorted(set(forbidden))}, started)


async def no_test_tamper(context: CheckContext) -> CheckResult:
    """Checks that visible tests were not weakened."""
    started = time.monotonic()
    base_metrics = context.workspace.base_test_metrics
    current_metrics = collect_test_metrics(
        context.workspace.root,
        base_metrics.keys(),
        forced_test_paths=base_metrics.keys(),
    )
    violations: List[str] = []
    for relative_path, metrics in sorted(base_metrics.items()):
        current = current_metrics.get(relative_path)
        if current is None:
            violations.append(f"visible test removed: {relative_path}")
            continue
        if current.test_functions < metrics.test_functions:
            violations.append(f"test function count decreased: {relative_path}")
        if current.asserts < metrics.asserts:
            violations.append(f"assert count decreased: {relative_path}")
    config_names = {"conftest.py", "pytest.ini", "pyproject.toml"}
    for path in sorted(context.workspace.root.rglob("*")):
        if path.name not in config_names:
            continue
        stat_result = path.lstat()
        config_path = path.relative_to(context.workspace.root).as_posix()
        if path.is_symlink() or not S_ISREG(stat_result.st_mode):
            violations.append(f"unsafe test config path: {config_path}")
            continue
        if stat_result.st_size > MAX_TEST_CONFIG_BYTES:
            violations.append(f"test config is too large: {config_path}")
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            violations.append(f"cannot read test config: {config_path}")
            continue
        for pattern in SABOTAGE_PATTERNS:
            if pattern in text:
                violations.append(f"suspicious test config pattern {pattern}: {config_path}")
    passed = not violations
    return check_result(context, passed, 1.0 if passed else 0.0, {"violations": violations}, started)
