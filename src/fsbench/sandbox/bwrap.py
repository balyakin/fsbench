"""Bubblewrap sandbox backend."""

import platform
import shutil
from pathlib import Path
from typing import List, Sequence, Unpack

from fsbench.errors import SandboxUnavailableError
from fsbench.logging import GLOBAL_SCRUBBER
from fsbench.sandbox.base import ProcessResult, ProcessRunKwargs, SandboxContext
from fsbench.sandbox.process import ProcessSandboxContext


class BubblewrapBackend:
    """Creates Bubblewrap-backed sandbox contexts on Linux."""

    def __init__(self, share_net: bool = False) -> None:
        """Stores network sharing mode."""
        self.share_net = share_net

    async def enter(self, root: Path) -> SandboxContext:
        """Prepares a Bubblewrap context for a workspace."""
        if platform.system() != "Linux":
            raise SandboxUnavailableError("bwrap sandbox is only available on Linux")
        bwrap_path = shutil.which("bwrap")
        if bwrap_path is None:
            raise SandboxUnavailableError("bwrap binary is not available")
        return BubblewrapSandboxContext(root=root, bwrap_path=bwrap_path, share_net=self.share_net)


class BubblewrapSandboxContext:
    """Runs commands through bwrap and delegates process cleanup to ProcessSandboxContext."""

    def __init__(self, root: Path, bwrap_path: str, share_net: bool) -> None:
        """Stores bwrap executable and workspace root."""
        self.root = root
        self.bwrap_path = bwrap_path
        self.share_net = share_net
        self.process_context = ProcessSandboxContext(root=root, scrubber=GLOBAL_SCRUBBER)

    async def run_process(
        self,
        argv: Sequence[str],
        **kwargs: Unpack[ProcessRunKwargs],
    ) -> ProcessResult:
        """Runs argv inside a Bubblewrap command line."""
        bwrap_argv = self._build_bwrap_argv(argv=argv, cwd=kwargs.get("cwd", self.root))
        return await self.process_context.run_process(bwrap_argv, **kwargs)

    def _build_bwrap_argv(self, argv: Sequence[str], cwd: Path) -> List[str]:
        args = [
            self.bwrap_path,
            "--die-with-parent",
            "--unshare-all",
            "--bind",
            str(self.root),
            str(self.root),
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--chdir",
            str(cwd),
        ]
        if self.share_net:
            args.append("--share-net")
        for system_path in ["/usr", "/bin", "/lib", "/lib64"]:
            if Path(system_path).exists():
                args.extend(["--ro-bind", system_path, system_path])
        args.append("--")
        args.extend(argv)
        return args
