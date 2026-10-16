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
                CREATE TABLE IF NOT EXISTS cost_observations (
                    job_key TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    calculated_amount TEXT,
                    exceeds_estimate INTEGER NOT NULL DEFAULT 0,
                    requires_review INTEGER NOT NULL DEFAULT 0
                );
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(cost_observations)")}
            if "requires_review" not in columns:
                connection.execute("ALTER TABLE cost_observations ADD COLUMN requires_review INTEGER NOT NULL DEFAULT 0")
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
            rows = connection.execute("SELECT episode_id,currency,amount FROM reservations").fetchall()
            if any(row["currency"] != currency for row in rows):
                raise StateError("mixed currencies require a separate project budget ledger")
            observations = connection.execute("SELECT * FROM cost_observations").fetchall()
            if any(row["currency"] != currency for row in observations):
                raise StateError("mixed currencies require a separate project budget ledger")
            if any(row["exceeds_estimate"] for row in observations):
                raise StateError("provider-calculated cost exceeded estimate; final billing review required before new paid tasks")
            if any(row["requires_review"] for row in observations):
                raise StateError("provider usage/output pricing requires manual review before new paid tasks")
            costs = {row["job_key"]: Decimal(row["calculated_amount"]) for row in observations if row["calculated_amount"] is not None}
            detailed = connection.execute("SELECT job_key,episode_id,amount FROM reservations").fetchall()
            exposures = [(row["episode_id"], max(Decimal(row["amount"]), costs.get(row["job_key"], Decimal(0)))) for row in detailed]
            if any(value > task_limit for _, value in exposures):
                raise StateError("existing provider-calculated cost exceeds per-task budget; billing review required")
            project = sum((value for _, value in exposures), Decimal(0))
            episode = sum((value for name, value in exposures if name == episode_id), Decimal(0))
            if project >= project_limit or episode >= episode_limit:
                raise StateError("budget limit reached; no new paid task may be submitted")
            if existing:
                return
            if amount > task_limit or episode + amount > episode_limit or project + amount > project_limit:
                raise StateError("budget limit exceeded")
            connection.execute("INSERT INTO reservations VALUES(?,?,?,?)", (job_key, episode_id, currency, str(amount)))

    def observe_cost(self, job: dict[str, Any]) -> None:
        """Persist provider-derived accounting and the job checkpoint atomically.

        Observations never release a reservation or confirm a final invoice.
        A later missing/smaller response cannot erase an observed exposure.
        """
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT * FROM cost_observations WHERE job_key=?", (job["job_key"],)).fetchone()
            calculated = job.get("calculated_cost")
            if previous and previous["calculated_amount"] is not None:
                calculated = str(max(Decimal(previous["calculated_amount"]), Decimal(calculated or 0)))
            exceeds = calculated is not None and Decimal(calculated) > Decimal(job["estimated_cost"])
            exceeds = bool(exceeds or (previous and previous["exceeds_estimate"]))
            connection.execute(
                "INSERT OR REPLACE INTO cost_observations VALUES(?,?,?,?,?,?)",
                (job["job_key"], job["episode_id"], job["currency"], calculated, int(exceeds),
                 int(bool(job.get("accounting_requires_review") or (previous and previous["requires_review"])))),
            )
            job["calculated_cost"] = calculated
            job["cost_exceeds_estimate"] = exceeds
            job["updated_at"] = time.time()
            connection.execute("UPDATE jobs SET payload=? WHERE job_key=?", (json.dumps(job, ensure_ascii=False), job["job_key"]))

    def financial_summary(self, currency: str) -> dict[str, Any]:
        with self.connection() as connection:
            reservations = connection.execute("SELECT job_key,amount FROM reservations WHERE currency=?", (currency,)).fetchall()
            observations = connection.execute("SELECT * FROM cost_observations WHERE currency=?", (currency,)).fetchall()
        known = {row["job_key"]: Decimal(row["calculated_amount"]) for row in observations if row["calculated_amount"] is not None}
        return {
            "reserved_budget": str(sum((Decimal(row["amount"]) for row in reservations), Decimal(0))),
            "provider_calculated_cost_known_total": str(sum(known.values(), Decimal(0))) if known else None,
            "provider_calculated_cost_known_tasks": len(known),
            "conservative_budget_exposure": str(sum((max(Decimal(row["amount"]), known.get(row["job_key"], Decimal(0))) for row in reservations), Decimal(0))),
            "new_paid_tasks_blocked_by_cost_review": any(row["exceeds_estimate"] or row["requires_review"] for row in observations),
            "billing_reconciliation_status": "not_reconciled_with_final_invoice",
            "notice": "Reservations and provider-derived calculations are not actual debits or guaranteed price caps.",
        }

    def reserved_total(self, currency: str) -> Decimal:
        with self.connection() as connection:
            rows = connection.execute("SELECT amount FROM reservations WHERE currency=?", (currency,)).fetchall()
        return sum((Decimal(row["amount"]) for row in rows), Decimal(0))
