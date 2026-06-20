"""Domain exceptions used by fsbench."""


class FsbenchError(Exception):
    """Base class for all fsbench domain errors."""


class ConfigurationError(FsbenchError):
    """Raised when local configuration is invalid."""


class SchemaVersionError(FsbenchError):
    """Raised when a persisted schema version is unsupported."""


class TaskValidationError(FsbenchError):
    """Raised when a benchmark task is invalid."""


class SandboxUnavailableError(FsbenchError):
    """Raised when a requested sandbox backend cannot be used."""


class SandboxExecutionError(FsbenchError):
    """Raised when a sandboxed subprocess cannot be executed."""


class AdapterUnavailableError(FsbenchError):
    """Raised when an adapter binary or required configuration is unavailable."""


class AdapterSmokeTestError(FsbenchError):
    """Raised when an adapter smoke test fails."""


class CheckExecutionError(FsbenchError):
    """Raised when a deterministic check fails to execute correctly."""


class ReportGenerationError(FsbenchError):
    """Raised when report generation fails."""


class StorageError(FsbenchError):
    """Raised when SQLite storage cannot be read or written."""
