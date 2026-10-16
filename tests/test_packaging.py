from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.packaging import generate_packaging


class PackagingSafetyTests(unittest.TestCase):
    def test_rejects_existing_output_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "original.mp4"
            output.write_bytes(b"private original")
            with self.assertRaises(FileExistsError):
                generate_packaging(output, "标题")
            self.assertEqual(output.read_bytes(), b"private original")

    def test_rejects_remote_and_invalid_specs_before_render(self):
        for destination in ("https://example.com/title.mp4", "//server/share/title.mp4"):
            with self.assertRaises(ValueError):
                generate_packaging(destination, "标题")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "title.mp4"
            for options in ({"backend": "cloud"}, {"duration_seconds": float("nan")}, {"duration_seconds": True}, {"width": 321}, {"fps": 0}):
                with self.assertRaises(ValueError):
                    generate_packaging(target, "标题", **options)
            self.assertFalse(target.exists())

    def test_missing_hyperframes_dependencies_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "title.mp4"
            with self.assertRaisesRegex(RuntimeError, "缺少隔离 HyperFrames"):
                generate_packaging(target, "标题", backend="hyperframes", project_dir=temporary)
            self.assertFalse(target.exists())

    def test_missing_ffmpeg_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as temporary, patch("short_drama.packaging.shutil.which", return_value=None):
            output = Path(temporary) / "title.mp4"
            with self.assertRaisesRegex(RuntimeError, "缺少本地依赖"):
                generate_packaging(output, "标题")
            self.assertFalse(output.exists())

    def test_hyperframes_title_is_escaped_and_runner_only_checks_and_renders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, version in (("hyperframes", "0.8.164"), ("gsap", "3.14.2")):
                package = root / "node_modules" / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(json.dumps({"version": version}))
            (root / "node_modules/hyperframes/bin").mkdir()
            (root / "node_modules/hyperframes/bin/hyperframes.mjs").write_text("")
            (root / "node_modules/gsap/dist").mkdir()
            (root / "node_modules/gsap/dist/gsap.min.js").write_text("/* pinned fixture */")
            (root / "fixture.ttf").write_bytes(b"fake font for escaping-only test")
            captured = []

            def fake_run(args, **kwargs):
                captured.append(args)
                source = (Path(args[3]) / "index.html").read_text()
                self.assertNotIn("<script>bad()", source)
                self.assertIn("&lt;script&gt;bad()", source)
                self.assertEqual(kwargs["env"]["HYPERFRAMES_NO_UPDATE_CHECK"], "1")
                self.assertNotIn("ARK_API_KEY", kwargs["env"])
                return subprocess.CompletedProcess(args, 0, "", "")

            from short_drama.packaging import _render_hyperframes
            with patch("short_drama.packaging._run_local", side_effect=fake_run), patch("short_drama.packaging.shutil.which", return_value="/usr/bin/chromium"), patch("short_drama.packaging._cjk_font", return_value=root / "fixture.ttf"), patch.dict("os.environ", {"ARK_API_KEY": "must-not-reach-renderer"}):
                result = _render_hyperframes(root / "output.mp4", "<script>bad()</script> __WIDTH__", root, duration=1, width=320, height=568, fps=30)
            self.assertEqual([args[2] for args in captured], ["check", "render"])
            self.assertTrue(result["check_passed"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要本地 FFmpeg/ffprobe")
class PackagingMediaTests(unittest.TestCase):
    def test_real_local_title_is_h264_with_audio_and_traceable_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "title with spaces.mp4"
            result = generate_packaging(output, "中文测试 %{n} ' :", duration_seconds=0.7, width=320, height=568)
            self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result["backend"], "ffmpeg")
            self.assertFalse(result["main_timeline_control"])
            self.assertFalse(result["external_api_called"])
            videos = [stream for stream in result["streams"] if stream["codec_type"] == "video"]
            audios = [stream for stream in result["streams"] if stream["codec_type"] == "audio"]
            self.assertEqual((videos[0]["width"], videos[0]["height"], videos[0]["codec_name"]), (320, 568, "h264"))
            self.assertEqual(audios[0]["codec_name"], "aac")
            self.assertAlmostEqual(float(result["format"]["duration"]), 0.7, delta=0.05)


if __name__ == "__main__":
    unittest.main()
