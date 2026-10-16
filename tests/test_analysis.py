from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.analysis import analyze_video


class AnalysisBoundaryTests(unittest.TestCase):
    def test_remote_inputs_and_missing_files_are_rejected(self):
        for value in ("https://example.com/private.mp4", "//host/private.mp4", ROOT / "not-a-file.mp4"):
            with self.assertRaises(ValueError):
                analyze_video(value)

    def test_no_audio_is_explicit_and_external_provider_stays_disabled(self):
        fixture = {"path": "/tmp/example.mp4", "streams": [{"codec_type": "video"}], "format": {"duration": "1"}}
        with patch("short_drama.analysis.probe_media", return_value=fixture), patch("short_drama.analysis._ffmpeg_analysis") as renderer:
            result = analyze_video("/tmp/example.mp4", detect_silence=True)
        self.assertEqual(result["silence"]["status"], "unavailable_no_audio")
        self.assertFalse(result["capabilities"]["asr"])
        self.assertFalse(result["capabilities"]["semantic_shot_recognition"])
        self.assertFalse(result["optional_providers"]["video-use"]["enabled"])
        renderer.assert_not_called()

    def test_analysis_timeout_is_reported(self):
        fixture = {"path": "/tmp/example.mp4", "streams": [{"codec_type": "video"}], "format": {"duration": "1"}}
        with patch("short_drama.analysis.probe_media", return_value=fixture), patch("short_drama.analysis.shutil.which", return_value="ffmpeg"), patch("short_drama.analysis.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 180)):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                analyze_video("/tmp/example.mp4", detect_scenes=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要本地 FFmpeg/ffprobe")
class AnalysisMediaTests(unittest.TestCase):
    def test_real_signal_analysis_finds_silence_and_a_hard_cut_without_editing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "signals.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-n",
                "-f", "lavfi", "-i", "color=c=black:s=160x240:r=30:d=1",
                "-f", "lavfi", "-i", "color=c=white:s=160x240:r=30:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]volume=0:enable='lt(t,0.5)+gt(t,1.5)'[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output),
            ], capture_output=True, text=True, timeout=30, check=True)
            before = hashlib.sha256(output.read_bytes()).hexdigest()
            result = analyze_video(output, detect_silence=True, detect_scenes=True)
            self.assertEqual(before, hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result["silence"]["status"], "completed")
            self.assertTrue(any(segment["start_seconds"] < 0.05 and segment["end_seconds"] > 0.4 for segment in result["silence"]["segments"]))
            self.assertTrue(any(abs(cut - 1) < 0.05 for cut in result["scenes"]["cut_candidates_seconds"]))
            self.assertFalse(result["external_api_called"])


if __name__ == "__main__":
    unittest.main()
