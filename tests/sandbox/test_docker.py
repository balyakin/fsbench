from pathlib import Path

import pytest

from fsbench.sandbox.docker import DockerBackend


async def test_docker_backend_is_stub(tmp_path: Path) -> None:
    # ARRANGE
    backend = DockerBackend()

    # ACT / ASSERT
    with pytest.raises(NotImplementedError):
        await backend.enter(tmp_path)
