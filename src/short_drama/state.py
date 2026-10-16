"""SQLite job ledger with atomic claims and conservative cost reservations."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator


class StateError(RuntimeError):
    pass


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_key TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    shot_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    owner TEXT,
                    lease_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    job_key TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    job_key TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details TEXT NOT NULL
                );
            """)
            # Atomic first-writer creation also migrates a legacy ledger. Never
            # replace an existing identity: a copied backup keeps the same UUID,
            # whereas an empty replacement at the same path receives a new one.
            connection.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('ledger_uuid',?)", (str(uuid.uuid4()),))
        ledger_id = self.read_ledger_id(self.path)
        if ledger_id is None:
            raise StateError("ledger UUID is invalid; restore a verified backup instead of resetting identity")
        self._ledger_id = ledger_id

    @property
    def ledger_id(self) -> str:
        return self._ledger_id

    @staticmethod
    def read_ledger_id(path: Path) -> str | None:
        """Inspect an existing ledger identity without creating/migrating a DB.

        Missing files, legacy ledgers without identity, corrupt databases and
        invalid UUIDs return None. A caller can fail closed before constructing
        StateStore/VideoEngine when a prior Live execution context expects an ID.
        """
        path = Path(path)
        if not path.is_file():
            return None
        connection = None
        try:
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            row = connection.execute("SELECT value FROM metadata WHERE key='ledger_uuid'").fetchone()
            if row is None or not isinstance(row[0], str):
                return None
            normalized = str(uuid.UUID(row[0]))
            return normalized if row[0] == normalized else None
        except (sqlite3.Error, OSError, ValueError):
            return None
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ensure(self, job: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO jobs(job_key, episode_id, shot_id, payload) VALUES(?,?,?,?)",
                (job["job_key"], job["episode_id"], job["shot_id"], json.dumps(job, ensure_ascii=False)),
            )
        stored = self.get(job["job_key"])
        assert stored is not None
        if stored.get("request_hash") != job.get("request_hash"):
            raise StateError("job-key collision with a different complete request hash")
        return stored

    def get(self, job_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM jobs WHERE job_key=?", (job_key,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute("SELECT payload FROM jobs ORDER BY episode_id, shot_id, job_key").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save(self, job: dict[str, Any]) -> None:
        job["updated_at"] = time.time()
        with self.connection() as connection:
            connection.execute("UPDATE jobs SET payload=? WHERE job_key=?", (json.dumps(job, ensure_ascii=False), job["job_key"]))

    def claim(self, job_key: str, owner: str, lease_seconds: int = 900) -> bool:
        now = time.time()
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET owner=?, lease_until=? WHERE job_key=? AND (owner IS NULL OR owner=? OR lease_until<?)",
                (owner, now + lease_seconds, job_key, owner, now),
            )
            return cursor.rowcount == 1

    def release(self, job_key: str, owner: str) -> None:
        with self.connection() as connection:
            connection.execute("UPDATE jobs SET owner=NULL, lease_until=0 WHERE job_key=? AND owner=?", (job_key, owner))

    def event(self, job_key: str, event: str, details: str = "") -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO events(created_at,job_key,event,details) VALUES(?,?,?,?)", (time.time(), job_key, event, details))

    def reserve(self, job_key: str, episode_id: str, currency: str, amount: Decimal,
                task_limit: Decimal, episode_limit: Decimal, project_limit: Decimal) -> None:
        """Reserve before submitting; never refund unknown/failed provider charges.

        Decimal values are stored as text (no floating point budget accounting).
        A resumed task reuses its reservation instead of charging it again.
        """
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT amount,currency FROM reservations WHERE job_key=?", (job_key,)).fetchone()
            if existing:
                if Decimal(existing["amount"]) != amount or existing["currency"] != currency:
                    raise StateError("existing cost reservation differs; review pricing before proceeding")
                return
            rows = connection.execute("SELECT episode_id,currency,amount FROM reservations").fetchall()
            if any(row["currency"] != currency for row in rows):
                raise StateError("mixed currencies require a separate project budget ledger")
            project = sum((Decimal(row["amount"]) for row in rows), Decimal(0))
            episode = sum((Decimal(row["amount"]) for row in rows if row["episode_id"] == episode_id), Decimal(0))
            if amount > task_limit or episode + amount > episode_limit or project + amount > project_limit:
                raise StateError("budget limit exceeded")
            connection.execute("INSERT INTO reservations VALUES(?,?,?,?)", (job_key, episode_id, currency, str(amount)))

    def reserved_total(self, currency: str) -> Decimal:
        with self.connection() as connection:
            rows = connection.execute("SELECT amount FROM reservations WHERE currency=?", (currency,)).fetchall()
        return sum((Decimal(row["amount"]) for row in rows), Decimal(0))
