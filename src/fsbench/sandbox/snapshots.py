"""Hash-based workspace snapshots and diff artifacts."""

import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
from stat import S_IFMT, S_ISLNK, S_ISREG, S_IXGRP, S_IXOTH, S_IXUSR
from typing import Dict, Iterable, List, Optional, Set
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field

from fsbench.logging import SecretScrubber

EXCLUDED_DIR_NAMES = {
    ".git",
    ".fsbench_home",
    ".hypothesis",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}


class FileRecord(BaseModel):
    """Stores stable metadata for one snapshotted path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str
    size: int = Field(ge=0)
    executable: bool


class FileSnapshot(BaseModel):
    """Stores a deterministic file snapshot for a workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: Dict[str, FileRecord]


class SnapshotDiff(BaseModel):
    """Stores added, removed, and modified paths between two snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    modified: List[str] = Field(default_factory=list)

    def changed_paths(self) -> List[str]:
        """Returns all changed paths in stable order."""
        return sorted([*self.added, *self.removed, *self.modified])


class TestMetrics(BaseModel):
    """Stores simple visible-test AST metrics for anti-tamper checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    test_functions: int = Field(ge=0)
    asserts: int = Field(ge=0)


def is_excluded_path(path: str) -> bool:
    """Returns True when a relative POSIX path is excluded from snapshots."""
    parts = path.split("/")
    return any(part in EXCLUDED_DIR_NAMES for part in parts)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_symlink(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(os.readlink(path).encode("utf-8", errors="replace"))
    return digest.hexdigest()


def build_snapshot(root: Path) -> FileSnapshot:
    """Builds a deterministic sha256 snapshot for files under root."""
    root = root.resolve()
    records: Dict[str, FileRecord] = {}
    for current_root, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names[:] = sorted(name for name in dir_names if name not in EXCLUDED_DIR_NAMES)
        for file_name in sorted(file_names):
            path = Path(current_root) / file_name
            relative = path.relative_to(root).as_posix()
            if is_excluded_path(relative):
                continue
            stat_result = path.lstat()
            executable = bool(stat_result.st_mode & (S_IXUSR | S_IXGRP | S_IXOTH))
            if S_ISLNK(stat_result.st_mode):
                digest = _hash_symlink(path)
                size = len(os.readlink(path).encode("utf-8", errors="replace"))
            elif S_ISREG(stat_result.st_mode):
                digest = _hash_file(path)
                size = stat_result.st_size
            else:
                file_type = S_IFMT(stat_result.st_mode)
                digest = hashlib.sha256(f"special:{file_type}".encode("utf-8")).hexdigest()
                size = 0
            records[relative] = FileRecord(
                path=relative,
                sha256=digest,
                size=size,
                executable=executable,
            )
    return FileSnapshot(files={key: records[key] for key in sorted(records)})


def compare_snapshots(base: FileSnapshot, current: FileSnapshot) -> SnapshotDiff:
    """Compares two snapshots and returns stable added, removed, and modified paths."""
    base_paths = set(base.files)
    current_paths = set(current.files)
    added = sorted(current_paths.difference(base_paths))
    removed = sorted(base_paths.difference(current_paths))
    modified = sorted(
        path
        for path in base_paths.intersection(current_paths)
        if base.files[path].sha256 != current.files[path].sha256
        or base.files[path].executable != current.files[path].executable
    )
    return SnapshotDiff(added=added, removed=removed, modified=modified)


def write_changed_files_artifact(diff: SnapshotDiff, artifact_path: Path, scrubber: SecretScrubber) -> None:
    """Writes changed_files.json using stable relative paths."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "added": [scrubber.scrub_text(path) for path in diff.added],
        "removed": [scrubber.scrub_text(path) for path in diff.removed],
        "modified": [scrubber.scrub_text(path) for path in diff.modified],
    }
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_zip_member_text(zip_file: ZipFile, relative_path: str) -> Optional[str]:
    try:
        info = zip_file.getinfo(relative_path)
    except KeyError:
        return None
    if info.file_size > 256 * 1024:
        return None
    data = zip_file.read(info)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_current_text(workspace_root: Path, relative_path: str) -> Optional[str]:
    path = workspace_root / relative_path
    if not path.exists() or path.is_symlink() or not path.is_file():
        return None
    if path.stat().st_size > 256 * 1024:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def write_text_diff_artifact(
    workspace_zip: Path,
    current_workspace: Path,
    diff: SnapshotDiff,
    artifact_path: Path,
    scrubber: SecretScrubber,
) -> None:
    """Writes a best-effort unified diff artifact without reading hidden files."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    with ZipFile(workspace_zip) as zip_file:
        for relative_path in diff.changed_paths():
            base_text = _read_zip_member_text(zip_file=zip_file, relative_path=relative_path)
            current_text = _read_current_text(workspace_root=current_workspace, relative_path=relative_path)
            if base_text is None or current_text is None:
                if relative_path in diff.added:
                    lines.append(f"Added {relative_path}\n")
                elif relative_path in diff.removed:
                    lines.append(f"Removed {relative_path}\n")
                else:
                    lines.append(f"Changed binary-or-large {relative_path}\n")
                continue
            diff_lines = difflib.unified_diff(
                base_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
            lines.extend(diff_lines)
            if not lines or not lines[-1].endswith("\n"):
                lines.append("\n")
    artifact_path.write_text(scrubber.scrub_text("".join(lines)), encoding="utf-8")


def is_visible_test_path(relative_path: str) -> bool:
    """Returns True when a path is considered a visible test file."""
    path = Path(relative_path)
    name = path.name
    return (
        relative_path.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name in {"conftest.py", "pytest.ini", "pyproject.toml"}
    )


def collect_test_metrics(
    root: Path,
    paths: Iterable[str],
    forced_test_paths: Optional[Iterable[str]] = None,
) -> Dict[str, TestMetrics]:
    """Collects simple AST metrics for visible Python tests."""
    metrics: Dict[str, TestMetrics] = {}
    forced_paths: Set[str] = set(forced_test_paths or [])
    candidate_paths = set(paths).union(forced_paths)
    for relative_path in sorted(candidate_paths):
        if not relative_path.endswith(".py"):
            continue
        if not is_visible_test_path(relative_path) and relative_path not in forced_paths:
            continue
        path = root / relative_path
        if not path.exists() or path.is_symlink():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            metrics[relative_path] = TestMetrics(test_functions=0, asserts=0)
            continue
        test_functions = 0
        asserts = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                test_functions += 1
            if isinstance(node, ast.Assert):
                asserts += 1
        metrics[relative_path] = TestMetrics(test_functions=test_functions, asserts=asserts)
    return metrics
