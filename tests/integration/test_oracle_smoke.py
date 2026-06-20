from pathlib import Path

from fsbench.orchestrator import RunSuiteOptions, run_suite


async def test_oracle_smoke_end_to_end(tmp_path: Path) -> None:
    # ARRANGE
    run_dir = tmp_path / "oracle-run"
    options = RunSuiteOptions(
        task_paths=["tasks/open/demo-calculator-move"],
        agents=["oracle"],
        repeats=1,
        run_dir=run_dir,
    )

    # ACT
    summary = await run_suite(options)

    # ASSERT
    assert summary.completed_cells == 1
    assert (run_dir / "runs.sqlite").exists()
    assert (run_dir / "report.json").exists()
