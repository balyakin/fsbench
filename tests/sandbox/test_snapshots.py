import socket
import tempfile
from pathlib import Path

import pytest

from fsbench.sandbox.snapshots import build_snapshot, compare_snapshots


def test_build_snapshot_sorts_paths(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    # ACT
    snapshot = build_snapshot(tmp_path)

    # ASSERT
    assert list(snapshot.files) == ["a.txt", "b.txt"]


def test_compare_snapshots_detects_changes(tmp_path: Path) -> None:
    # ARRANGE
    (tmp_path / "old.txt").write_text("old", encoding="utf-8")
    (tmp_path / "same.txt").write_text("same", encoding="utf-8")
    base = build_snapshot(tmp_path)
    (tmp_path / "old.txt").unlink()
    (tmp_path / "same.txt").write_text("changed", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")

    # ACT
    diff = compare_snapshots(base, build_snapshot(tmp_path))

    # ASSERT
    assert diff.added == ["new.txt"]
    assert diff.removed == ["old.txt"]
    assert diff.modified == ["same.txt"]


def test_build_snapshot_records_socket_without_opening(tmp_path: Path) -> None:
    # ARRANGE
    with tempfile.TemporaryDirectory(prefix="fsb-", dir="/private/tmp") as root:
        root_path = Path(root)
        socket_path = root_path / "agent.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(socket_path))
            # ACT
            snapshot = build_snapshot(root_path)
        except OSError as error:
            pytest.skip(f"cannot create unix socket: {error}")
        finally:
            server.close()

    # ASSERT
    assert "agent.sock" in snapshot.files
    assert snapshot.files["agent.sock"].size == 0
