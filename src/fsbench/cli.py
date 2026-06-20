"""Typer command-line interface for fsbench."""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, List, Optional, TypeVar

import typer

from fsbench.config import load_settings
from fsbench.constants import RUNS_DATABASE_NAME, SCHEMA_VERSION
from fsbench.doctor import DoctorItem, run_doctor
from fsbench.errors import FsbenchError
from fsbench.models import AgentEnvMode, SandboxKind
from fsbench.orchestrator import RunSuiteOptions, RunSuiteSummary, run_suite
from fsbench.report.csv_report import export_csv_reports
from fsbench.report.html_report import export_html_report
from fsbench.report.json_report import compare_reports, export_json_report, export_runs_jsonl, load_report
from fsbench.scoring import aggregate_runs
from fsbench.store import RunStore, close_database, initialize_schema, open_database
from fsbench.tasks.template import scaffold_task
from fsbench.tasks.validation import TaskValidationReport, validate_changed, validate_tasks

app = typer.Typer(no_args_is_help=True, help="Local coding-agent benchmark harness.")
T = TypeVar("T")


@app.command()
def doctor(
    agents: str = typer.Option(
        "oracle,codex,aider,claude,opencode,pi",
        "--agents",
        help="Comma-separated agents to inspect.",
    ),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to fsbench.toml."),
) -> None:
    """Checks local runtime, tools, sandbox, and adapter availability."""
    settings = load_settings(config)
    result = asyncio.run(run_doctor(settings=settings, agents=_parse_agents(agents)))
    _echo_doctor(result.items)
    if not result.ok:
        raise typer.Exit(1)


@app.command("new-task")
def new_task(
    task_id: str = typer.Argument(..., help="Task id."),
    root: Path = typer.Option(Path("tasks/open"), "--root", help="Task collection root."),
    force: bool = typer.Option(False, "--force", help="Overwrite known scaffold files for the same task id."),
) -> None:
    """Creates a new task scaffold."""
    _run_with_errors(lambda: typer.echo(scaffold_task(task_id=task_id, root=root, force=force).as_posix()))


@app.command()
def validate(
    tasks: Optional[List[str]] = typer.Option(None, "--tasks", help="Task path or glob; can be repeated."),
    changed: bool = typer.Option(False, "--changed", help="Validate only git-changed tasks."),
) -> None:
    """Validates task manifests, base failure, oracle success, and deterministic checks."""

    async def runner() -> List[TaskValidationReport]:
        if changed:
            return await validate_changed(Path.cwd())
        selected = tasks if tasks else ["tasks/open"]
        return await validate_tasks(selected)

    reports = _run_async_with_errors(runner)
    _echo_validation_reports(reports)
    if any(not report.valid for report in reports):
        raise typer.Exit(1)


