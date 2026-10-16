from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from short_drama.media import normalize_media, probe_media, qc_video, validate_timeline_media
from short_drama.timeline import build_timeline


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要本地 FFmpeg 和 FFprobe")
class LocalMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def create_source(self, name="source.mp4", *, audio=True, codec="libx264"):
        path = self.root / name
        command = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "testsrc2=size=96x160:rate=24:duration=0.5"]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050:duration=0.5"]
        command += ["-c:v", codec, "-pix_fmt", "yuv420p"]
        if codec == "libx265":
            command += ["-x265-params", "pools=1:frame-threads=1:log-level=error"]
        if audio:
            command += ["-c:a", "aac", "-shortest"]
        command += [str(path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def test_probe_normalize_sample_rate_fps_and_full_decode(self):
        source = self.create_source()
        original_hash = probe_media(source)["sha256"]
        target = self.root / "normalized.mp4"
        result = normalize_media(source, target, width=1080, height=1920, fps=30)
        streams = {stream["codec_type"]: stream for stream in result["streams"]}
        self.assertEqual(streams["audio"]["sample_rate"], "48000")
        self.assertEqual(streams["video"]["avg_frame_rate"], "30/1")
        self.assertEqual(probe_media(source)["sha256"], original_hash)
        storyboard = {"episode_id": "EP001", "fps": 30, "shots": [{"shot_id": "EP001-SC01-SH001", "duration_frames": 15}]}
        timeline = build_timeline(storyboard, {"jobs": [{"shot_id": "EP001-SC01-SH001", "status": "succeeded", "artifact": {"path": str(target)}}]}, {"tracks": [], "subtitles": []}, intro_frames=0, outro_frames=0)
        quality = qc_video(target, timeline)
        self.assertTrue(quality["passed"], quality["errors"])
        self.assertTrue(quality["manual_checks"])
        with self.assertRaises(FileExistsError):
            normalize_media(source, target)
        with self.assertRaises(FileExistsError):
            normalize_media(source, source)

    def test_h265_silent_source_gets_h264_and_audio(self):
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
        if "libx265" not in encoders:
            self.skipTest("本地构建没有 libx265 编码器")
        source = self.create_source(audio=False, codec="libx265")
        self.assertEqual(probe_media(source)["streams"][0]["codec_name"], "hevc")
        target = self.root / "h264.mp4"
        result = normalize_media(source, target, width=180, height=320)
        streams = {stream["codec_type"]: stream for stream in result["streams"]}
        self.assertEqual(streams["video"]["codec_name"], "h264")
        self.assertEqual(streams["audio"]["codec_name"], "aac")

    def test_qc_reports_wrong_specs_and_missing_audio(self):
        source = self.create_source(audio=False)
        quality = qc_video(source)
        self.assertFalse(quality["passed"])
        self.assertTrue(any("分辨率" in error for error in quality["errors"]))
        self.assertIn("输出缺少音轨", quality["errors"])

    def test_corrupt_or_remote_media_is_rejected(self):
        source = self.root / "broken.mp4"
        source.write_bytes(b"not a video")
        self.assertFalse(qc_video(source)["passed"])
        with self.assertRaisesRegex(ValueError, "本地"):
            probe_media("https://example.test/video.mp4")

    def test_source_guard_rejects_media_shorter_than_requested_shot(self):
        source = self.create_source(audio=False)
        storyboard = {"episode_id": "EP001", "fps": 30, "shots": [{"shot_id": "EP001-SC01-SH001", "duration_frames": 30}]}
        timeline = build_timeline(storyboard, {"jobs": [{"shot_id": "EP001-SC01-SH001", "status": "succeeded", "artifact": {"path": str(source)}}]}, {"tracks": [], "subtitles": []})
        self.assertTrue(any("时长不足" in error for error in validate_timeline_media(timeline)))
        with self.assertRaisesRegex(ValueError, "本地"):
            normalize_media(source, "https://example.test/output.mp4")

    @unittest.skipUnless(shutil.which("node"), "需要 Node.js")
    def test_render_helper_never_replaces_existing_output(self):
        manifest = self.root / "timeline.json"
        manifest.write_text("{}", encoding="utf-8")
        output = self.root / "existing.mp4"
        output.write_bytes(b"preserve original")
        helper = Path(__file__).resolve().parents[1] / "tools" / "render_episode.mjs"
        result = subprocess.run(["node", str(helper), str(manifest), str(output)], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("禁止静默覆盖", result.stderr)
        self.assertEqual(output.read_bytes(), b"preserve original")


if __name__ == "__main__":
    unittest.main()
