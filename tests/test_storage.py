from __future__ import annotations

import tempfile
import shutil
import unittest
from decimal import Decimal
from pathlib import Path

from short_drama.state import StateError, StateStore
from short_drama.storage import LocalStorage, StorageError


class StorageTests(unittest.TestCase):
    def test_backup_can_be_explicitly_rebound_by_key_after_mount_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"persistent media")
            original = LocalStorage(root / "old-cloud-mount")
            artifact = original.put(source, "EP001/shot.mp4")
            shutil.copytree(original.root, root / "new-cloud-mount")
            restored = LocalStorage(root / "new-cloud-mount")
            self.assertFalse(restored.verify(artifact))
            rebound = restored.rebind(artifact)
            self.assertTrue(restored.verify(rebound))
            self.assertEqual(rebound["sha256"], artifact["sha256"])
            Path(rebound["path"]).write_bytes(b"damaged backup")
            with self.assertRaises(StorageError):
                restored.rebind(artifact)
    def test_immutable_storage_detects_tampering_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"original media")
            storage = LocalStorage(root / "persistent")
            artifact = storage.put(source, "EP001/shot.mp4")
            self.assertTrue(storage.verify(artifact))
            self.assertEqual(storage.put(source, "EP001/shot.mp4"), artifact)
            source.write_bytes(b"different media")
            with self.assertRaises(StorageError):
                storage.put(source, "EP001/shot.mp4")
            self.assertEqual(Path(artifact["path"]).read_bytes(), b"original media")
            Path(artifact["path"]).write_bytes(b"corrupt")
            self.assertFalse(storage.verify(artifact))

    def test_traversal_and_symlink_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = LocalStorage(root / "objects")
            (storage.root / "escape").symlink_to(root, target_is_directory=True)
            for key in ("../private", "/absolute", "a\\b", "escape/private"):
                with self.subTest(key=key), self.assertRaises(StorageError):
                    storage.path_for(key)

    def test_reservations_are_atomic_decimal_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite3"
            state = StateStore(path)
            state.reserve("job1", "EP001", "CNY", Decimal("0.1"), Decimal("1"), Decimal("1"), Decimal("0.3"))
            restarted = StateStore(path)
            restarted.reserve("job1", "EP001", "CNY", Decimal("0.1"), Decimal("1"), Decimal("1"), Decimal("0.3"))
            restarted.reserve("job2", "EP002", "CNY", Decimal("0.2"), Decimal("1"), Decimal("1"), Decimal("0.3"))
            self.assertEqual(restarted.reserved_total("CNY"), Decimal("0.3"))
            with self.assertRaises(StateError):
                restarted.reserve("job3", "EP003", "CNY", Decimal("0.000001"), Decimal("1"), Decimal("1"), Decimal("0.3"))
            with self.assertRaises(StateError):
                restarted.reserve("job1", "EP001", "CNY", Decimal("0.11"), Decimal("1"), Decimal("1"), Decimal("1"))

    def test_job_claim_blocks_concurrent_owners_and_expired_leases_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "jobs.sqlite3")
            state.ensure({"job_key": "j", "episode_id": "EP001", "shot_id": "s", "status": "pending"})
            self.assertTrue(state.claim("j", "worker1"))
            self.assertFalse(state.claim("j", "worker2"))
            state.release("j", "worker2")
            self.assertFalse(state.claim("j", "worker2"))
            state.release("j", "worker1")
            self.assertTrue(state.claim("j", "worker2", lease_seconds=-1))
            self.assertTrue(state.claim("j", "worker3"))
