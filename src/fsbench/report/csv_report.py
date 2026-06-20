"""CSV report exporters."""

import csv
from pathlib import Path

from fsbench.models import BenchmarkReport


def export_csv_reports(run_dir: Path, report: BenchmarkReport) -> None:
    """Writes report.csv and aggregates.csv."""
    _write_runs_csv(run_dir / "report.csv", report)
    _write_aggregates_csv(run_dir / "aggregates.csv", report)


def _write_runs_csv(path: Path, report: BenchmarkReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "task_id",
                "agent",
                "repeat",
                "passed",
                "score",
                "duration_s",
                "cost_usd",
                "error_kind",
            ],
        )
        writer.writeheader()
        for run in report.runs:
            writer.writerow(
                {
                    "run_id": run.run_id,
                    "task_id": run.task_id,
                    "agent": run.agent,
                    "repeat": run.repeat,
                    "passed": run.passed,
                    "score": f"{run.score:.6f}",
                    "duration_s": f"{run.agent_result.duration_s:.6f}",
                    "cost_usd": "" if run.agent_result.cost_usd is None else f"{run.agent_result.cost_usd:.6f}",
                    "error_kind": run.error_kind.value,
                }
            )


def _write_aggregates_csv(path: Path, report: BenchmarkReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "task_id",
                "agent",
                "repeats",
                "successes",
                "pass_at_1",
                "mean_score",
                "mean_duration_s",
                "mean_cost_usd",
            ],
        )
        writer.writeheader()
        for aggregate in report.aggregates:
            writer.writerow(
                {
                    "task_id": aggregate.task_id,
                    "agent": aggregate.agent,
                    "repeats": aggregate.repeats,
                    "successes": aggregate.successes,
                    "pass_at_1": f"{aggregate.pass_at_1:.6f}",
                    "mean_score": f"{aggregate.mean_score:.6f}",
                    "mean_duration_s": f"{aggregate.mean_duration_s:.6f}",
                    "mean_cost_usd": "" if aggregate.mean_cost_usd is None else f"{aggregate.mean_cost_usd:.6f}",
                }
            )
