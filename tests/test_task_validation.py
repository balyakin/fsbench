import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from fsbench.errors import TaskValidationError
from fsbench.models import CheckSpec, CheckType, TaskSpec
from fsbench.seed import build_check_seed, build_run_seed
from fsbench.tasks.loader import discover_tasks, load_task


def _task_spec() -> TaskSpec:
    return TaskSpec(
        id="abc-task",
        version="0.1.0",
        tier=1,
        category="single_file_bugfix",
        description="A sufficiently long task description for tests.",
        required_checks=["unit"],
        checks=[CheckSpec(name="unit", type=CheckType.FILE_EXISTS, path=Path("app.py"))],
    )


def test_seed_is_stable() -> None:
    # ARRANGE
    first = build_run_seed(42, "task", "oracle", 0)

    # ACT
    second = build_run_seed(42, "task", "oracle", 0)

    # ASSERT
    assert first == second


def test_check_seed_is_independent_of_agent_and_repeat() -> None:
    # ARRANGE
    codex_run_seed = build_run_seed(42, "task", "codex", 0)
    aider_run_seed = build_run_seed(42, "task", "aider", 1)

    # ACT
    first = build_check_seed(42, "task")
    second = build_check_seed(42, "task")

    # ASSERT
    assert first == second
    assert first not in {codex_run_seed, aider_run_seed}


def test_task_spec_rejects_unknown_fields() -> None:
    # ARRANGE
    data = _task_spec().model_dump()
    data["extra"] = "nope"

    # ACT / ASSERT
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(data)


def test_task_spec_rejects_missing_required_check() -> None:
    # ARRANGE
    data = _task_spec().model_dump()
    data["required_checks"] = ["missing"]

    # ACT / ASSERT
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(data)


def test_task_spec_rejects_duplicate_check_names() -> None:
    # ARRANGE
    data = _task_spec().model_dump()
    data["checks"].append(data["checks"][0])

    # ACT / ASSERT
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(data)


def test_discover_tasks_finds_mvp_corpus() -> None:
    # ARRANGE
    paths = ["tasks/open"]

    # ACT
    tasks = discover_tasks(paths)

    # ASSERT
    assert len(tasks) == 15


def test_load_task_rejects_hidden_symlink_escape(tmp_path: Path) -> None:
    # ARRANGE
    task_dir = tmp_path / "bad-task"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("Fix the task.\n", encoding="utf-8")
    (task_dir / "solution").mkdir()
    hidden_dir = task_dir / "hidden"
    hidden_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n", encoding="utf-8")
    (hidden_dir / "_fsbench_hidden_escape.py").symlink_to(outside)
    with ZipFile(task_dir / "workspace.zip", "w") as archive:
        archive.writestr("app.py", "VALUE = 1\n")
    (task_dir / "task.yaml").write_text(
        """
id: bad-task
version: "0.1.0"
tier: 1
category: single_file_bugfix
description: "A sufficiently long task description for tests."
required_checks:
  - app_exists
checks:
  - name: app_exists
    type: file_exists
    path: app.py
""".strip(),
        encoding="utf-8",
    )

    # ACT / ASSERT
    with pytest.raises(TaskValidationError):
        load_task(task_dir)


def test_discover_tasks_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    # ARRANGE
    first_task = tmp_path / "first"
    second_task = tmp_path / "second"
    shutil.copytree(Path("tasks/open/demo-calculator-move"), first_task)
    shutil.copytree(Path("tasks/open/demo-calculator-move"), second_task)

    # ACT / ASSERT
    with pytest.raises(TaskValidationError):
        discover_tasks([str(tmp_path)])
