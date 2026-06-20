"""Task scaffolding for `fsbench new-task`."""

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import yaml

from fsbench.errors import TaskValidationError
from fsbench.tasks.loader import load_task

TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def scaffold_task(task_id: str, root: Path, force: bool = False) -> Path:
    """Creates a new task scaffold and validates the resulting directory."""
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise TaskValidationError(f"invalid task id: {task_id}")
    task_dir = root / task_id
    if task_dir.exists() and not force:
        raise TaskValidationError(f"task already exists: {task_dir}")
    if task_dir.exists() and force:
        existing_yaml = task_dir / "task.yaml"
        try:
            existing_data: Any = (
                yaml.safe_load(existing_yaml.read_text(encoding="utf-8")) if existing_yaml.exists() else None
            )
        except yaml.YAMLError as error:
            raise TaskValidationError("--force requires a parseable existing task.yaml with the same id") from error
        if not isinstance(existing_data, dict) or existing_data.get("id") != task_id:
            raise TaskValidationError("--force requires an existing task.yaml with the same id")
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "solution").mkdir(exist_ok=True)
    (task_dir / "hidden").mkdir(exist_ok=True)

    (task_dir / "prompt.md").write_text(
        "Fix `answer()` so it returns the integer 42 while keeping the public API unchanged.\n",
        encoding="utf-8",
    )
    (task_dir / "task.yaml").write_text(
        f"""id: {task_id}
version: "0.1.0"
tier: 1
category: single_file_bugfix
description: "Starter scaffold task; replace this description before calibration."
timeout_s: 300
editable_files:
  - app.py
required_checks:
  - pytest_behavior
checks:
  - name: pytest_behavior
    type: pytest
    inject:
      - _fsbench_hidden_test_behavior.py
    args:
      - tests
      - _fsbench_hidden_test_behavior.py
  - name: diff_scope_limit
    type: diff_scope
    max_files_changed: 1
    forbid_changes:
      - tests/**
""",
        encoding="utf-8",
    )
    (task_dir / "solution" / "app.py").write_text("def answer() -> int:\n    return 42\n", encoding="utf-8")
    (task_dir / "hidden" / "_fsbench_hidden_test_behavior.py").write_text(
        "from app import answer\n\n\ndef test_hidden_answer() -> None:\n    assert answer() == 42\n",
        encoding="utf-8",
    )
    with tempfile.TemporaryDirectory() as raw_temp:
        temp_root = Path(raw_temp)
        (temp_root / "tests").mkdir()
        (temp_root / "app.py").write_text("def answer() -> int:\n    return 0\n", encoding="utf-8")
        (temp_root / "tests" / "test_behavior.py").write_text(
            "from app import answer\n\n\ndef test_answer() -> None:\n    assert answer() == 42\n",
            encoding="utf-8",
        )
        with ZipFile(task_dir / "workspace.zip", "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(temp_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(temp_root).as_posix())
    (task_dir / "CALIBRATION.md").write_text(
        "# Calibration\n\nDocument expected difficulty and calibration notes.\n", encoding="utf-8"
    )
    load_task(task_dir)
    shutil.rmtree(task_dir / "workspace", ignore_errors=True)
    return task_dir
