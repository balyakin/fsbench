"""Content and file existence checks."""

import time

from fsbench.checks.base import CheckContext, check_result, resolve_workspace_path
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult


async def content_present(context: CheckContext) -> CheckResult:
    """Checks that a file contains a literal substring."""
    started = time.monotonic()
    path = resolve_workspace_path(context.workspace.root, context.check.path)
    if context.check.pattern is None:
        raise CheckExecutionError("pattern is required")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise CheckExecutionError(f"cannot decode file as UTF-8: {context.check.path}") from error
    passed = context.check.pattern in text
    return check_result(context, passed, 1.0 if passed else 0.0, {"path": path.name}, started)


async def content_absent(context: CheckContext) -> CheckResult:
    """Checks that a file does not contain a literal substring."""
    started = time.monotonic()
    path = resolve_workspace_path(context.workspace.root, context.check.path)
    if context.check.pattern is None:
        raise CheckExecutionError("pattern is required")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise CheckExecutionError(f"cannot decode file as UTF-8: {context.check.path}") from error
    passed = context.check.pattern not in text
    return check_result(context, passed, 1.0 if passed else 0.0, {"path": path.name}, started)


async def file_exists(context: CheckContext) -> CheckResult:
    """Checks that a path exists inside the workspace."""
    started = time.monotonic()
    path = resolve_workspace_path(context.workspace.root, context.check.path)
    passed = path.exists()
    path_text = context.check.path.as_posix() if context.check.path else ""
    return check_result(context, passed, 1.0 if passed else 0.0, {"path": path_text}, started)


async def file_absent(context: CheckContext) -> CheckResult:
    """Checks that a path is absent inside the workspace."""
    started = time.monotonic()
    path = resolve_workspace_path(context.workspace.root, context.check.path)
    passed = not path.exists()
    path_text = context.check.path.as_posix() if context.check.path else ""
    return check_result(context, passed, 1.0 if passed else 0.0, {"path": path_text}, started)
