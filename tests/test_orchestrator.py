from pathlib import Path

import pytest

from fsbench import orchestrator as orchestrator_module
from fsbench.config import load_settings
from fsbench.logging import GLOBAL_SCRUBBER
from fsbench.orchestrator import MatrixCell, RunSuiteOptions
from fsbench.tasks.loader import load_task


async def test_run_suite_stops_after_budget_shutdown_without_active_tasks(tmp_path: Path) -> None:
    # ARRANGE
    options = RunSuiteOptions(
        task_paths=[
            "tasks/open/demo-calculator-move",
            "tasks/open/t1-list-average",
        ],
        agents=["oracle"],
        repeats=1,
        run_dir=tmp_path / "budget-run",
        max_cost_usd=0.0,
    )

    # ACT
    summary = await orchestrator_module.run_suite(options)

    # ASSERT
    assert summary.shutdown_reason == "budget_exceeded"
    assert summary.completed_cells == 0


async def test_run_suite_closes_database_when_schema_initialization_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # ARRANGE
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

    fake_connection = FakeConnection()

    async def fake_open_database(database_path: Path) -> FakeConnection:
        return fake_connection

    async def fake_initialize_schema(connection: FakeConnection, schema_version: str) -> None:
        raise RuntimeError("schema failed")

    async def fake_close_database(connection: FakeConnection) -> None:
        connection.closed = True

    monkeypatch.setattr(orchestrator_module, "open_database", fake_open_database)
    monkeypatch.setattr(orchestrator_module, "initialize_schema", fake_initialize_schema)
    monkeypatch.setattr(orchestrator_module, "close_database", fake_close_database)
    options = RunSuiteOptions(
        task_paths=["tasks/open/demo-calculator-move"],
        agents=["oracle"],
        repeats=1,
        run_dir=tmp_path / "schema-run",
    )

    # ACT / ASSERT
    with pytest.raises(RuntimeError):
        await orchestrator_module.run_suite(options)
    assert fake_connection.closed is True


async def test_run_cell_scrubs_harness_exception_detail(tmp_path: Path, monkeypatch) -> None:
    # ARRANGE
    secret_value = "token=abcdefghijklmnopqrstuvwxyz"
    GLOBAL_SCRUBBER.register_secret("TEST_SECRET", secret_value)

    def fake_make_workspace(**kwargs):
        raise RuntimeError(f"leaked {secret_value}")

    monkeypatch.setattr(orchestrator_module, "make_workspace", fake_make_workspace)
    task = load_task(Path("tasks/open/demo-calculator-move"))
    settings = load_settings()
    cell = MatrixCell(
        task_id=task.spec.id,
        agent="oracle",
        repeat=0,
        seed=123,
    )

    # ACT
    result = await orchestrator_module.run_cell(
        cell=cell,
        task=task,
        run_id="run",
        run_dir=tmp_path,
        settings=settings,
        task_version_hash="task_hash",
        env_manifest_hash="env_hash",
    )

    # ASSERT
    assert secret_value not in result.error_detail
    assert secret_value not in result.agent_result.error_detail
    assert "<TEST_SECRET>" in result.error_detail
