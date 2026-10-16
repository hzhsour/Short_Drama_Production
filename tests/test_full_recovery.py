"""Offline recovery checks; fixture media is generated locally, never uploaded."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.io import file_hash, load_json, write_json
from short_drama.pipeline import run_pipeline
from short_drama.recovery import restore_run
from short_drama.state import StateStore


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg/FFprobe")
class FullRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        base = Path(cls.fixture.name)
        original = base / "original"
        cls.old_run = original / "run"
        assets = original / "assets"
        assets.mkdir(parents=True)
        script = load_json(ROOT / "examples/technical-demo/script.json")
        script.update(width=160, height=288)
        write_json(assets / "script.json", script)
        shutil.copy2(ROOT / "examples/technical-demo/characters.json", assets / "characters.json")
        run_pipeline(assets / "script.json", assets / "characters.json", cls.old_run,
                     asset_root=assets, project_workspace=original / "engine", storage_root=original / "video")
        # A metadata-only output fixture exercises completed-output path/hash
        # migration. Actual MP4 rendering and reuse is checked by verify_recovery.
        candidate = cls.old_run / "EP900-v001.mp4"
        candidate.write_bytes(b"metadata-only-output-fixture-not-a-playable-video")
        intermediate = cls.old_run / "remotion/EP900-v001.mp4"
        intermediate.parent.mkdir()
        intermediate.write_bytes(b"metadata-only-intermediate-fixture")
        record = load_json(cls.old_run / "run.json")
        record["status"] = "completed"
        record["output"] = str(candidate)
        record["tasks"]["render"] = {"status": "succeeded", "path": str(candidate),
                                      "sha256": file_hash(candidate),
                                      "timeline_sha256": file_hash(cls.old_run / "timeline.json")}
        record["tasks"]["postproduction"] = {"status": "succeeded", "source": str(intermediate),
                                              "source_sha256": file_hash(intermediate), "output": str(candidate)}
        write_json(cls.old_run / "run.json", record)
        write_json(cls.old_run / "quality.json", {"passed": True, "probe": {"path": str(candidate), "sha256": file_hash(candidate)}})
        cls.snapshot = base / "snapshot"
        shutil.copytree(original, cls.snapshot)
        # Explicit consistent backup API replaces the copied DB; no worker runs
        # during this fixture operation. Production needs the same consistency.
        source = sqlite3.connect(original / "engine/state/video-jobs.sqlite3")
        destination = sqlite3.connect(cls.snapshot / "engine/state/video-jobs.sqlite3")
        source.backup(destination)
        source.close()
        destination.close()
        original.rename(base / "original-now-offline")
        cls.original_record = record

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.run = root / "restored-episode"
        self.engine = root / "restored-shared-ledger"
        self.video = root / "restored-video-store"
        self.assets = root / "restored-reference-media"
        for old, new in (("run", self.run), ("engine", self.engine), ("video", self.video), ("assets", self.assets)):
            shutil.copytree(self.snapshot / old, new)

    def tearDown(self):
        self.temporary.cleanup()

    def restore(self):
        return restore_run(self.run, self.engine, self.video, new_asset_root=self.assets)

    def test_full_metadata_rebinding_preserves_completed_outputs_and_task_identity(self):
        before = load_json(self.run / "video-result.json")
        identity = {job["job_key"]: (job["provider_job_id"], job["attempts"], job["artifact"]["sha256"]) for job in before["jobs"]}
        self.assertFalse(self.old_run.exists())
        with patch("short_drama.providers.mock.MockAdapter.submit", side_effect=AssertionError("restore must never submit")), \
             patch("short_drama.providers.mock.MockAdapter.poll", side_effect=AssertionError("restore must never poll")), \
             patch("short_drama.providers.mock.MockAdapter.download", side_effect=AssertionError("restore must never download")):
            result = self.restore()
        self.assertFalse(result["network_called"])
        self.assertFalse(result["backup_created"])
        self.assertGreater(result["verified_files"], 5)
        record = load_json(self.run / "run.json")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["execution_context"]["ledger_id"], self.original_record["execution_context"]["ledger_id"])
        self.assertEqual(record["execution_context"]["engine_workspace"], str(self.engine))
        self.assertEqual(file_hash(Path(record["output"])), record["tasks"]["render"]["sha256"])
        self.assertEqual(record["tasks"]["render"]["timeline_sha256"], file_hash(self.run / "timeline.json"))
        self.assertEqual(record["tasks"]["timeline"]["sha256"], file_hash(self.run / "timeline.json"))
        self.assertEqual(record["tasks"]["audio"]["manifest_sha256"], file_hash(self.run / "audio-result.json"))
        for path, digest in record["tasks"]["audio"]["checksums"].items():
            self.assertTrue(Path(path).is_relative_to(self.run))
            self.assertEqual(file_hash(Path(path)), digest)
        for job in load_json(self.run / "video-result.json")["jobs"]:
            self.assertEqual(identity[job["job_key"]], (job["provider_job_id"], job["attempts"], job["artifact"]["sha256"]))
            self.assertTrue(Path(job["artifact"]["path"]).is_relative_to(self.video))
        for name in ("audio-result.json", "timeline.json", "quality.json", "audio-v001/audio-manifest.json"):
            self.assertNotIn(str(self.old_run), (self.run / name).read_text())
        self.assertIn(str(self.old_run), (self.run / "events.jsonl").read_text())  # immutable history

    def test_audio_corruption_is_rejected_before_any_ledger_rebind(self):
        audio = load_json(self.run / "audio-result.json")
        track = self.run / Path(audio["tracks"][0]["path"]).relative_to(self.old_run)
        track.write_bytes(b"corrupt restored audio")
        before = (self.run / "run.json").read_bytes()
        with patch("short_drama.recovery.VideoEngine.rebind_storage") as rebind:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                self.restore()
            rebind.assert_not_called()
        self.assertEqual(before, (self.run / "run.json").read_bytes())

    def test_missing_original_uuid_is_rejected_without_creating_replacement(self):
        database = self.engine / "state/video-jobs.sqlite3"
        database.unlink()
        with self.assertRaisesRegex(ValueError, "UUID"):
            self.restore()
        self.assertFalse(database.exists())

    def test_mismatched_task_id_is_rejected_even_with_correct_ledger_uuid(self):
        state = StateStore(self.engine / "state/video-jobs.sqlite3")
        job = state.list_jobs()[0]
        job["provider_job_id"] = "wrong-task-id"
        state.save(job)
        with patch("short_drama.recovery.VideoEngine.rebind_storage") as rebind:
            with self.assertRaisesRegex(ValueError, "任务身份"):
                self.restore()
            rebind.assert_not_called()

    def test_changed_final_timeline_is_not_marked_reusable(self):
        timeline = load_json(self.run / "timeline.json")
        timeline["title"] += " tampered"
        write_json(self.run / "timeline.json", timeline)
        with self.assertRaisesRegex(ValueError, "SHA-256|时间线"):
            self.restore()

    def test_missing_final_subtitles_is_rejected(self):
        (self.run / "subtitles.srt").unlink()
        with self.assertRaisesRegex(ValueError, "SRT"):
            self.restore()

    def test_interrupted_metadata_migration_resumes_same_offline_plan(self):
        from short_drama import recovery
        atomic_write = recovery.write_json

        def interrupt(path, value):
            if Path(path).name == "timeline.json":
                raise OSError("simulated interrupted metadata write")
            atomic_write(path, value)

        with patch("short_drama.recovery.write_json", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.restore()
        self.assertEqual(load_json(self.run / ".restore-plan.json")["status"], "validated")
        # Some JSON and the ledger already contain new paths; old run.json still
        # names unavailable roots. The saved validated plan reconciles both.
        result = self.restore()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(load_json(self.run / ".restore-plan.json")["status"], "completed")
        record = load_json(self.run / "run.json")
        self.assertEqual(record["tasks"]["audio"]["manifest_sha256"], file_hash(self.run / "audio-result.json"))
        self.assertEqual(record["tasks"]["render"]["timeline_sha256"], file_hash(self.run / "timeline.json"))
