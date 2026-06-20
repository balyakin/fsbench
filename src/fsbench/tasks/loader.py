"""Task discovery, loading, and version hashing."""

import fnmatch
import glob
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Sequence, Set

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from fsbench.errors import TaskValidationError
from fsbench.models import TaskSpec
from fsbench.sandbox.base import validate_workspace_zip
from fsbench.store import canonical_json


class TaskBundle(BaseModel):
    """Stores validated paths and manifest for a benchmark task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    spec: TaskSpec
    prompt_path: Path
    workspace_zip: Path
    solution_dir: Path
    hidden_dir: Path


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_existing_path(path: Path, root: Path) -> None:
    if not path.exists():
        raise TaskValidationError(f"required task path is missing: {path}")
    if not _path_is_inside(path, root):
        raise TaskValidationError(f"task path escapes root: {path}")
    if path.is_symlink():
        resolved = path.resolve()
        if not _path_is_inside(resolved, root):
            raise TaskValidationError(f"task symlink escapes root: {path}")


def _validate_tree_paths(root: Path, allowed_root: Path) -> None:
    for current_root, dir_names, file_names in os.walk(root, followlinks=False):
        for name in [*dir_names, *file_names]:
            path = Path(current_root) / name
            if not _path_is_inside(path, allowed_root):
                raise TaskValidationError(f"task path escapes root: {path}")
            if path.is_symlink() and not _path_is_inside(path.resolve(), allowed_root):
                raise TaskValidationError(f"task symlink escapes root: {path}")


def load_task(root: Path) -> TaskBundle:
    """Loads and validates one task directory."""
    task_root = root.resolve()
    task_yaml = task_root / "task.yaml"
    prompt_path = task_root / "prompt.md"
    workspace_zip = task_root / "workspace.zip"
    solution_dir = task_root / "solution"
    hidden_dir = task_root / "hidden"
    for path in [task_yaml, prompt_path, workspace_zip, solution_dir, hidden_dir]:
        _validate_existing_path(path=path, root=task_root)
    if not solution_dir.is_dir():
        raise TaskValidationError(f"solution is not a directory: {solution_dir}")
    if not hidden_dir.is_dir():
        raise TaskValidationError(f"hidden is not a directory: {hidden_dir}")
    _validate_tree_paths(solution_dir, task_root)
    _validate_tree_paths(hidden_dir, task_root)

    try:
        raw_data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
        if not isinstance(raw_data, dict):
            raise TaskValidationError(f"task.yaml must contain a mapping: {task_yaml}")
        spec = TaskSpec.model_validate(raw_data)
    except ValidationError as error:
        raise TaskValidationError(f"invalid task.yaml: {task_yaml}") from error
    except yaml.YAMLError as error:
        raise TaskValidationError(f"invalid YAML: {task_yaml}") from error

    for check in spec.checks:
        for path in check.inject:
            candidate = hidden_dir / path
            _validate_existing_path(candidate, hidden_dir)
        for maybe_path in [check.in_file, check.path]:
            if maybe_path is None:
                continue
            candidate = task_root / maybe_path
            if candidate.exists() and not _path_is_inside(candidate, task_root):
                raise TaskValidationError(f"check path escapes task root: {maybe_path}")

    validate_workspace_zip(workspace_zip)
    return TaskBundle(
        root=task_root,
        spec=spec,
        prompt_path=prompt_path,
        workspace_zip=workspace_zip,
        solution_dir=solution_dir,
        hidden_dir=hidden_dir,
    )


def protected_test_paths(task: TaskBundle) -> List[str]:
    """Returns workspace Python paths protected as visible tests by task metadata."""
    workspace_files = validate_workspace_zip(task.workspace_zip)
    protected = {path.as_posix() for path in task.spec.editable_files if path.as_posix().endswith(".py")}
    for check in task.spec.checks:
        for pattern in check.forbid_changes:
            protected.update(
                path for path in workspace_files if path.endswith(".py") and fnmatch.fnmatch(path, pattern)
            )
    return sorted(path for path in protected if path in workspace_files)


def _task_dirs_from_input(raw_path: str) -> List[Path]:
    matches = [Path(match) for match in sorted(glob.glob(raw_path))] if glob.has_magic(raw_path) else [Path(raw_path)]
    task_dirs: List[Path] = []
    for path in matches:
        if path.is_file() and path.name == "task.yaml":
            task_dirs.append(path.parent)
            continue
        if (path / "task.yaml").exists():
            task_dirs.append(path)
            continue
        if path.is_dir():
            task_dirs.extend(sorted(task_yaml.parent for task_yaml in path.rglob("task.yaml")))
    return task_dirs


def discover_tasks(paths: Sequence[str]) -> List[TaskBundle]:
    """Discovers task directories under paths or globs and loads them in task_id order."""
    task_dirs: Dict[Path, Path] = {}
    for raw_path in paths:
        for task_dir in _task_dirs_from_input(raw_path):
            resolved_task_dir = task_dir.resolve()
            task_dirs[resolved_task_dir] = resolved_task_dir
    tasks = [load_task(path) for path in sorted(task_dirs)]
    seen_task_ids: Set[str] = set()
    duplicate_task_ids: List[str] = []
    for task in tasks:
        if task.spec.id in seen_task_ids:
            duplicate_task_ids.append(task.spec.id)
        seen_task_ids.add(task.spec.id)
    if duplicate_task_ids:
        duplicate_text = ", ".join(sorted(set(duplicate_task_ids)))
        raise TaskValidationError(f"duplicate task ids found: {duplicate_text}")
    return sorted(tasks, key=lambda task: task.spec.id)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_tree(root: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    if not root.exists():
        return entries
    for current_root, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names[:] = sorted(dir_names)
        for file_name in sorted(file_names):
            path = Path(current_root) / file_name
            relative = path.relative_to(root).as_posix()
            stat_result = path.lstat()
            entries.append(
                {
                    "executable": bool(stat_result.st_mode & 0o111),
                    "path": relative,
                    "sha256": _hash_file(path)
                    if not path.is_symlink()
                    else hashlib.sha256(os.readlink(path).encode()).hexdigest(),
                    "size": stat_result.st_size,
                }
            )
    return entries


def compute_task_version_hash(task: TaskBundle) -> str:
    """Computes the deterministic task_version_hash for resume invalidation."""
    payload = {
        "algorithm": "task-version-hash-v1",
        "hidden": _hash_tree(task.hidden_dir),
        "prompt_sha256": _hash_file(task.prompt_path),
        "solution": _hash_tree(task.solution_dir),
        "spec": json.loads(task.spec.model_dump_json()),
        "workspace_zip_sha256": _hash_file(task.workspace_zip),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
