"""JSON and JSONL report exporters."""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from fsbench.constants import SCHEMA_VERSION
from fsbench.models import BenchmarkReport, SuiteRef
from fsbench.store import RunStore, utc_now_iso


def atomic_write_text(path: Path, text: str) -> None:
    """Writes text through a same-directory temporary file and renames it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


async def build_report(store: RunStore) -> BenchmarkReport:
    """Builds a BenchmarkReport from SQLite storage."""
    metadata = await store.get_metadata_dict()
    suite = SuiteRef(
        name=metadata.get("suite_name", "fsbench-open"),
        version=metadata.get("suite_version", "0.1.0"),
        corpus_git_sha=metadata.get("corpus_git_sha", "0" * 40),
        corpus_ref_kind="git" if metadata.get("corpus_ref_kind", "unknown") == "git" else "unknown",
        corpus_dirty=metadata.get("corpus_dirty", "true") == "true",
        calibration_agents=json.loads(metadata.get("calibration_agents", "[]")),
    )
    public_metadata = {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            "task_version_hashes_json",
            "skipped_adapters_json",
        }
    }
    return BenchmarkReport(
        schema_version=metadata.get("schema_version", SCHEMA_VERSION),
        run_id=metadata.get("run_id", "unknown"),
        generated_at=utc_now_iso(),
        suite=suite,
        metadata=public_metadata,
        runs=await store.list_runs(),
        aggregates=await store.list_aggregates(),
    )


async def export_json_report(run_dir: Path, store: RunStore) -> BenchmarkReport:
    """Writes report.json and returns the in-memory report."""
    report = await build_report(store)
    atomic_write_text(run_dir / "report.json", report.model_dump_json(indent=2))
    return report


async def export_runs_jsonl(run_dir: Path, store: RunStore) -> None:
    """Writes stable runs.jsonl from SQLite."""
    lines = [run.model_dump_json() for run in await store.list_runs()]
    text = "\n".join(lines)
    if text:
        text = f"{text}\n"
    atomic_write_text(run_dir / "runs.jsonl", text)


def load_report(path: Path) -> BenchmarkReport:
    """Loads a BenchmarkReport JSON file."""
    return BenchmarkReport.model_validate_json(path.read_text(encoding="utf-8"))


AgentAggregateSummary = Tuple[float, Tuple[float, float]]


def compare_reports(left: BenchmarkReport, right: BenchmarkReport, by_task: bool) -> Tuple[List[str], List[str]]:
    """Compares two reports and returns warning lines and result lines."""
    warnings: List[str] = []
    lines: List[str] = []
    if left.schema_version != right.schema_version:
        warnings.append(f"schema_version differs: {left.schema_version} != {right.schema_version}")
    if left.suite.version != right.suite.version:
        warnings.append(f"suite.version differs: {left.suite.version} != {right.suite.version}")
    if left.suite.corpus_git_sha != right.suite.corpus_git_sha:
        warnings.append("corpus_git_sha differs")
    if left.suite.corpus_ref_kind == "unknown" or right.suite.corpus_ref_kind == "unknown":
        warnings.append("corpus_ref_kind is unknown; strict reproducibility is not proven")
    if left.suite.corpus_dirty or right.suite.corpus_dirty:
        warnings.append("at least one corpus is dirty; strict benchmark comparison is not proven")
    left_by_agent = _aggregate_by_agent(left)
    right_by_agent = _aggregate_by_agent(right)
    for agent in sorted(set(left_by_agent).union(right_by_agent)):
        left_value = left_by_agent.get(agent)
        right_value = right_by_agent.get(agent)
        if left_value is None or right_value is None:
            lines.append(f"{agent}: missing on one side")
            continue
        left_pass, left_ci = left_value
        right_pass, right_ci = right_value
        lines.append(
            f"{agent}: pass_at_1 {left_pass:.3f} ci95={left_ci[0]:.3f}..{left_ci[1]:.3f} -> "
            f"{right_pass:.3f} ci95={right_ci[0]:.3f}..{right_ci[1]:.3f} "
            f"(delta {right_pass - left_pass:+.3f})"
        )
    if by_task:
        lines.extend(_compare_by_task(left, right))
    return warnings, lines


def _aggregate_by_agent(report: BenchmarkReport) -> Dict[str, AgentAggregateSummary]:
    grouped: Dict[str, List[float]] = {}
    ci_lows: Dict[str, List[float]] = {}
    ci_highs: Dict[str, List[float]] = {}
    for aggregate in report.aggregates:
        grouped.setdefault(aggregate.agent, []).append(aggregate.pass_at_1)
        ci_lows.setdefault(aggregate.agent, []).append(aggregate.pass_at_1_ci95[0])
        ci_highs.setdefault(aggregate.agent, []).append(aggregate.pass_at_1_ci95[1])
    return {
        agent: (
            sum(values) / len(values),
            (
                sum(ci_lows[agent]) / len(ci_lows[agent]),
                sum(ci_highs[agent]) / len(ci_highs[agent]),
            ),
        )
        for agent, values in grouped.items()
    }


def _compare_by_task(left: BenchmarkReport, right: BenchmarkReport) -> List[str]:
    lines = ["by-task:"]
    left_values = {(aggregate.task_id, aggregate.agent): aggregate for aggregate in left.aggregates}
    right_values = {(aggregate.task_id, aggregate.agent): aggregate for aggregate in right.aggregates}
    for key in sorted(set(left_values).union(right_values)):
        left_value = left_values.get(key)
        right_value = right_values.get(key)
        task_id, agent = key
        if left_value is None or right_value is None:
            status = "missing"
            detail = ""
        elif right_value.pass_at_1 > left_value.pass_at_1:
            status = "improved"
            detail = _task_ci_detail(
                left_value.pass_at_1,
                left_value.pass_at_1_ci95,
                right_value.pass_at_1,
                right_value.pass_at_1_ci95,
            )
        elif right_value.pass_at_1 < left_value.pass_at_1:
            status = "regressed"
            detail = _task_ci_detail(
                left_value.pass_at_1,
                left_value.pass_at_1_ci95,
                right_value.pass_at_1,
                right_value.pass_at_1_ci95,
            )
        else:
            status = "unchanged"
            detail = _task_ci_detail(
                left_value.pass_at_1,
                left_value.pass_at_1_ci95,
                right_value.pass_at_1,
                right_value.pass_at_1_ci95,
            )
        lines.append(f"{task_id} {agent}: {status}{detail}")
    return lines


def _task_ci_detail(
    left_pass: float,
    left_ci: Tuple[float, float],
    right_pass: float,
    right_ci: Tuple[float, float],
) -> str:
    return (
        f" pass_at_1 {left_pass:.3f} ci95={left_ci[0]:.3f}..{left_ci[1]:.3f} -> "
        f"{right_pass:.3f} ci95={right_ci[0]:.3f}..{right_ci[1]:.3f}"
    )
