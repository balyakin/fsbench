"""HTML report exporter."""

import json
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from fsbench.errors import ReportGenerationError
from fsbench.models import BenchmarkReport, RunResult

MAX_INDEX_HTML_BYTES = 5 * 1024 * 1024


def export_html_report(run_dir: Path, report: BenchmarkReport, inline_diff_max_bytes: int = 65536) -> None:
    """Writes index.html and per-cell HTML pages."""
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    cell_links: Dict[str, str] = {}
    for run in report.runs:
        relative = Path("cells") / run.task_id / run.agent / f"{run.repeat}.html"
        cell_path = run_dir / relative
        cell_path.parent.mkdir(parents=True, exist_ok=True)
        cell_links[_cell_key(run)] = relative.as_posix()
        context = _cell_context(run_dir=run_dir, run=run, inline_diff_max_bytes=inline_diff_max_bytes)
        cell_html = env.get_template("cell.html.j2").render(**context)
        cell_path.write_text(cell_html, encoding="utf-8")
    index_html = env.get_template("index.html.j2").render(
        report=report, cell_links=cell_links, heatmap=_heatmap(report)
    )
    if len(index_html.encode("utf-8")) > MAX_INDEX_HTML_BYTES:
        raise ReportGenerationError("index.html exceeds 5 MB limit")
    (run_dir / "index.html").write_text(index_html, encoding="utf-8")


def _cell_key(run: RunResult) -> str:
    return f"{run.task_id}:{run.agent}:{run.repeat}"


def _cell_context(run_dir: Path, run: RunResult, inline_diff_max_bytes: int) -> Dict[str, object]:
    changed_files: Dict[str, List[str]] = {"added": [], "removed": [], "modified": []}
    diff_inline = ""
    artifacts_dir = Path(run.artifacts_dir) if run.artifacts_dir is not None else None
    if artifacts_dir is not None:
        changed_path = run_dir / artifacts_dir / "changed_files.json"
        if changed_path.exists():
            changed_files = json.loads(changed_path.read_text(encoding="utf-8"))
        diff_path = run_dir / artifacts_dir / "diff.patch"
        if diff_path.exists() and diff_path.stat().st_size <= inline_diff_max_bytes:
            diff_inline = diff_path.read_text(encoding="utf-8")
    return {
        "run": run,
        "changed_files": changed_files,
        "diff_inline": diff_inline,
        "artifacts_dir": "" if artifacts_dir is None else artifacts_dir.as_posix(),
    }


def _heatmap(report: BenchmarkReport) -> Dict[str, Dict[str, float]]:
    heatmap: Dict[str, Dict[str, float]] = {}
    for aggregate in report.aggregates:
        heatmap.setdefault(aggregate.task_id, {})[aggregate.agent] = aggregate.pass_at_1
    return heatmap
