"""SQLite storage for fsbench runs."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from fsbench.errors import StorageError
from fsbench.models import CheckResult, RunResult, TaskAgentAggregate


def canonical_json(data: Dict[str, Any]) -> str:
    """Serializes a mapping as canonical JSON."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now_iso() -> str:
    """Returns the current UTC time in fsbench report format."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def open_database(database_path: Path) -> aiosqlite.Connection:
    """Opens SQLite database and enables required pragmas."""
    connection: Optional[aiosqlite.Connection] = None
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(database_path)
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA synchronous=NORMAL")
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA busy_timeout=5000")
        await connection.commit()
        return connection
    except Exception as error:
        if connection is not None:
            await connection.close()
        raise StorageError(f"cannot open run database: {database_path}") from error


async def initialize_schema(connection: aiosqlite.Connection, schema_version: str) -> None:
    """Creates SQLite schema when it does not exist."""
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_key TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            run_json TEXT NOT NULL,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            repeat INTEGER NOT NULL,
            seed INTEGER NOT NULL,
            task_version_hash TEXT NOT NULL,
            env_manifest_hash TEXT NOT NULL,
            passed INTEGER NOT NULL,
            score REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            run_key TEXT NOT NULL,
            check_name TEXT NOT NULL,
            check_type TEXT NOT NULL,
            required INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            score REAL NOT NULL,
            duration_s REAL NOT NULL,
            detail_json TEXT NOT NULL,
            error_kind TEXT NOT NULL,
            error_detail TEXT,
            PRIMARY KEY (run_key, check_name),
            FOREIGN KEY (run_key) REFERENCES runs(run_key) ON DELETE CASCADE
        )
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_checks_name_passed
        ON checks (check_name, passed)
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS aggregates (
            aggregate_key TEXT PRIMARY KEY,
            aggregate_json TEXT NOT NULL,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            pass_at_1 REAL NOT NULL,
            mean_score REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await connection.execute(
        """
        INSERT OR REPLACE INTO run_metadata (key, value)
        VALUES ('schema_version', ?)
        """,
        (schema_version,),
    )
    await connection.commit()


async def close_database(connection: Optional[aiosqlite.Connection]) -> None:
    """Closes SQLite database if it was opened."""
    if connection is None:
        return

    await connection.close()


class RunStore:
    """Owns all direct SQLite access for one run directory."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        """Stores an open SQLite connection."""
        self.connection = connection

    @staticmethod
    def build_run_key(
        task_id: str,
        agent: str,
        repeat: int,
        seed: int,
        task_version_hash: str,
        env_manifest_hash: str,
    ) -> str:
        """Builds the canonical resume key hash for one matrix cell."""
        payload = {
            "agent": agent,
            "env_manifest_hash": env_manifest_hash,
            "repeat": repeat,
            "seed": seed,
            "task_id": task_id,
            "task_version_hash": task_version_hash,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    async def set_metadata(self, key: str, value: str) -> None:
        """Stores a metadata key."""
        await self.connection.execute(
            "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.connection.commit()

    async def set_metadata_many(self, values: Dict[str, str]) -> None:
        """Stores several metadata keys in one transaction."""
        await self.connection.execute("BEGIN IMMEDIATE")
        try:
            for key, value in sorted(values.items()):
                await self.connection.execute(
                    "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
            await self.connection.commit()
        except Exception as error:
            await self.connection.rollback()
            raise StorageError("cannot store run metadata") from error

    async def get_metadata(self, key: str) -> Optional[str]:
        """Returns one metadata value."""
        cursor = await self.connection.execute("SELECT value FROM run_metadata WHERE key = ?", (key,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return str(row[0])

    async def get_metadata_dict(self) -> Dict[str, str]:
        """Returns all run metadata as a dictionary."""
        cursor = await self.connection.execute("SELECT key, value FROM run_metadata ORDER BY key")
        rows = await cursor.fetchall()
        await cursor.close()
        return {str(row[0]): str(row[1]) for row in rows}

    async def save_run(self, run: RunResult) -> str:
        """Saves one completed RunResult and its CheckResult rows."""
        run_key = self.build_run_key(
            task_id=run.task_id,
            agent=run.agent,
            repeat=run.repeat,
            seed=run.seed,
            task_version_hash=run.task_version_hash,
            env_manifest_hash=run.env_manifest_hash,
        )
        try:
            await self.connection.execute("BEGIN IMMEDIATE")
            await self.connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_key,
                    schema_version,
                    run_json,
                    task_id,
                    agent,
                    repeat,
                    seed,
                    task_version_hash,
                    env_manifest_hash,
                    passed,
                    score,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_key,
                    run.schema_version,
                    canonical_json(run.model_dump(mode="json")),
                    run.task_id,
                    run.agent,
                    run.repeat,
                    run.seed,
                    run.task_version_hash,
                    run.env_manifest_hash,
                    1 if run.passed else 0,
                    run.score,
                    utc_now_iso(),
                ),
            )
            await self.connection.execute("DELETE FROM checks WHERE run_key = ?", (run_key,))
            for check in run.checks:
                await self._insert_check(run_key=run_key, check=check)
            await self.connection.commit()
            return run_key
        except Exception as error:
            await self.connection.rollback()
            raise StorageError("cannot save run result") from error

    async def _insert_check(self, run_key: str, check: CheckResult) -> None:
        await self.connection.execute(
            """
            INSERT INTO checks (
                run_key,
                check_name,
                check_type,
                required,
                passed,
                score,
                duration_s,
                detail_json,
                error_kind,
                error_detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_key,
                check.name,
                check.type.value,
                1 if check.required else 0,
                1 if check.passed else 0,
                check.score,
                check.duration_s,
                canonical_json(check.detail),
                check.error_kind.value,
                check.error_detail,
            ),
        )

    async def has_completed_run(
        self,
        task_id: str,
        agent: str,
        repeat: int,
        seed: int,
        task_version_hash: str,
        env_manifest_hash: str,
    ) -> bool:
        """Returns True when the exact resume key has a saved RunResult."""
        run_key = self.build_run_key(
            task_id=task_id,
            agent=agent,
            repeat=repeat,
            seed=seed,
            task_version_hash=task_version_hash,
            env_manifest_hash=env_manifest_hash,
        )
        cursor = await self.connection.execute("SELECT 1 FROM runs WHERE run_key = ?", (run_key,))
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def get_run(self, task_id: str, agent: str, repeat: int) -> Optional[RunResult]:
        """Returns one run by human-visible matrix coordinates."""
        cursor = await self.connection.execute(
            """
            SELECT run_json FROM runs
            WHERE task_id = ? AND agent = ? AND repeat = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_id, agent, repeat),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return RunResult.model_validate_json(str(row[0]))

    async def list_runs(self) -> List[RunResult]:
        """Returns all saved runs in stable matrix order."""
        cursor = await self.connection.execute(
            """
            SELECT run_json FROM runs
            ORDER BY task_id, agent, repeat
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [RunResult.model_validate_json(str(row[0])) for row in rows]

    async def replace_aggregates(self, aggregates: List[TaskAgentAggregate]) -> None:
        """Replaces persisted aggregates with a freshly computed set."""
        try:
            await self.connection.execute("BEGIN IMMEDIATE")
            await self.connection.execute("DELETE FROM aggregates")
            for aggregate in aggregates:
                aggregate_key = hashlib.sha256(
                    canonical_json({"agent": aggregate.agent, "task_id": aggregate.task_id}).encode("utf-8")
                ).hexdigest()
                await self.connection.execute(
                    """
                    INSERT INTO aggregates (
                        aggregate_key,
                        aggregate_json,
                        task_id,
                        agent,
                        pass_at_1,
                        mean_score,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        aggregate_key,
                        canonical_json(aggregate.model_dump(mode="json")),
                        aggregate.task_id,
                        aggregate.agent,
                        aggregate.pass_at_1,
                        aggregate.mean_score,
                        utc_now_iso(),
                    ),
                )
            await self.connection.commit()
        except Exception as error:
            await self.connection.rollback()
            raise StorageError("cannot replace aggregates") from error

    async def list_aggregates(self) -> List[TaskAgentAggregate]:
        """Returns all aggregate rows in stable order."""
        cursor = await self.connection.execute(
            """
            SELECT aggregate_json FROM aggregates
            ORDER BY agent, task_id
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [TaskAgentAggregate.model_validate_json(str(row[0])) for row in rows]
