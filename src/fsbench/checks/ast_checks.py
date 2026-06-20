"""AST-based deterministic checks."""

import ast
import time
from pathlib import Path
from typing import List, Optional, Union

from fsbench.checks.base import CheckContext, check_result, resolve_workspace_path
from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult
from fsbench.sandbox.snapshots import is_excluded_path


def _parse_file(path: Path) -> ast.AST:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        raise CheckExecutionError(f"cannot parse Python file: {path}") from error


def _find_symbol(tree: ast.AST, symbol: str, kind: str) -> Optional[ast.AST]:
    for node in ast.walk(tree):
        if kind == "function" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol:
                return node
        if kind == "class" and isinstance(node, ast.ClassDef):
            if node.name == symbol:
                return node
        if kind == "method" and isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == symbol:
                    return child
    return None


async def ast_defines(context: CheckContext) -> CheckResult:
    """Checks that a symbol is defined in the expected file and not in forbidden globs."""
    started = time.monotonic()
    if context.check.symbol is None or context.check.kind is None:
        raise CheckExecutionError("symbol and kind are required")
    path = resolve_workspace_path(context.workspace.root, context.check.in_file)
    tree = _parse_file(path)
    found = _find_symbol(tree, context.check.symbol, context.check.kind) is not None
    forbidden_hits: List[str] = []
    for pattern in context.check.forbid_in_globs:
        for candidate in sorted(context.workspace.root.glob(pattern)):
            if candidate == path or not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.relative_to(context.workspace.root).as_posix()
            if is_excluded_path(relative):
                continue
            candidate_tree = _parse_file(candidate)
            if _find_symbol(candidate_tree, context.check.symbol, context.check.kind) is not None:
                forbidden_hits.append(relative)
    passed = found and not forbidden_hits
    return check_result(context, passed, 1.0 if passed else 0.0, {"forbidden_hits": forbidden_hits}, started)


async def ast_signature(context: CheckContext) -> CheckResult:
    """Checks that a symbol has the expected normalized signature."""
    started = time.monotonic()
    if context.check.symbol is None or context.check.kind is None or context.check.signature is None:
        raise CheckExecutionError("symbol, kind and signature are required")
    path = resolve_workspace_path(context.workspace.root, context.check.in_file)
    tree = _parse_file(path)
    node = _find_symbol(tree, context.check.symbol, context.check.kind)
    if node is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return check_result(context, False, 0.0, {"found": False}, started)
    signature = _format_signature(node)
    passed = signature == context.check.signature
    return check_result(context, passed, 1.0 if passed else 0.0, {"actual": signature}, started)


async def ast_no_import(context: CheckContext) -> CheckResult:
    """Checks that forbidden module imports are absent."""
    started = time.monotonic()
    if context.check.module is None:
        raise CheckExecutionError("module is required")
    files = (
        [resolve_workspace_path(context.workspace.root, context.check.in_file)]
        if context.check.in_file
        else _python_files(context.workspace.root)
    )
    violations: List[str] = []
    for path in files:
        tree = _parse_file(path)
        relative = path.relative_to(context.workspace.root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _import_violates(alias.name, None, context.check.module, context.check.names):
                        violations.append(f"{relative}:{alias.name}")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    if _import_violates(module, alias.name, context.check.module, context.check.names):
                        violations.append(f"{relative}:{module}.{alias.name}")
    passed = not violations
    return check_result(context, passed, 1.0 if passed else 0.0, {"violations": violations}, started)


def _python_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if not is_excluded_path(relative) and not path.is_symlink():
            files.append(path)
    return files


def _import_violates(module: str, name: Optional[str], forbidden_module: str, forbidden_names: List[str]) -> bool:
    if not forbidden_names:
        return module == forbidden_module or module.startswith(f"{forbidden_module}.")
    if name is not None:
        return module == forbidden_module and name in forbidden_names
    if not module.startswith(f"{forbidden_module}."):
        return False
    imported_root = module.removeprefix(f"{forbidden_module}.").split(".", maxsplit=1)[0]
    return imported_root in forbidden_names


def _format_signature(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    args = node.args
    parts: List[str] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults, strict=True):
        parts.append(_format_arg(arg, default))
    if args.vararg is not None:
        parts.append(f"*{_format_arg(args.vararg, None)}")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parts.append(_format_arg(arg, default))
    if args.kwarg is not None:
        parts.append(f"**{_format_arg(args.kwarg, None)}")
    returns = ""
    if node.returns is not None:
        returns = f" -> {ast.unparse(node.returns)}"
    return f"({', '.join(parts)}){returns}"


def _format_arg(arg: ast.arg, default: Optional[ast.expr]) -> str:
    text = arg.arg
    if arg.annotation is not None:
        text = f"{text}: {ast.unparse(arg.annotation)}"
    if default is not None:
        text = f"{text} = {ast.unparse(default)}"
    return text
