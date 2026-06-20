from pathlib import Path

import pytest

from fsbench.constants import SCHEMA_VERSION
from fsbench.errors import ReportGenerationError
from fsbench.models import BenchmarkReport, SuiteRef
from fsbench.report.html_report import export_html_report


def test_export_html_report_rejects_oversized_index(tmp_path: Path) -> None:
    # ARRANGE
    report = BenchmarkReport(
        schema_version=SCHEMA_VERSION,
        run_id="x" * (6 * 1024 * 1024),
        generated_at="2026-06-20T00:00:00Z",
        suite=SuiteRef(
            name="suite",
            version="0.1.0",
            corpus_git_sha="0" * 40,
            corpus_ref_kind="unknown",
            corpus_dirty=True,
        ),
        metadata={},
        runs=[],
        aggregates=[],
    )

    # ACT / ASSERT
    with pytest.raises(ReportGenerationError):
        export_html_report(tmp_path, report)
    assert not (tmp_path / "index.html").exists()
