"""Async suite orchestrator."""

import asyncio
import hashlib
import json
import os
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field

from fsbench.adapters.registry import get_adapter_for_task, get_real_adapter, resolve_adapter_target
from fsbench.checks.registry import run_all_checks
from fsbench.config import load_settings
from fsbench.constants import HARNESS_LOG_NAME, RUNS_DATABASE_NAME, SCHEMA_VERSION
from fsbench.doctor import build_env_manifest_hash
from fsbench.errors import ConfigurationError
from fsbench.logging import GLOBAL_SCRUBBER, configure_logging, get_logger
from fsbench.models import AgentEnvMode, AgentResult, FsbenchSettings, RunErrorKind, RunResult, SandboxKind
from fsbench.report.csv_report import export_csv_reports
from fsbench.report.html_report import export_html_report
from fsbench.report.json_report import export_json_report, export_runs_jsonl
from fsbench.sandbox.base import SandboxBackend, Workspace, make_workspace
from fsbench.sandbox.bwrap import BubblewrapBackend
from fsbench.sandbox.docker import DockerBackend
from fsbench.sandbox.environment import build_agent_env, build_check_env
from fsbench.sandbox.process import ProcessBackend
from fsbench.sandbox.snapshots import (
    build_snapshot,
    compare_snapshots,
    write_changed_files_artifact,
    write_text_diff_artifact,
)
from fsbench.scoring import aggregate_runs, score_run
from fsbench.seed import build_check_seed, build_run_seed
from fsbench.store import RunStore, canonical_json, close_database, initialize_schema, open_database, utc_now_iso
from fsbench.tasks.loader import TaskBundle, compute_task_version_hash, discover_tasks, protected_test_paths

_RUN_SEQUENCE = 0


class RunSuiteOptions(BaseModel):
    """Stores CLI options for a suite run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_paths: List[str]
    agents: List[str]
    repeats: int = Field(ge=1)
    run_dir: Optional[Path] = None
    dry_run: bool = False
    max_cost_usd: Optional[float] = Field(default=None, ge=0.0)
    sandbox: Optional[SandboxKind] = None
    agent_env: Optional[AgentEnvMode] = None
    config_path: Optional[Path] = None
    keep_artifacts: Optional[bool] = None


class RunSuiteSummary(BaseModel):
    """Stores a concise run-suite outcome for CLI output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    run_dir: Optional[Path]
    planned_cells: int
    resume_hits: int
    pending_cells: int
    completed_cells: int
    skipped_adapters: Dict[str, str]
    env_manifest_hash: str
    timeout_ceiling_s: int
    shutdown_reason: Optional[str] = None


