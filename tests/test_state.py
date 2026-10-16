from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from short_drama.state import StateError, StateStore


class LedgerIdentityTests(unittest.TestCase):
    def test_identity_survives_restart_and_backup_but_not_empty_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state" / "jobs.sqlite3"
            original = StateStore(path)
            ledger_id = original.ledger_id
            self.assertEqual(str(UUID(ledger_id)), ledger_id)
            self.assertEqual(StateStore(path).ledger_id, ledger_id)
            backup = root / "restored elsewhere.sqlite3"
            shutil.copy2(path, backup)
            self.assertEqual(StateStore.read_ledger_id(backup), ledger_id)
            self.assertEqual(StateStore(backup).ledger_id, ledger_id)
            path.unlink()
            replacement = StateStore(path)
            self.assertNotEqual(replacement.ledger_id, ledger_id)

    def test_read_only_inspection_does_not_create_missing_or_empty_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing" / "jobs.sqlite3"
            self.assertIsNone(StateStore.read_ledger_id(missing))
            self.assertFalse(missing.parent.exists())
            empty = root / "empty.sqlite3"
            empty.touch()
            self.assertIsNone(StateStore.read_ledger_id(empty))
            self.assertEqual(empty.stat().st_size, 0)

    def test_legacy_ledger_is_unchanged_by_read_and_migrates_once_on_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE existing_data(value TEXT)")
                connection.execute("INSERT INTO existing_data VALUES('keep production history')")
            before = path.read_bytes()
            self.assertIsNone(StateStore.read_ledger_id(path))
            self.assertEqual(path.read_bytes(), before)
            migrated = StateStore(path)
            self.assertEqual(StateStore.read_ledger_id(path), migrated.ledger_id)
            self.assertEqual(StateStore(path).ledger_id, migrated.ledger_id)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT value FROM existing_data").fetchone()[0], "keep production history")

    def test_corrupt_or_invalid_identity_is_rejected_without_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite3"
            path.write_bytes(b"not a SQLite database")
            self.assertIsNone(StateStore.read_ledger_id(path))
            path.unlink()
            StateStore(path)
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE metadata SET value='tampered' WHERE key='ledger_uuid'")
            self.assertIsNone(StateStore.read_ledger_id(path))
            with self.assertRaises(StateError):
                StateStore(path)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='ledger_uuid'").fetchone()[0], "tampered")
