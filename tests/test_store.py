from pathlib import Path

from fsbench.constants import SCHEMA_VERSION
from fsbench.models import AgentResult, CheckResult, CheckType, RunErrorKind, RunResult
from fsbench.store import RunStore, close_database, initialize_schema, open_database


def _run_result() -> RunResult:
    return RunResult(
        schema_version=SCHEMA_VERSION,
        run_id="run",
        task_id="task",
        task_version="0.1.0",
        agent="oracle",
        repeat=0,
        seed=1,
        agent_result=AgentResult(
            agent="oracle",
            agent_version="oracle",
            exit_code=0,
            timed_out=False,
            duration_s=0.1,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            stdout_tail="",
            stderr_tail="",
        ),
        checks=[
            CheckResult(
                name="unit",
                type=CheckType.FILE_EXISTS,
                required=True,
                weight=1.0,
                passed=True,
                score=1.0,
            )
        ],
        passed=True,
        score=1.0,
        error_kind=RunErrorKind.NONE,
        started_at="2026-06-20T00:00:00Z",
        finished_at="2026-06-20T00:00:01Z",
        artifacts_dir="artifacts/task/oracle/0",
        task_version_hash="t",
        env_manifest_hash="e",
    )


async def test_run_store_saves_and_reads_run(tmp_path: Path) -> None:
    # ARRANGE
    connection = await open_database(tmp_path / "runs.sqlite")
    await initialize_schema(connection, SCHEMA_VERSION)
    store = RunStore(connection)
    run = _run_result()

    # ACT
    await store.save_run(run)
    loaded = await store.get_run("task", "oracle", 0)
    hit = await store.has_completed_run("task", "oracle", 0, 1, "t", "e")

    # ASSERT
    assert loaded == run
    assert hit is True
    await close_database(connection)
