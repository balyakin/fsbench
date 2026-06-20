"""Pi CLI adapter"""

from pathlib import Path
from typing import Optional, Sequence

from fsbench.adapters.base import CliAgentAdapter, Usage, parse_json_usage_text


class PiAdapter(CliAgentAdapter):
    """Runs the Pi CLI in JSON output mode"""

    name = "pi"
    provider_name = "pi"
    binary = "pi"
    version_args = ("--version",)

    def __init__(self, name: Optional[str] = None, model: Optional[str] = None) -> None:
        """Stores optional CLI model override

        Args:
            name: Optional report agent name
            model: Optional CLI model name
        """
        if name is not None:
            self.name = name
        self.model = model

    def build_argv(self, prompt: str, workspace_root: Path) -> Sequence[str]:
        """Builds the Pi CLI argv

        Args:
            prompt: Task prompt text
            workspace_root: Workspace path

        Returns:
            CLI argv for process execution
        """
        argv = [
            self.binary,
            "-p",
            "--mode",
            "json",
            "--approve",
            "--no-session",
            prompt,
        ]
        if self.model is not None:
            argv[4:4] = ["--model", self.model]
        return argv

    def parse_usage(self, stdout: str, stderr: str) -> Usage:
        """Parses Pi JSON usage output

        Args:
            stdout: Sanitized process stdout
            stderr: Sanitized process stderr

        Returns:
            Parsed usage values
        """
        return parse_json_usage_text(f"{stdout}\n{stderr}")
