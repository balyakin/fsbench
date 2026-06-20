from fsbench.constants import SCHEMA_VERSION
from fsbench.models import BenchmarkReport, SuiteRef, TaskAgentAggregate
from fsbench.report.json_report import compare_reports


def _report(pass_at_1: float) -> BenchmarkReport:
    aggregate = TaskAgentAggregate(
        task_id="task",
        agent="oracle",
        repeats=1,
        successes=1 if pass_at_1 == 1.0 else 0,
        pass_at_1=pass_at_1,
        pass_at_k={"1": pass_at_1},
        pass_all_at_k={"1": pass_at_1},
        pass_at_1_ci95=(0.0, 1.0),
        mean_score=pass_at_1,
        mean_duration_s=1.0,
    )
    return BenchmarkReport(
        schema_version=SCHEMA_VERSION,
        run_id="run",
        generated_at="2026-06-20T00:00:00Z",
        suite=SuiteRef(
            name="suite", version="0.1.0", corpus_git_sha="0" * 40, corpus_ref_kind="unknown", corpus_dirty=True
        ),
        metadata={},
        runs=[],
        aggregates=[aggregate],
    )


def test_compare_reports_by_task() -> None:
    # ARRANGE
    left = _report(0.0)
    right = _report(1.0)

    # ACT
    warnings, lines = compare_reports(left, right, by_task=True)

    # ASSERT
    assert warnings
    assert any("improved" in line for line in lines)
    assert any("ci95=" in line for line in lines)
