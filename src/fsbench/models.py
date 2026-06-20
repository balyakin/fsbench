"""Pydantic models for task manifests, settings, run results, and reports."""

from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fsbench.constants import DEFAULT_CHECK_TIMEOUT_S, DEFAULT_TIMEOUT_S, MAX_CHECKS_PER_TASK


class RunErrorKind(StrEnum):
    """Describes a normalized run error category."""

    NONE = "none"
    AGENT_NOT_FOUND = "agent_not_found"
    AGENT_SMOKE_FAILED = "agent_smoke_failed"
    TIMEOUT = "timeout"
    OOM = "oom"
    SANDBOX_ERROR = "sandbox_error"
    CHECK_TIMEOUT = "check_timeout"
    CHECK_FAILED = "check_failed"
    CHECK_CRASH = "check_crash"
    HARNESS_CRASH = "harness_crash"
    INTERRUPTED = "interrupted"
    SCHEMA_ERROR = "schema_error"
    EGRESS_ERROR = "egress_error"
    BUDGET_EXCEEDED = "budget_exceeded"


class CheckType(StrEnum):
    """Describes built-in check types supported by the MVP."""

    RUFF = "ruff"
    MYPY = "mypy"
    PYTEST = "pytest"
    AST_DEFINES = "ast_defines"
    AST_SIGNATURE = "ast_signature"
    AST_NO_IMPORT = "ast_no_import"
    CONTENT_PRESENT = "content_present"
    CONTENT_ABSENT = "content_absent"
    FILE_EXISTS = "file_exists"
    FILE_ABSENT = "file_absent"
    DIFF_SCOPE = "diff_scope"
    INTEGRITY = "integrity"
    NO_TEST_TAMPER = "no_test_tamper"


class SandboxKind(StrEnum):
    """Describes supported sandbox backend names."""

    PROCESS = "process"
    BWRAP = "bwrap"
    DOCKER = "docker"


class AgentEnvMode(StrEnum):
    """Describes agent subprocess environment mode."""

    ISOLATED = "isolated"
    HOST = "host"


class Limits(BaseModel):
    """Stores resource limits for a task run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=1, le=3600)
    mem_mb: int = Field(default=2048, ge=128, le=65536)
    nproc: int = Field(default=256, ge=16, le=4096)
    fsize_mb: int = Field(default=256, ge=16, le=8192)


def _validate_relative_path(path: Path) -> Path:
    path_text = path.as_posix()
    if path.is_absolute():
        raise ValueError(f"path must be relative: {path_text}")
    if ".." in path.parts:
        raise ValueError(f"path must not contain '..': {path_text}")
    if "\\" in str(path):
        raise ValueError(f"path must use POSIX separators: {path_text}")
    if path_text == ".":
        raise ValueError("path must not be empty")
    return path


class CheckSpec(BaseModel):
    """Stores a single deterministic check definition from task.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    type: CheckType
    weight: float = Field(default=1.0, gt=0.0, le=100.0)
    check_timeout_s: int = Field(default=DEFAULT_CHECK_TIMEOUT_S, ge=1, le=1800)
    args: List[str] = Field(default_factory=list)
    inject: List[Path] = Field(default_factory=list)
    strict: bool = False
    allow: int = Field(default=0, ge=0, le=100000)
    threshold: int = Field(default=10, ge=1, le=100000)
    symbol: Optional[str] = None
    kind: Optional[Literal["function", "class", "method"]] = None
    in_file: Optional[Path] = None
    signature: Optional[str] = None
    module: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$",
    )
    names: List[str] = Field(default_factory=list)
    forbid_in_globs: List[str] = Field(default_factory=list)
    path: Optional[Path] = None
    pattern: Optional[str] = None
    max_files_changed: Optional[int] = Field(default=None, ge=0, le=100)
    forbid_changes: List[str] = Field(default_factory=list)

    @field_validator("inject")
    @classmethod
    def validate_inject(cls, paths: List[Path]) -> List[Path]:
        """Validates hidden injection paths."""
        return [_validate_relative_path(path) for path in paths]

    @field_validator("in_file", "path")
    @classmethod
    def validate_optional_path(cls, path: Optional[Path]) -> Optional[Path]:
        """Validates optional task paths."""
        if path is None:
            return None
        return _validate_relative_path(path)

    @field_validator("forbid_changes", "forbid_in_globs")
    @classmethod
    def validate_globs(cls, globs: List[str]) -> List[str]:
        """Validates relative POSIX glob patterns."""
        for glob in globs:
            if glob.startswith("/"):
                raise ValueError(f"glob must be relative: {glob}")
            if "\\" in glob:
                raise ValueError(f"glob must use POSIX separators: {glob}")
            if ".." in Path(glob).parts:
                raise ValueError(f"glob must not contain '..': {glob}")
        return globs


