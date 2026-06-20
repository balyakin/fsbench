import asyncio
import sys
import time
from pathlib import Path

from fsbench.sandbox import process as process_module
from fsbench.sandbox.process import ProcessBackend


async def test_process_backend_runs_command(tmp_path: Path) -> None:
    # ARRANGE
    context = await ProcessBackend().enter(tmp_path)

    # ACT
    result = await context.run_process(["python3", "-c", "print('ok')"], cwd=tmp_path, timeout_s=10)

    # ASSERT
    assert result.exit_code == 0
    assert "ok" in result.stdout_tail


async def test_process_backend_times_out(tmp_path: Path) -> None:
    # ARRANGE
    context = await ProcessBackend().enter(tmp_path)

    # ACT
    result = await context.run_process(["python3", "-c", "import time; time.sleep(2)"], cwd=tmp_path, timeout_s=1)

    # ASSERT
    assert result.timed_out is True


async def test_process_backend_times_out_when_child_holds_stdout(tmp_path: Path) -> None:
    # ARRANGE
    context = await ProcessBackend().enter(tmp_path)
    script = (
        "import subprocess\n"
        "import sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)'])\n"
        "print('parent done')\n"
    )

    # ACT
    result = await asyncio.wait_for(
        context.run_process([sys.executable, "-c", script], cwd=tmp_path, timeout_s=1),
        timeout=4,
    )

    # ASSERT
    assert result.timed_out is True


async def test_terminate_process_tree_does_not_block_event_loop(monkeypatch) -> None:
    # ARRANGE
    class FakeProcess:
        def children(self, recursive: bool):
            return []

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    def fake_process(pid: int) -> FakeProcess:
        return FakeProcess()

    def fake_wait_procs(processes, timeout: float):
        time.sleep(0.2)
        return [], []

    monkeypatch.setattr(process_module.psutil, "Process", fake_process)
    monkeypatch.setattr(process_module.psutil, "wait_procs", fake_wait_procs)
    started = time.monotonic()

    # ACT
    terminate_task = asyncio.create_task(process_module.terminate_process_tree(12345))
    await asyncio.sleep(0.01)
    duration_s = time.monotonic() - started
    await terminate_task

    # ASSERT
    assert duration_s < 0.1
