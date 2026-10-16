from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from short_drama.timeline import build_timeline, timeline_srt, validate_timeline


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.video = root / "shot.mp4"
        self.video.write_bytes(b"local fixture, decode tested separately")
        self.image = root / "image.png"
        self.image.write_bytes(b"local image fixture")
        self.voice = root / "voice.wav"
        self.voice.write_bytes(b"local voice fixture")
        self.storyboard = {"episode_id": "EP001", "fps": 30, "shots": [
            {"shot_id": "EP001-SC01-SH001", "scene_id": "EP001-SC01", "duration_frames": 30, "dialogue": []},
            {"shot_id": "EP001-SC01-SH002", "scene_id": "EP001-SC01", "duration_frames": 60, "dialogue": []},
        ]}
        self.videos = {"episode_id": "EP001", "mode": "mock", "jobs": [
            {"shot_id": "EP001-SC01-SH001", "status": "succeeded", "artifact": {"path": str(self.video)}},
            {"shot_id": "EP001-SC01-SH002", "status": "succeeded", "artifact": {"path": str(self.image)}},
        ]}
        self.audio = {"episode_id": "EP001", "tracks": [{
            "id": "C1-voice", "shot_id": "EP001-SC01-SH002", "path": str(self.voice), "start_frame": 5,
            "duration_frames": 20, "volume": 0.8, "kind": "dialogue", "character_id": "CHAR-001",
        }], "subtitles": [{"shot_id": "EP001-SC01-SH002", "character_id": "CHAR-001", "text": "这是一段中文对白。", "start_frame": 5, "end_frame": 25}]}

    def test_mixed_media_and_audio_shift_with_intro(self):
        result = build_timeline(self.storyboard, self.videos, self.audio, intro_frames=10, outro_frames=15, title="测试")
        self.assertEqual(result["duration_frames"], 115)
        self.assertEqual([shot["start_frame"] for shot in result["shots"]], [10, 40])
        self.assertEqual([shot["media"]["kind"] for shot in result["shots"]], ["video", "image"])
        self.assertEqual(result["subtitles"][0]["start_frame"], 45)
        self.assertEqual(result["tracks"][0]["start_frame"], 45)
        self.assertEqual(result["outro"]["start_frame"], 100)
        self.assertIn("00:00:01,500 --> 00:00:02,167", timeline_srt(result))
        self.assertEqual(validate_timeline(result), [])
        self.assertEqual(result["shots"][0]["media"]["sha256"], hashlib.sha256(self.video.read_bytes()).hexdigest())

    def test_failed_or_duplicate_jobs_cannot_be_rendered(self):
        self.videos["jobs"][0]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "尚未完成"):
            build_timeline(self.storyboard, self.videos, self.audio)
        self.videos["jobs"].append(self.videos["jobs"][0])
        with self.assertRaisesRegex(ValueError, "重复"):
            build_timeline(self.storyboard, self.videos, self.audio)

    def test_rejects_network_media_and_hash_mismatch(self):
        self.videos["jobs"][0]["artifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "哈希"):
            build_timeline(self.storyboard, self.videos, self.audio)
        self.videos["jobs"][0]["artifact"] = {"path": "https://example.test/shot.mp4"}
        with self.assertRaisesRegex(ValueError, "本地"):
            build_timeline(self.storyboard, self.videos, self.audio)

    def test_rejects_audio_and_subtitle_overflow_without_clipping(self):
        self.audio["tracks"][0]["duration_frames"] = 90
        with self.assertRaisesRegex(ValueError, "音轨超出"):
            build_timeline(self.storyboard, self.videos, self.audio)
        self.audio["tracks"] = []
        self.audio["subtitles"][0]["end_frame"] = 61
        with self.assertRaisesRegex(ValueError, "字幕超出"):
            build_timeline(self.storyboard, self.videos, self.audio)

    def test_structural_qc_catches_gap_and_safe_area(self):
        result = build_timeline(self.storyboard, self.videos, self.audio)
        broken = deepcopy(result)
        broken["shots"][1]["start_frame"] += 1
        broken["safe_area"]["x"] = -1
        broken["subtitles"][0]["shot_id"] = "unknown"
        errors = validate_timeline(broken)
        self.assertTrue(any("缺口" in error for error in errors))
        self.assertTrue(any("安全范围" in error for error in errors))
        self.assertTrue(any("追溯" in error for error in errors))

    def test_dialogue_duration_form_and_no_input_mutation(self):
        self.storyboard["shots"][0]["dialogue"] = [{"character_id": "CHAR-001", "text": "你好", "start_frame": 2, "duration_frames": 8}]
        original = deepcopy(self.storyboard)
        result = build_timeline(self.storyboard, self.videos, {"tracks": []}, intro_frames=4, outro_frames=0)
        self.assertEqual(result["subtitles"][0]["end_frame"], 14)
        self.assertEqual(self.storyboard, original)

    def test_rejects_invalid_dimensions_and_episode(self):
        self.storyboard["width"] = 1081
        with self.assertRaisesRegex(ValueError, "偶数"):
            build_timeline(self.storyboard, self.videos, self.audio)
        self.storyboard["width"] = 1080
        self.audio["episode_id"] = "EP002"
        with self.assertRaisesRegex(ValueError, "episode_id"):
            build_timeline(self.storyboard, self.videos, self.audio)

    def test_very_short_shots_keep_a_visible_frame(self):
        self.storyboard["shots"][0]["duration_frames"] = 2
        result = build_timeline(self.storyboard, self.videos, self.audio)
        self.assertEqual(result["shots"][0]["transition"]["duration_frames"], 0)


if __name__ == "__main__":
    unittest.main()
