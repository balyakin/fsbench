"""Claude CLI adapter."""

from pathlib import Path
from typing import Sequence

from fsbench.adapters.base import CliAgentAdapter, Usage, parse_json_usage_text


class ClaudeAdapter(CliAgentAdapter):
    """Runs the Claude CLI in JSON output mode."""

    name = "claude"
    provider_name = "claude"
    binary = "claude"
    version_args = ("--version",)

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds the Claude CLI argv."""
        return [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses Claude JSON usage output."""
        return parse_json_usage_text(f"{stdout}\n{stderr}")
