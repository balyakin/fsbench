"""Process sandbox backend."""

import asyncio
import os
import signal
import time
from asyncio.subprocess import PIPE
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Optional, Sequence, Unpack

import psutil

from fsbench.constants import DEFAULT_STDIO_TAIL_BYTES
from fsbench.errors import SandboxExecutionError
from fsbench.logging import GLOBAL_SCRUBBER, SecretScrubber
from fsbench.models import Limits
from fsbench.sandbox.base import CompletedProcessResult, ProcessResult, ProcessRunKwargs, SandboxContext


class ProcessBackend:
    """Creates process sandbox contexts."""

    async def enter(self, root: Path) -> SandboxContext:
        """Returns a process sandbox context rooted at the workspace."""
        return ProcessSandboxContext(root=root, scrubber=GLOBAL_SCRUBBER)


class ProcessSandboxContext:
    """Runs commands as local subprocesses with timeout and cleanup."""

    def __init__(self, root: Path, scrubber: SecretScrubber) -> None:
        """Stores workspace root and scrubber."""
        self.root = root
        self.scrubber = scrubber

    async def run_process(
        self,
        argv: Sequence[str],
        **kwargs: Unpack[ProcessRunKwargs],
    ) -> ProcessResult:
        """Runs argv with deterministic output capture and timeout."""
        if not argv:
            raise SandboxExecutionError("argv must not be empty")
        cwd = kwargs.get("cwd", self.root)
        env = kwargs.get("env")
        timeout_s = kwargs.get("timeout_s", 300)
        stdin_text = kwargs.get("stdin_text")
        limits = kwargs.get("limits")
        stdout_path = kwargs.get("stdout_path")
        stderr_path = kwargs.get("stderr_path")

        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env,
                stdin=PIPE if stdin_text is not None else None,
                stdout=PIPE,
                stderr=PIPE,
                start_new_session=True,
                preexec_fn=_build_preexec(limits),
            )
        except FileNotFoundError:
            duration_s = time.monotonic() - started
            return CompletedProcessResult(
                exit_code=127,
                timed_out=False,
                duration_s=duration_s,
                stdout_tail="",
                stderr_tail=self.scrubber.scrub_text(f"command not found: {argv[0]}"),
            )
        except Exception as error:
            raise SandboxExecutionError(f"cannot start process: {argv[0]}") from error

        stdout_tail = ""
        stderr_tail = ""
        process_group_id = process.pid
        stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_path, self.scrubber))
        stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_path, self.scrubber))
        timed_out = False
        try:
            try:
                async with asyncio.timeout(timeout_s):
                    if stdin_text is not None and process.stdin is not None:
                        try:
                            process.stdin.write(stdin_text.encode("utf-8"))
                            await process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        finally:
                            process.stdin.close()
                    await process.wait()
                    output = await asyncio.gather(stdout_task, stderr_task)
                    stdout_tail = output[0]
                    stderr_tail = output[1]
            except TimeoutError:
                timed_out = True
                await _kill_process_group_id(process_group_id)
                await process.wait()
        except asyncio.CancelledError:
            await _kill_process_group_id(process_group_id)
            raise
        finally:
            await _kill_process_group_id(process_group_id)
            await _close_reader_tasks(stdout_task, stderr_task)

        duration_s = time.monotonic() - started
        return CompletedProcessResult(
            exit_code=process.returncode,
            timed_out=timed_out,
            duration_s=duration_s,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )


async def _close_reader_tasks(stdout_task: asyncio.Task[str], stderr_task: asyncio.Task[str]) -> None:
    for reader_task in [stdout_task, stderr_task]:
        if not reader_task.done():
            reader_task.cancel()
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


def _build_preexec(limits: Optional[Limits]) -> Optional[Callable[[], Any]]:
    if os.name != "posix" or limits is None:
        return None

    def set_limits() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s + 1))
        mem_bytes = limits.mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        fsize_bytes = limits.fsize_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))

    return set_limits


async def _read_stream(
    stream: Optional[asyncio.StreamReader],
    artifact_path: Optional[Path],
    scrubber: SecretScrubber,
) -> str:
    if stream is None:
        return ""
    tail: Deque[str] = deque()
    tail_bytes = 0
    artifact_handle = None
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_handle = artifact_path.open("a", encoding="utf-8")
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            scrubbed = scrubber.scrub_bytes(chunk)
            encoded_size = len(scrubbed.encode("utf-8", errors="replace"))
            tail.append(scrubbed)
            tail_bytes += encoded_size
            while tail_bytes > DEFAULT_STDIO_TAIL_BYTES and tail:
                removed = tail.popleft()
                tail_bytes -= len(removed.encode("utf-8", errors="replace"))
            if artifact_handle is not None:
                artifact_handle.write(scrubbed)
                artifact_handle.flush()
    finally:
        if artifact_handle is not None:
            artifact_handle.close()
    joined_bytes = "".join(tail).encode("utf-8", errors="replace")
    return joined_bytes[-DEFAULT_STDIO_TAIL_BYTES:].decode("utf-8", errors="ignore")


async def terminate_process_tree(pid: int) -> None:
    """Terminates a process tree using psutil with process-group fallback."""
    try:
        await asyncio.to_thread(_terminate_process_tree_blocking, pid)
    except psutil.Error:
        await _kill_process_group(pid)


def _terminate_process_tree_blocking(pid: int) -> None:
    parent = psutil.Process(pid)
    processes = parent.children(recursive=True)
    processes.append(parent)
    for child_process in processes:
        try:
            child_process.terminate()
        except psutil.Error:
            continue
    wait_result = psutil.wait_procs(processes, timeout=5.0)
    alive_processes = wait_result[1]
    for child_process in alive_processes:
        try:
            child_process.kill()
        except psutil.Error:
            continue
    psutil.wait_procs(alive_processes, timeout=2.0)


async def _kill_process_group_id(process_group_id: int) -> None:
    if os.name != "posix":
        return
    for signal_number in [signal.SIGTERM, signal.SIGKILL]:
        try:
            os.killpg(process_group_id, signal_number)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.5)


async def _kill_process_group(pid: int) -> None:
    if os.name != "posix":
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    for sig in [signal.SIGTERM, signal.SIGKILL]:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.5)