class TaskSpec(BaseModel):
    """Stores the complete task manifest loaded from task.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    tier: Literal[1, 2, 3, 4, 5]
    category: Literal[
        "single_file_bugfix",
        "cross_file_refactor",
        "api_preserving_rewrite",
        "concurrency_correctness",
        "performance_bound",
        "property_spec_impl",
        "dependency_surgery",
        "backward_compat",
        "adversarial_decoy",
        "subtle_semantics",
    ]
    description: str = Field(min_length=20, max_length=500)
    timeout_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=10, le=3600)
    editable_files: List[Path] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    required_checks: List[str] = Field(min_length=1)
    checks: List[CheckSpec] = Field(min_length=1, max_length=MAX_CHECKS_PER_TASK)

    @field_validator("editable_files")
    @classmethod
    def validate_editable_files(cls, paths: List[Path]) -> List[Path]:
        """Validates editable workspace paths."""
        return [_validate_relative_path(path) for path in paths]

    @model_validator(mode="after")
    def validate_checks(self) -> "TaskSpec":
        """Validates relationships between checks and required_checks."""
        check_names = [check.name for check in self.checks]
        unique_check_names = set(check_names)
        required_names = set(self.required_checks)
        missing_required_names = required_names.difference(unique_check_names)

        if len(check_names) != len(unique_check_names):
            raise ValueError("check names must be unique")

        if missing_required_names:
            raise ValueError(f"required checks are missing: {sorted(missing_required_names)}")

        return self


class AgentResult(BaseModel):
    """Stores raw agent execution result after output sanitization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: str
    agent_version: Optional[str] = None
    exit_code: Optional[int]
    timed_out: bool
    duration_s: float = Field(ge=0.0)
    cost_usd: Optional[float] = Field(default=None, ge=0.0)
    tokens_in: Optional[int] = Field(default=None, ge=0)
    tokens_out: Optional[int] = Field(default=None, ge=0)
    stdout_tail: str
    stderr_tail: str
    error_kind: RunErrorKind = RunErrorKind.NONE
    error_detail: Optional[str] = None


class CheckResult(BaseModel):
    """Stores the result of one deterministic check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: CheckType
    required: bool
    weight: float = Field(gt=0.0)
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    detail: Dict[str, Any] = Field(default_factory=dict)
    duration_s: float = Field(default=0.0, ge=0.0)
    error_kind: RunErrorKind = RunErrorKind.NONE
    error_detail: Optional[str] = None


class SuiteRef(BaseModel):
    """Stores suite identity used to compare benchmark reports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    corpus_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    corpus_ref_kind: Literal["git", "unknown"] = "git"
    corpus_dirty: bool = False
    calibration_date: Optional[str] = None
    calibration_agents: List[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """Stores one task-agent-repeat result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_id: str
    task_id: str
    task_version: str
    agent: str
    repeat: int = Field(ge=0)
    seed: int = Field(ge=0)
    agent_result: AgentResult
    checks: List[CheckResult]
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    error_kind: RunErrorKind = RunErrorKind.NONE
    error_detail: Optional[str] = None
    started_at: str
    finished_at: str
    artifacts_dir: Optional[str] = None
    task_version_hash: str
    env_manifest_hash: str


class TaskAgentAggregate(BaseModel):
    """Stores aggregate metrics for one task-agent pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    agent: str
    repeats: int = Field(ge=1)
    successes: int = Field(ge=0)
    pass_at_1: float = Field(ge=0.0, le=1.0)
    pass_at_k: Dict[str, float]
    pass_all_at_k: Dict[str, float]
    pass_at_1_ci95: Tuple[float, float]
    mean_score: float = Field(ge=0.0, le=1.0)
    score_std_dev: Optional[float] = Field(default=None, ge=0.0)
    mean_cost_usd: Optional[float] = Field(default=None, ge=0.0)
    dollars_per_solve: Optional[float] = Field(default=None, ge=0.0)
    mean_duration_s: float = Field(ge=0.0)


class BenchmarkReport(BaseModel):
    """Stores the complete public JSON report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_id: str
    generated_at: str
    suite: SuiteRef
    metadata: Dict[str, str]
    runs: List[RunResult]
    aggregates: List[TaskAgentAggregate]


class ProviderProfile(BaseModel):
    """Stores non-secret provider configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env_allowlist: List[str] = Field(default_factory=list)
    required_env: List[str] = Field(default_factory=list)
    base_url_env: Optional[str] = None
    max_parallel: Optional[int] = Field(default=None, ge=1, le=100)


class EgressSettings(BaseModel):
    """Stores egress mode settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strict: bool = False
    allowlist: List[str] = Field(default_factory=list)


class ReportSettings(BaseModel):
    """Stores report rendering settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keep_artifacts: bool = True
    inline_diff_max_bytes: int = Field(default=65536, ge=0, le=1048576)


class FsbenchSettings(BaseModel):
    """Stores fsbench local settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_seed: int = Field(default=42, ge=0)
    parallel: int = Field(default=4, ge=1, le=128)
    sandbox: SandboxKind = SandboxKind.PROCESS
    agent_env: AgentEnvMode = AgentEnvMode.ISOLATED
    default_repeats: int = Field(default=1, ge=1, le=100)
    agents: Dict[str, str] = Field(default_factory=dict)
    providers: Dict[str, ProviderProfile] = Field(default_factory=dict)
    egress: EgressSettings = Field(default_factory=EgressSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
