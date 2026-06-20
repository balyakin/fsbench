"""Structured logging and secret scrubbing."""

import logging as stdlib_logging
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import structlog


class SecretScrubber:
    """Scrubs known secrets and common API-key patterns from text."""

    def __init__(self) -> None:
        """Initializes an empty scrubber."""
        self._secrets: Dict[str, str] = {}
        self._patterns = [
            re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
            re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
            re.compile(r"(?i)(api[_-]?key|token|secret)[=:][A-Za-z0-9_./+=-]{12,}"),
        ]

    def register_secret(self, env_name: str, value: str) -> None:
        """Registers a secret value under the environment variable name that supplied it."""
        if not value:
            return
        self._secrets[value] = f"<{env_name}>"

    def scrub_text(self, text: str) -> str:
        """Returns text with known secrets replaced by safe placeholders."""
        scrubbed = text
        for secret, replacement in sorted(self._secrets.items(), key=lambda item: len(item[0]), reverse=True):
            scrubbed = scrubbed.replace(secret, replacement)
        for pattern in self._patterns:
            scrubbed = pattern.sub("<REDACTED>", scrubbed)
        return scrubbed

    def scrub_bytes(self, chunk: bytes) -> str:
        """Decodes and scrubs a bytes chunk, redacting undecodable binary data."""
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return "<REDACTED_BINARY_CHUNK>"
        return self.scrub_text(text)

    def scrub_value(self, value: Any) -> Any:
        """Recursively scrubs strings inside a JSON-like value."""
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            return {self.scrub_text(str(key)): self.scrub_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.scrub_value(item) for item in value]
        return value


GLOBAL_SCRUBBER = SecretScrubber()


def _scrub_processor(
    logger: stdlib_logging.Logger,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    scrubbed = GLOBAL_SCRUBBER.scrub_value(dict(event_dict))
    return cast(MutableMapping[str, Any], scrubbed)


def configure_logging(log_path: Optional[Path], level: str = "INFO") -> None:
    """Configures stdlib logging and structlog for sanitized JSON-lines logs."""
    handlers: List[stdlib_logging.Handler]
    numeric_level = stdlib_logging.getLevelName(level.upper())
    if log_path is None:
        handlers = [stdlib_logging.NullHandler()]
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers = [stdlib_logging.FileHandler(log_path, encoding="utf-8")]

    stdlib_logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        format="%(message)s",
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _scrub_processor,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Returns a configured structlog logger."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
