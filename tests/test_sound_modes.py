"""Audio mode acceptance uses locally synthesized FFmpeg fixtures, never APIs."""

from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.audio import build_audio
from short_drama.media import validate_timeline_media
from short_drama.script import script_to_storyboard, validate_script
from short_drama.timeline import build_timeline, validate_timeline
from test_audio import audio_board, audio_characters
from test_script import valid_script


def make_sound_fixture(root: Path, *, frequency: int = 440, with_audio: bool = True) -> Path:
    """One second of 160x284 color and optional 48kHz AAC sine wave."""
    path = root / (f"source-{frequency}.mp4" if with_audio else "source-silent.mp4")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "color=c=0x264060:s=160x284:r=30:d=1"]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=1"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-ar", "48000", "-shortest"]
    command += [str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    return path


class SoundModeContractTests(unittest.TestCase):
    def test_script_conversion_preserves_explicit_mode_and_rejects_invalid(self):
        for mode in ("model", "dub", "silent"):
            script = valid_script()
            script["sound_mode"] = mode
            self.assertEqual(script_to_storyboard(script)["sound_mode"], mode)
        script["sound_mode"] = "unknown"
        self.assertTrue(any("sound_mode" in error for error in validate_script(script)))

    def test_model_and_silent_keep_captions_without_audio_or_tts(self):
        class ForbiddenTTS:
            is_local = True

            def synthesize(self, *args):
                raise AssertionError("model/silent must never synthesize speech")

        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("model", "silent"):
                board = audio_board()
                board["sound_mode"] = mode
                # Missing files and a forbidden TTS adapter are intentionally
                # configured: mode selection must bypass all external tracks.
                board["shots"][0]["dialogue"][0]["audio_path"] = "missing.wav"
                output = Path(temporary) / mode
                result = build_audio(board, audio_characters(), output, mode="local", tts_adapter=ForbiddenTTS())
                self.assertEqual(result["sound_mode"], mode)
                self.assertEqual(result["tracks"], [])
                self.assertEqual(len(result["subtitles"]), 2)
                self.assertIn("灯还亮着", Path(result["srt_path"]).read_text(encoding="utf-8"))
                self.assertEqual(list(output.glob("*.wav")), [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "音轨验收需要 FFmpeg/FFprobe")
class SoundModeMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = make_sound_fixture(self.root)
        self.board = audio_board()
        self.board["shots"] = self.board["shots"][:1]
        self.board.update(width=160, height=284)

    def inputs(self, mode="model"):
        board = {**self.board, "sound_mode": mode}
        audio = build_audio(board, audio_characters(), self.root / f"audio-{mode}")
        video = {"episode_id": board["episode_id"], "mode": "mock", "sound_mode": mode, "jobs": [{
            "shot_id": board["shots"][0]["shot_id"], "status": "succeeded", "artifact": {
                "path": str(self.source), "sound_mode": mode, "has_source_audio": True,
            },
        }]}
        return board, video, audio

    def test_locally_generated_aac_video_has_verified_consistent_modes(self):
        for mode in ("model", "dub", "silent"):
            board, video, audio = self.inputs(mode)
            manifest = build_timeline(board, video, audio, intro_frames=0, outro_frames=0, transition_frames=0)
            media = manifest["shots"][0]["media"]
            self.assertIs(media["has_source_audio"], True)
            self.assertEqual(media["sound_mode"], mode)
            self.assertEqual(manifest["sound_mode"], mode)
            self.assertEqual(bool(manifest["tracks"]), mode == "dub")
            self.assertEqual(validate_timeline(manifest), [])

    def test_model_refuses_no_audio_and_false_metadata(self):
        board, video, audio = self.inputs()
        video["jobs"][0]["artifact"] = {"path": str(make_sound_fixture(self.root, with_audio=False)), "sound_mode": "model", "has_source_audio": False}
        with self.assertRaisesRegex(ValueError, "实际含音轨"):
            build_timeline(board, video, audio)
        video["jobs"][0]["artifact"] = {"path": str(self.source), "sound_mode": "model", "has_source_audio": False}
        with self.assertRaisesRegex(ValueError, "实测不一致"):
            build_timeline(board, video, audio)

    def test_non_mock_needs_mode_and_artifact_metadata(self):
        board, video, audio = self.inputs("dub")
        video["mode"] = "live"
        del board["sound_mode"]
        with self.assertRaisesRegex(ValueError, "必须显式声明"):
            build_timeline(board, video, audio)
        board["sound_mode"] = "dub"
        del video["jobs"][0]["artifact"]["sound_mode"]
        with self.assertRaisesRegex(ValueError, "缺少 sound_mode"):
            build_timeline(board, video, audio)
        video["mode"] = "mock"
        manifest = build_timeline(board, video, audio)
        self.assertTrue(any("旧 Mock" in line for line in manifest["quality"]["warnings"]))

    def test_conflicts_and_duplicate_audio_are_rejected(self):
        board, video, audio = self.inputs()
        mismatched = deepcopy(audio)
        mismatched["sound_mode"] = "dub"
        with self.assertRaisesRegex(ValueError, "音频结果 sound_mode"):
            build_timeline(board, video, mismatched)
        mismatched = deepcopy(video)
        mismatched["jobs"][0]["artifact"]["sound_mode"] = "silent"
        with self.assertRaisesRegex(ValueError, "素材 sound_mode"):
            build_timeline(board, mismatched, audio)
        _, _, dubbed = self.inputs("dub")
        audio["tracks"] = dubbed["tracks"]
        with self.assertRaisesRegex(ValueError, "禁止外部音轨"):
            build_timeline(board, video, audio)

    def test_manifest_validation_prevents_mode_edits_and_duplicate_tracks(self):
        board, video, audio = self.inputs()
        manifest = build_timeline(board, video, audio)
        manifest["shots"][0]["media"]["sound_mode"] = "dub"
        self.assertTrue(any("sound_mode" in error for error in validate_timeline(manifest)))
        manifest["shots"][0]["media"]["sound_mode"] = "model"
        manifest["tracks"] = [{"id": "duplicate", "start_frame": 0, "duration_frames": 1}]
        self.assertTrue(any("禁止外部音轨" in error for error in validate_timeline(manifest)))

    def test_render_preflight_rechecks_actual_audio_streams(self):
        board, video, audio = self.inputs()
        manifest = build_timeline(board, video, audio, intro_frames=0, outro_frames=0)
        self.assertEqual(validate_timeline_media(manifest), [])
        # Forged JSON with the correct video hash must still fail if its
        # claimed model sound is absent from the actual file.
        import hashlib
        silent = make_sound_fixture(self.root, with_audio=False)
        media = manifest["shots"][0]["media"]
        media.update(path=str(silent), sha256=hashlib.sha256(silent.read_bytes()).hexdigest())
        errors = validate_timeline_media(manifest)
        self.assertTrue(any("has_source_audio 不一致" in error for error in errors))
        self.assertTrue(any("实际没有音轨" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
