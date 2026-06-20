"""Aider CLI adapter."""

from pathlib import Path
from typing import Sequence

from fsbench.adapters.base import CliAgentAdapter, Usage, parse_text_usage


class AiderAdapter(CliAgentAdapter):
    """Runs the Aider CLI with a prompt file."""

    name = "aider"
    provider_name = "aider"
    binary = "aider"
    version_args = ("--version",)

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds the Aider CLI argv."""
        return [
            self.binary,
            "--message-file",
            "task.md",
            "--yes-always",
            "--no-stream",
            "--no-pretty",
            "--no-check-update",
            "--no-analytics",
        ]

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses Aider text usage output."""
        return parse_text_usage(f"{stdout}\n{stderr}")
