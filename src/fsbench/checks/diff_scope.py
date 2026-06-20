"""Diff-scope checks based on snapshots."""

import fnmatch
import time
from typing import List

from fsbench.checks.base import CheckContext, check_result
from fsbench.models import CheckResult
from fsbench.sandbox.snapshots import build_snapshot, compare_snapshots


async def diff_scope(context: CheckContext) -> CheckResult:
    """Checks changed paths against task scope limits."""
    started = time.monotonic()
    current = build_snapshot(context.workspace.root)
    diff = compare_snapshots(context.workspace.base_snapshot, current)
    changed = diff.changed_paths()
    violations: List[str] = []
    if context.check.max_files_changed is not None and len(changed) > context.check.max_files_changed:
        violations.append(f"changed file count {len(changed)} exceeds {context.check.max_files_changed}")
    forbidden_changed = [
        path for path in changed for pattern in context.check.forbid_changes if fnmatch.fnmatch(path, pattern)
    ]
    if forbidden_changed:
        violations.append(f"forbidden paths changed: {sorted(set(forbidden_changed))}")
    passed = not violations
    detail = {
        "added": diff.added,
        "removed": diff.removed,
        "modified": diff.modified,
        "violations": violations,
    }
    return check_result(context, passed, 1.0 if passed else 0.0, detail, started)