@app.command()
def run(
    tasks: Optional[List[str]] = typer.Option(None, "--tasks", help="Task path or glob; can be repeated."),
    agents: str = typer.Option("oracle", "--agents", help="Comma-separated agent names."),
    repeats: int = typer.Option(1, "--repeats", min=1, help="Repeat count."),
    run_dir: Optional[Path] = typer.Option(None, "--run-dir", help="Run directory for new run or resume."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan matrix and resume hits without running cells."),
    max_cost_usd: Optional[float] = typer.Option(None, "--max-cost-usd", min=0.0, help="Known-cost budget cap."),
    sandbox: Optional[SandboxKind] = typer.Option(None, "--sandbox", help="Sandbox backend."),
    agent_env: Optional[AgentEnvMode] = typer.Option(None, "--agent-env", help="Agent environment mode."),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to fsbench.toml."),
    keep_artifacts: Optional[bool] = typer.Option(None, "--keep-artifacts/--clean-workspaces", help="Keep workspaces."),
) -> None:
    """Runs the selected benchmark matrix."""
    options = RunSuiteOptions(
        task_paths=tasks if tasks else ["tasks/open"],
        agents=_parse_agents(agents),
        repeats=repeats,
        run_dir=run_dir,
        dry_run=dry_run,
        max_cost_usd=max_cost_usd,
        sandbox=sandbox,
        agent_env=agent_env,
        config_path=config,
        keep_artifacts=keep_artifacts,
    )
    summary = _run_async_with_errors(lambda: run_suite(options))
    _echo_run_summary(summary)


@app.command()
def report(
    run_dir: Path = typer.Option(..., "--run-dir", help="Run directory."),
) -> None:
    """Regenerates JSON, JSONL, CSV, and HTML reports from SQLite."""
    _run_async_with_errors(lambda: _export_reports(run_dir))
    typer.echo(f"wrote reports in {run_dir.as_posix()}")


@app.command()
def leaderboard(
    report_path: Path = typer.Option(..., "--report", help="Path to report.json."),
) -> None:
    """Prints a compact leaderboard from report.json."""
    benchmark_report = load_report(report_path)
    for aggregate in sorted(benchmark_report.aggregates, key=lambda item: (-item.pass_at_1, item.agent, item.task_id)):
        ci_low, ci_high = aggregate.pass_at_1_ci95
        typer.echo(
            f"{aggregate.agent}\t{aggregate.task_id}\tpass@1={aggregate.pass_at_1:.3f}\t"
            f"ci95={ci_low:.3f}..{ci_high:.3f}\tscore={aggregate.mean_score:.3f}"
        )


@app.command()
def compare(
    left_report: Path = typer.Argument(..., help="Left report.json."),
    right_report: Path = typer.Argument(..., help="Right report.json."),
    by_task: bool = typer.Option(False, "--by-task", help="Show per-task regression matrix."),
) -> None:
    """Compares two JSON reports."""
    left = load_report(left_report)
    right = load_report(right_report)
    warnings, lines = compare_reports(left=left, right=right, by_task=by_task)
    for warning in warnings:
        typer.echo(f"WARNING: {warning}", err=True)
    for line in lines:
        typer.echo(line)


@app.command()
def inspect(
    run_dir: Path = typer.Option(..., "--run-dir", help="Run directory."),
    task: str = typer.Option(..., "--task", help="Task id."),
    agent: str = typer.Option(..., "--agent", help="Agent name."),
    repeat: int = typer.Option(..., "--repeat", min=0, help="Repeat index."),
) -> None:
    """Inspects a saved cell without running agents, checks, shell, or sandbox."""
    _run_async_with_errors(lambda: _inspect_cell(run_dir=run_dir, task=task, agent=agent, repeat=repeat))


async def _export_reports(run_dir: Path) -> None:
    database_path = run_dir / RUNS_DATABASE_NAME
    if not database_path.exists():
        raise FsbenchError(f"run database does not exist: {database_path}")
    connection = await open_database(database_path)
    try:
        await initialize_schema(connection, SCHEMA_VERSION)
        store = RunStore(connection)
        await store.replace_aggregates(aggregate_runs(await store.list_runs()))
        benchmark_report = await export_json_report(run_dir, store)
        await export_runs_jsonl(run_dir, store)
        export_csv_reports(run_dir, benchmark_report)
        settings = load_settings()
        export_html_report(
            run_dir,
            benchmark_report,
            inline_diff_max_bytes=settings.report.inline_diff_max_bytes,
        )
    finally:
        await close_database(connection)


async def _inspect_cell(run_dir: Path, task: str, agent: str, repeat: int) -> None:
    database_path = run_dir / RUNS_DATABASE_NAME
    if not database_path.exists():
        raise FsbenchError(f"run database does not exist: {database_path}")
    connection = await open_database(database_path)
    try:
        store = RunStore(connection)
        run = await store.get_run(task_id=task, agent=agent, repeat=repeat)
        if run is None:
            raise FsbenchError("cell not found")
        typer.echo(f"{run.task_id} {run.agent} repeat={run.repeat}")
        typer.echo(f"passed={run.passed} score={run.score:.3f} error={run.error_kind.value}")
        typer.echo(f"agent_version={run.agent_result.agent_version} duration={run.agent_result.duration_s:.3f}s")
        typer.echo(f"cost_usd={run.agent_result.cost_usd}")
        typer.echo("checks:")
        for check in run.checks:
            typer.echo(
                f"  {check.name}\t{check.type.value}\trequired={check.required}\t"
                f"passed={check.passed}\tscore={check.score:.3f}\tduration={check.duration_s:.3f}s"
            )
        if run.artifacts_dir is not None:
            artifacts_dir = (run_dir / run.artifacts_dir).resolve()
            try:
                artifacts_dir.relative_to(run_dir.resolve())
            except ValueError as error:
                raise FsbenchError("artifact path escapes run directory") from error
            typer.echo(f"artifacts={run.artifacts_dir}")
        typer.echo("stdout_tail:")
        typer.echo(run.agent_result.stdout_tail)
        typer.echo("stderr_tail:")
        typer.echo(run.agent_result.stderr_tail)
    finally:
        await close_database(connection)


def _parse_agents(agents: str) -> List[str]:
    names = [name.strip() for name in agents.split(",") if name.strip()]
    if not names:
        raise typer.BadParameter("at least one agent is required")
    return names


def _echo_doctor(items: List[DoctorItem]) -> None:
    for item in items:
        typer.echo(f"{item.name}\t{item.status}\t{item.detail}")


def _echo_validation_reports(reports: List[TaskValidationReport]) -> None:
    for report in reports:
        status = "ok" if report.valid else "fail"
        typer.echo(
            f"{report.task_id}\t{status}\tbase_passed={report.base_passed}\t"
            f"oracle_passed={report.oracle_passed}\toracle_score={report.oracle_score:.3f}"
        )
        for error in report.errors:
            typer.echo(f"  {error}", err=True)


def _echo_run_summary(summary: RunSuiteSummary) -> None:
    typer.echo(f"run_id={summary.run_id}")
    if summary.run_dir is not None:
        typer.echo(f"run_dir={summary.run_dir.as_posix()}")
    typer.echo(f"planned_cells={summary.planned_cells}")
    typer.echo(f"resume_hits={summary.resume_hits}")
    typer.echo(f"pending_cells={summary.pending_cells}")
    typer.echo(f"completed_cells={summary.completed_cells}")
    typer.echo(f"env_manifest_hash={summary.env_manifest_hash}")
    typer.echo(f"timeout_ceiling_s={summary.timeout_ceiling_s}")
    if summary.skipped_adapters:
        typer.echo(f"skipped_adapters={summary.skipped_adapters}")
    if summary.shutdown_reason is not None:
        typer.echo(f"shutdown_reason={summary.shutdown_reason}")


def _run_with_errors(func: Callable[[], None]) -> None:
    try:
        func()
    except FsbenchError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def _run_async_with_errors(func: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        return asyncio.run(func())
    except FsbenchError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


if __name__ == "__main__":
    app()
