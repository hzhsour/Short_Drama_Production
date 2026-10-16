import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.io import file_hash
from short_drama.pipeline import run_pipeline
from short_drama.state import StateStore
from short_drama.video_engine import VideoEngine


class PipelineRecoveryTests(unittest.TestCase):
    def test_changed_shared_ledger_is_rejected_before_any_new_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = (ROOT / "examples/technical-demo/script.json", ROOT / "examples/technical-demo/characters.json", root / "run")
            result = run_pipeline(*args, max_jobs=0)
            self.assertEqual(result["status"], "waiting_video")
            with patch("short_drama.pipeline.VideoEngine") as engine:
                with self.assertRaisesRegex(ValueError, "账本"):
                    run_pipeline(*args, project_workspace=root / "empty-different-ledger")
                engine.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg/FFprobe")
    def test_local_audio_source_change_invalidates_audio_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = json.loads((ROOT / "examples/technical-demo/script.json").read_text())
            script["scenes"][0]["shots"] = script["scenes"][0]["shots"][:1]
            shot = script["scenes"][0]["shots"][0]
            shot["duration_frames"] = 30
            shot["audio"] = []
            shot["dialogue"][0].update(start_frame=0, duration_frames=30, audio_path="recording.wav")
            script_path = root / "script.json"
            script_path.write_text(json.dumps(script), encoding="utf-8")
            characters = ROOT / "examples/technical-demo/characters.json"
            recording = root / "recording.wav"
            def record(frequency):
                with wave.open(str(recording), "wb") as handle:
                    handle.setparams((1, 2, 24000, 24000, "NONE", "not compressed"))
                    handle.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * frequency * frame / 24000))) for frame in range(24000)))
            record(220)
            run_pipeline(script_path, characters, root / "run", asset_root=root, audio_mode="local")
            before = json.loads((root / "run/audio-result.json").read_text())
            first = Path(before["tracks"][0]["path"])
            first_hash = file_hash(first)
            record(330)
            run_pipeline(script_path, characters, root / "run", asset_root=root, audio_mode="local")
            after = json.loads((root / "run/audio-result.json").read_text())
            second = Path(after["tracks"][0]["path"])
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_hash, file_hash(second))
            self.assertEqual(file_hash(first), first_hash)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg/FFprobe")
    def test_live_video_with_mock_audio_remains_explicit_technical_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script_path = ROOT / "examples/technical-demo/script.json"
            characters_path = ROOT / "examples/technical-demo/characters.json"
            from short_drama.script import script_to_storyboard
            board = script_to_storyboard(json.loads(script_path.read_text()), json.loads(characters_path.read_text()))
            # Pre-existing local clips stand in for a completed provider result.
            # The fake does not perform HTTP, submit an API job, or create approval.
            result = VideoEngine(root / "fixtures").run(board)
            result["mode"] = "live"
            approval = root / "approval.json"
            approval.write_text(json.dumps({"creative": {"approved": True, "script_sha256": file_hash(script_path), "characters_sha256": file_hash(characters_path)}}))
            with patch("short_drama.pipeline.VideoEngine") as engine:
                engine.return_value.state = StateStore(root / "shared/state/video-jobs.sqlite3")
                engine.return_value.plan.return_value = []
                engine.return_value.run.return_value = result
                record = run_pipeline(script_path, characters_path, root / "run", mode="live", provider="fake-provider", audio_mode="mock", approval_file=approval, project_workspace=root / "shared")
            timeline = json.loads((root / "run/timeline.json").read_text())
            self.assertTrue(record["technical_test"])
            self.assertTrue(record["mock_audio"])
            self.assertEqual(record["speech_status"], "test_tones_not_speech")
            self.assertTrue(timeline["technical_test"])
            self.assertIn("非真实配音", timeline["intro"]["subtitle"])
