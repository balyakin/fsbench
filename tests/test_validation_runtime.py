from pathlib import Path

from fsbench.tasks.validation import validate_task


async def test_validate_task_demo() -> None:
    # ARRANGE
    task_path = Path("tasks/open/demo-calculator-move")

    # ACT
    report = await validate_task(task_path)

    # ASSERT
    assert report.valid is True
    assert report.base_passed is False
    assert report.oracle_passed is True