class MatrixCell(BaseModel):
    """Stores one task-agent-repeat matrix cell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    agent: str
    repeat: int
    seed: int


def build_run_id(tasks: Sequence[str], agents: Sequence[str], repeats: int, sandbox: SandboxKind) -> str:
    """Builds a deterministic-format run id with a content hash suffix."""
    global _RUN_SEQUENCE
    _RUN_SEQUENCE += 1
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "agents": list(agents),
        "pid": os.getpid(),
        "repeats": repeats,
        "sandbox": sandbox.value,
        "sequence": _RUN_SEQUENCE,
        "tasks": list(tasks),
        "timestamp": timestamp,
    }
    suffix = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:8]
    return f"{timestamp}-{suffix}"


async def _open_run_store(run_dir: Path) -> Tuple[aiosqlite.Connection, RunStore]:
    connection = await open_database(run_dir / RUNS_DATABASE_NAME)
    try:
        await initialize_schema(connection, SCHEMA_VERSION)
        store = RunStore(connection)
        return connection, store
    except Exception:
        await close_database(connection)
        raise


async def run_suite(options: RunSuiteOptions) -> RunSuiteSummary:
    """Runs or dry-runs a task-agent-repeat suite matrix."""
    settings = load_settings(options.config_path)
    if options.sandbox is not None:
        settings = settings.model_copy(update={"sandbox": options.sandbox})
    if options.agent_env is not None:
        settings = settings.model_copy(update={"agent_env": options.agent_env})
    if options.keep_artifacts is not None:
        settings = settings.model_copy(
            update={"report": settings.report.model_copy(update={"keep_artifacts": options.keep_artifacts})}
        )
    agents = sorted(options.agents)
    tasks = discover_tasks(options.task_paths)
    task_ids = [task.spec.id for task in tasks]
    run_id = build_run_id(task_ids, agents, options.repeats, settings.sandbox)
    run_dir_exists_before = options.run_dir is not None and options.run_dir.exists()
    run_dir = _resolve_run_dir(options, run_id)

    if options.dry_run and not run_dir_exists_before:
        configure_logging(None)
        store = None
        connection = None
    else:
        if not options.dry_run:
            run_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(run_dir / HARNESS_LOG_NAME)
        store_pair = await _open_run_store(run_dir)
        connection = store_pair[0]
        store = store_pair[1]
        existing_run_id = await store.get_metadata("run_id")
        if existing_run_id is not None:
            run_id = existing_run_id

    try:
        logger = get_logger("fsbench.orchestrator").bind(run_id=run_id)
        task_hashes = {task.spec.id: compute_task_version_hash(task) for task in tasks}
        env_manifest_hash = await build_env_manifest_hash(settings, agents)
        metadata = await _build_metadata(
            run_id=run_id,
            settings=settings,
            tasks=tasks,
            agents=agents,
            repeats=options.repeats,
            task_hashes=task_hashes,
            env_manifest_hash=env_manifest_hash,
        )
        if store is not None:
            await _initialize_or_validate_metadata(store, metadata, run_dir_exists_before)

        matrix = _build_matrix(tasks=tasks, agents=agents, repeats=options.repeats, base_seed=settings.base_seed)
        resume_hits = await _count_resume_hits(store, matrix, task_hashes, env_manifest_hash)
        pending_cells = len(matrix) - resume_hits
        timeout_ceiling_s = sum(_task_by_id(tasks)[cell.task_id].spec.timeout_s for cell in matrix)
        if options.dry_run:
            if connection is not None:
                await close_database(connection)
            return RunSuiteSummary(
                run_id=run_id,
                run_dir=run_dir if options.run_dir is not None else None,
                planned_cells=len(matrix),
                resume_hits=resume_hits,
                pending_cells=pending_cells,
                completed_cells=0,
                skipped_adapters={},
                env_manifest_hash=env_manifest_hash,
                timeout_ceiling_s=timeout_ceiling_s,
            )

        if store is None or connection is None:
            raise ConfigurationError("run store was not initialized")

        task_map = _task_by_id(tasks)
        skipped_adapters = await _preflight_adapters(settings=settings, agents=agents)
        if skipped_adapters:
            await store.set_metadata("skipped_adapters_json", json.dumps(skipped_adapters, sort_keys=True))
        runnable_matrix = [cell for cell in matrix if cell.agent not in skipped_adapters]
        shutdown = _ShutdownFlag()
        _install_signal_handlers(shutdown)
        global_semaphore = asyncio.Semaphore(settings.parallel)
        provider_semaphores = _provider_semaphores(settings=settings, agents=agents)
        completed_cells = 0
        known_spend_usd = 0.0
        active: Set[asyncio.Task[RunResult]] = set()
        index = 0
    except Exception:
        await close_database(connection)
        raise
    try:
        while index < len(runnable_matrix) or active:
            while index < len(runnable_matrix) and len(active) < settings.parallel and shutdown.reason is None:
                cell = runnable_matrix[index]
                index += 1
                if options.max_cost_usd is not None and known_spend_usd >= options.max_cost_usd:
                    shutdown.reason = RunErrorKind.BUDGET_EXCEEDED.value
                    await store.set_metadata("shutdown_reason", shutdown.reason)
                    break
                if await store.has_completed_run(
                    task_id=cell.task_id,
                    agent=cell.agent,
                    repeat=cell.repeat,
                    seed=cell.seed,
                    task_version_hash=task_hashes[cell.task_id],
                    env_manifest_hash=env_manifest_hash,
                ):
                    continue
                task = task_map[cell.task_id]
                active.add(
                    asyncio.create_task(
                        _run_cell_with_semaphores(
                            cell=cell,
                            task=task,
                            run_id=run_id,
                            run_dir=run_dir,
                            settings=settings,
                            task_version_hash=task_hashes[cell.task_id],
                            env_manifest_hash=env_manifest_hash,
                            global_semaphore=global_semaphore,
                            provider_semaphores=provider_semaphores,
                        )
                    )
                )
            if not active:
                if shutdown.reason is not None:
                    break
                continue
            done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for done_task in done:
                try:
                    run = done_task.result()
                except asyncio.CancelledError:
                    shutdown.reason = shutdown.reason or RunErrorKind.INTERRUPTED.value
                    await store.set_metadata("shutdown_reason", shutdown.reason)
                    continue
                except Exception as error:
                    logger.exception("cell_task_crashed", error=str(error))
                    shutdown.reason = shutdown.reason or RunErrorKind.HARNESS_CRASH.value
                    await store.set_metadata("shutdown_reason", shutdown.reason)
                    continue
                await store.save_run(run)
                await _append_jsonl(run_dir / "runs.jsonl", run)
                completed_cells += 1
                if run.agent_result.cost_usd is not None:
                    known_spend_usd += run.agent_result.cost_usd
                elif options.max_cost_usd is not None:
                    logger.warning("budget_cost_unknown", task_id=run.task_id, agent=run.agent, repeat=run.repeat)
        if shutdown.reason is not None:
            await store.set_metadata("shutdown_reason", shutdown.reason)
        runs = await store.list_runs()
        await store.replace_aggregates(aggregate_runs(runs))
        report = await export_json_report(run_dir, store)
        await export_runs_jsonl(run_dir, store)
        export_csv_reports(run_dir, report)
        export_html_report(run_dir, report, inline_diff_max_bytes=settings.report.inline_diff_max_bytes)
        return RunSuiteSummary(
            run_id=run_id,
            run_dir=run_dir,
            planned_cells=len(matrix),
            resume_hits=resume_hits,
            pending_cells=pending_cells,
            completed_cells=completed_cells,
            skipped_adapters=skipped_adapters,
            env_manifest_hash=env_manifest_hash,
            timeout_ceiling_s=timeout_ceiling_s,
            shutdown_reason=shutdown.reason,
        )
    finally:
        for active_task in active:
            active_task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        await close_database(connection)


async def _run_cell_with_semaphores(
    cell: MatrixCell,
    task: TaskBundle,
    run_id: str,
    run_dir: Path,
    settings: FsbenchSettings,
    task_version_hash: str,
    env_manifest_hash: str,
    global_semaphore: asyncio.Semaphore,
    provider_semaphores: Dict[str, asyncio.Semaphore],
) -> RunResult:
    adapter = get_adapter_for_task(cell.agent, task.solution_dir, settings.agents)
    semaphore = provider_semaphores.get(adapter.provider_name)
    async with global_semaphore:
        if semaphore is None:
            return await run_cell(
                cell=cell,
                task=task,
                run_id=run_id,
                run_dir=run_dir,
                settings=settings,
                task_version_hash=task_version_hash,
                env_manifest_hash=env_manifest_hash,
            )
        async with semaphore:
            return await run_cell(
                cell=cell,
                task=task,
                run_id=run_id,
                run_dir=run_dir,
                settings=settings,
                task_version_hash=task_version_hash,
                env_manifest_hash=env_manifest_hash,
            )


async def run_cell(
    cell: MatrixCell,
    task: TaskBundle,
    run_id: str,
    run_dir: Path,
    settings: FsbenchSettings,
    task_version_hash: str,
    env_manifest_hash: str,
) -> RunResult:
    """Runs one task-agent-repeat cell end to end."""
    started_at = utc_now_iso()
    artifact_relative = Path("artifacts") / task.spec.id / cell.agent / str(cell.repeat)
    artifact_dir = run_dir / artifact_relative
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    agent_result = _harness_agent_result(cell.agent, "not started")
    passed = False
    score = 0.0
    error_kind = RunErrorKind.NONE
    error_detail = None
    workspace: Optional[Workspace] = None
    try:
        workspace = make_workspace(
            run_dir=run_dir,
            task_id=task.spec.id,
            agent=cell.agent,
            repeat=cell.repeat,
            workspace_zip=task.workspace_zip,
            prompt_path=task.prompt_path,
            protected_test_paths=protected_test_paths(task),
        )
        sandbox_context = await _sandbox_backend(settings.sandbox).enter(workspace.root)
        adapter = get_adapter_for_task(cell.agent, task.solution_dir, settings.agents)
        provider_profile = settings.providers.get(adapter.provider_name)
        agent_env = build_agent_env(workspace.root, settings, provider_profile, GLOBAL_SCRUBBER)
        agent_result = await adapter.run(
            sandbox_context=sandbox_context,
            workspace_root=workspace.root,
            env=agent_env,
            timeout_s=task.spec.timeout_s,
            limits=task.spec.limits,
            artifact_dir=artifact_dir,
            scrubber=GLOBAL_SCRUBBER,
        )
        current_snapshot = build_snapshot(workspace.root)
        diff = compare_snapshots(workspace.base_snapshot, current_snapshot)
        write_changed_files_artifact(diff, artifact_dir / "changed_files.json", GLOBAL_SCRUBBER)
        write_text_diff_artifact(task.workspace_zip, workspace.root, diff, artifact_dir / "diff.patch", GLOBAL_SCRUBBER)
        check_env = build_check_env(workspace.root, build_check_seed(settings.base_seed, task.spec.id))
        checks = await run_all_checks(
            task=task,
            workspace=workspace,
            sandbox_context=sandbox_context,
            check_env=check_env,
            artifact_dir=artifact_dir,
        )
        core_files = _find_core_files(workspace.root)
        if core_files:
            core_files_path = artifact_dir / "core_files.json"
            core_files_path.write_text(json.dumps(core_files, indent=2), encoding="utf-8")
            error_kind = RunErrorKind.SANDBOX_ERROR
            error_detail = (artifact_relative / core_files_path.name).as_posix()
        passed, score = score_run(checks)
        if agent_result.error_kind != RunErrorKind.NONE and error_kind == RunErrorKind.NONE:
            error_kind = agent_result.error_kind
            passed = False
        if error_kind != RunErrorKind.NONE:
            passed = False
    except asyncio.CancelledError:
        raise
    except Exception as error:
        error_kind = RunErrorKind.HARNESS_CRASH
        scrubbed_detail = GLOBAL_SCRUBBER.scrub_text(str(error))
        error_detail = scrubbed_detail
        agent_result = _harness_agent_result(cell.agent, scrubbed_detail)
    finally:
        if workspace is not None and not settings.report.keep_artifacts:
            shutil.rmtree(workspace.root, ignore_errors=True)
    return RunResult(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        task_id=task.spec.id,
        task_version=task.spec.version,
        agent=cell.agent,
        repeat=cell.repeat,
        seed=cell.seed,
        agent_result=agent_result,
        checks=checks,
        passed=passed,
        score=score,
        error_kind=error_kind,
        error_detail=error_detail,
        started_at=started_at,
        finished_at=utc_now_iso(),
        artifacts_dir=artifact_relative.as_posix(),
        task_version_hash=task_version_hash,
        env_manifest_hash=env_manifest_hash,
    )


def _resolve_run_dir(options: RunSuiteOptions, run_id: str) -> Path:
    if options.run_dir is not None:
        return options.run_dir
    return Path("runs") / run_id


def _build_matrix(
    tasks: Sequence[TaskBundle],
    agents: Sequence[str],
    repeats: int,
    base_seed: int,
) -> List[MatrixCell]:
    cells: List[MatrixCell] = []
    for task in sorted(tasks, key=lambda item: item.spec.id):
        for agent in sorted(agents):
            for repeat in range(repeats):
                cells.append(
                    MatrixCell(
                        task_id=task.spec.id,
                        agent=agent,
                        repeat=repeat,
                        seed=build_run_seed(base_seed, task.spec.id, agent, repeat),
                    )
                )
    return cells


def _task_by_id(tasks: Sequence[TaskBundle]) -> Dict[str, TaskBundle]:
    return {task.spec.id: task for task in tasks}


async def _count_resume_hits(
    store: Optional[RunStore],
    matrix: Sequence[MatrixCell],
    task_hashes: Dict[str, str],
    env_manifest_hash: str,
) -> int:
    if store is None:
        return 0
    hits = 0
    for cell in matrix:
        if await store.has_completed_run(
            task_id=cell.task_id,
            agent=cell.agent,
            repeat=cell.repeat,
            seed=cell.seed,
            task_version_hash=task_hashes[cell.task_id],
            env_manifest_hash=env_manifest_hash,
        ):
            hits += 1
    return hits


async def _build_metadata(
    run_id: str,
    settings: FsbenchSettings,
    tasks: Sequence[TaskBundle],
    agents: Sequence[str],
    repeats: int,
    task_hashes: Dict[str, str],
    env_manifest_hash: str,
) -> Dict[str, str]:
    corpus_git_sha, corpus_ref_kind, corpus_dirty = await _corpus_ref(Path.cwd())
    return {
        "agent_selection": json.dumps(list(agents), sort_keys=True),
        "agent_env": settings.agent_env.value,
        "corpus_dirty": "true" if corpus_dirty else "false",
        "corpus_git_sha": corpus_git_sha,
        "corpus_ref_kind": corpus_ref_kind,
        "created_at": utc_now_iso(),
        "env_manifest_hash": env_manifest_hash,
        "repeats": str(repeats),
        "run_id": run_id,
        "sandbox": settings.sandbox.value,
        "schema_version": SCHEMA_VERSION,
        "suite_name": "fsbench-open",
        "suite_version": "0.1.0",
        "task_selection": json.dumps([task.spec.id for task in tasks], sort_keys=True),
        "task_version_hashes_json": json.dumps(task_hashes, sort_keys=True),
    }


async def _initialize_or_validate_metadata(
    store: RunStore,
    metadata: Dict[str, str],
    validate_existing: bool,
) -> None:
    if validate_existing:
        existing = await store.get_metadata_dict()
        for key in [
            "env_manifest_hash",
            "task_selection",
            "task_version_hashes_json",
            "agent_selection",
            "agent_env",
            "repeats",
            "sandbox",
        ]:
            if key in existing and existing[key] != metadata[key]:
                raise ConfigurationError(f"resume metadata mismatch for {key}")
    existing_run_id = await store.get_metadata("run_id")
    if existing_run_id is not None:
        metadata = dict(metadata)
        metadata["run_id"] = existing_run_id
    await store.set_metadata_many(metadata)


async def _preflight_adapters(settings: FsbenchSettings, agents: Sequence[str]) -> Dict[str, str]:
    skipped: Dict[str, str] = {}
    for agent in sorted(agents):
        target = resolve_adapter_target(agent, settings.agents)
        adapter_name = target[0]
        if adapter_name == "oracle":
            continue
        adapter = get_real_adapter(agent, settings.agents)
        provider_profile = settings.providers.get(adapter.provider_name)
        env = build_agent_env(Path.cwd(), settings, provider_profile, GLOBAL_SCRUBBER)
        available, reason = await adapter.smoke_test(env=env, provider_profile=provider_profile)
        if not available:
            skipped[agent] = reason
    return skipped


def _provider_semaphores(settings: FsbenchSettings, agents: Sequence[str]) -> Dict[str, asyncio.Semaphore]:
    semaphores: Dict[str, asyncio.Semaphore] = {}
    for agent in agents:
        target = resolve_adapter_target(agent, settings.agents)
        adapter_name = target[0]
        if adapter_name == "oracle":
            continue
        adapter = get_real_adapter(agent, settings.agents)
        profile = settings.providers.get(adapter.provider_name)
        if profile is not None and profile.max_parallel is not None:
            semaphores[adapter.provider_name] = asyncio.Semaphore(profile.max_parallel)
    return semaphores


def _sandbox_backend(kind: SandboxKind) -> SandboxBackend:
    if kind == SandboxKind.PROCESS:
        return ProcessBackend()
    if kind == SandboxKind.BWRAP:
        return BubblewrapBackend()
    if kind == SandboxKind.DOCKER:
        return DockerBackend()  # type: ignore[return-value]
    raise ConfigurationError(f"unknown sandbox backend: {kind.value}")


async def _append_jsonl(path: Path, run: RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json())
        handle.write("\n")


def _harness_agent_result(agent: str, detail: str) -> AgentResult:
    return AgentResult(
        agent=agent,
        agent_version=None,
        exit_code=None,
        timed_out=False,
        duration_s=0.0,
        stdout_tail="",
        stderr_tail="",
        error_kind=RunErrorKind.HARNESS_CRASH,
        error_detail=detail,
    )


def _find_core_files(root: Path) -> List[str]:
    core_files: List[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and (path.name == "core" or path.name.startswith("core.") or path.name.endswith(".core")):
            core_files.append(path.relative_to(root).as_posix())
    return core_files


async def _corpus_ref(cwd: Path) -> Tuple[str, str, bool]:
    try:
        sha = await _git_output(["rev-parse", "HEAD"], cwd)
        status = await _git_output(["status", "--porcelain", "--", "SPEC.md", "tasks"], cwd)
    except ConfigurationError:
        return "0" * 40, "unknown", True
    return sha.strip(), "git", bool(status.strip())


async def _git_output(args: Sequence[str], cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise ConfigurationError(stderr.decode("utf-8", errors="replace"))
    return stdout.decode("utf-8", errors="replace")


class _ShutdownFlag:
    def __init__(self) -> None:
        self.reason: Optional[str] = None


def _install_signal_handlers(shutdown: _ShutdownFlag) -> None:
    def request_shutdown() -> None:
        shutdown.reason = RunErrorKind.INTERRUPTED.value

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for sig in [signal.SIGINT, signal.SIGTERM]:
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            continue
