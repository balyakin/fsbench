"""Codex CLI adapter."""

from pathlib import Path
from typing import Optional, Sequence

from fsbench.adapters.base import CliAgentAdapter, Usage, parse_json_usage_text


class CodexAdapter(CliAgentAdapter):
    """Runs the Codex CLI in workspace-write mode."""

    name = "codex"
    provider_name = "codex"
    binary = "codex"
    version_args = ("--version",)

    def __init__(self, name: Optional[str] = None, model: Optional[str] = None) -> None:
        """Stores optional CLI model override."""
        if name is not None:
            self.name = name
        self.model = model

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds the Codex CLI argv."""
        argv = [
            self.binary,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--approval-policy",
            "never",
            prompt,
        ]
        if self.model is not None:
            argv[2:2] = ["--model", self.model]
        return argv

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses Codex JSONL usage events."""
        return parse_json_usage_text(f"{stdout}\n{stderr}")
