from pathlib import Path

from typer.testing import CliRunner

from fsbench.cli import app


def test_cli_run_dry_run() -> None:
    # ARRANGE
    runner = CliRunner()

    # ACT
    result = runner.invoke(
        app,
        ["run", "--agents", "oracle", "--tasks", "tasks/open/demo-calculator-move", "--repeats", "1", "--dry-run"],
    )

    # ASSERT
    assert result.exit_code == 0
    assert "planned_cells=1" in result.stdout


def test_cli_run_dry_run_accepts_host_agent_env() -> None:
    # ARRANGE
    runner = CliRunner()

    # ACT
    result = runner.invoke(
        app,
        [
            "run",
            "--agents",
            "oracle",
            "--tasks",
            "tasks/open/demo-calculator-move",
            "--repeats",
            "1",
            "--agent-env",
            "host",
            "--dry-run",
        ],
    )

    # ASSERT
    assert result.exit_code == 0
    assert "planned_cells=1" in result.stdout


def test_cli_doctor() -> None:
    # ARRANGE
    runner = CliRunner()

    # ACT
    result = runner.invoke(app, ["doctor", "--agents", "oracle"])

    # ASSERT
    assert result.exit_code == 0
    assert "python\tok" in result.stdout


def test_cli_new_task(tmp_path: Path) -> None:
    # ARRANGE
    runner = CliRunner()
    root = tmp_path / "tasks"

    # ACT
    result = runner.invoke(app, ["new-task", "sample-task", "--root", str(root)])

    # ASSERT
    assert result.exit_code == 0
    assert (root / "sample-task" / "workspace.zip").exists()


def test_cli_run_report_inspect_and_leaderboard(tmp_path: Path) -> None:
    # ARRANGE
    runner = CliRunner()
    run_dir = tmp_path / "run"

    # ACT
    run_result = runner.invoke(
        app,
        [
            "run",
            "--agents",
            "oracle",
            "--tasks",
            "tasks/open/demo-calculator-move",
            "--repeats",
            "1",
            "--run-dir",
            str(run_dir),
        ],
    )
    report_result = runner.invoke(app, ["report", "--run-dir", str(run_dir)])
    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            "--run-dir",
            str(run_dir),
            "--task",
            "demo-calculator-move",
            "--agent",
            "oracle",
            "--repeat",
            "0",
        ],
    )
    leaderboard_result = runner.invoke(app, ["leaderboard", "--report", str(run_dir / "report.json")])

    # ASSERT
    assert run_result.exit_code == 0
    assert report_result.exit_code == 0
    assert inspect_result.exit_code == 0
    assert leaderboard_result.exit_code == 0
    assert "passed=True" in inspect_result.stdout
    assert "oracle" in leaderboard_result.stdout
    assert "ci95=" in leaderboard_result.stdout
