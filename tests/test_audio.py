from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.audio import PiperLocalTTSAdapter, build_audio, frames_to_srt_time, inspect_audio, subtitles_to_srt
from test_validation import valid_shot
from test_continuity import valid_characters


def audio_board():
    first = valid_shot()
    first["duration_frames"] = 30
    first["dialogue"] = [{"character_id": "CHAR-001", "text": "灯还亮着。", "start_frame": 3, "duration_frames": 24}]
    first["audio"] = [{"kind": "bgm", "start_frame": 0, "duration_frames": 30, "volume": .15}]
    second = valid_shot("EP001-SC01-SH002")
    second["duration_frames"] = 30
    second["characters"] = ["CHAR-002"]
    second["dialogue"] = [{"character_id": "CHAR-002", "text": "我一直在等你。", "start_frame": 0, "duration_frames": 30}]
    second["audio"] = []
    return {"episode_id": "EP001", "fps": 30, "aspect_ratio": "9:16", "shots": [first, second]}


def audio_characters():
    data = valid_characters()
    second = deepcopy(data["characters"][0])
    second.update(character_id="CHAR-002", name="陈默")
    second["voice"].update(profile_id="chen-test", pitch_hz=140)
    data["characters"].append(second)
    return data


class AudioTests(unittest.TestCase):
    def test_mock_tracks_voice_profiles_srt_duration_and_loudness(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_audio(audio_board(), audio_characters(), Path(tmp))
            self.assertEqual(result["mode"], "mock")
            self.assertIn("不是真人配音", result["notice"])
            voices = [track for track in result["tracks"] if track["kind"] == "dialogue"]
            self.assertEqual([track["voice_profile_id"] for track in voices], ["lin-test", "chen-test"])
            self.assertEqual(voices[0]["start_frame"], 3)
            srt = Path(result["srt_path"]).read_text()
            self.assertIn("00:00:00,100 --> 00:00:00,900", srt)
            self.assertIn("00:00:01,000 --> 00:00:02,000", srt)
            for track, quality in zip(result["tracks"], result["quality"]):
                self.assertEqual(quality["errors"], [])
                self.assertAlmostEqual(quality["duration_seconds"], track["duration_frames"] / 30, places=4)
                self.assertLess(quality["peak_dbfs"], -10)
                self.assertIsNotNone(quality["rms_dbfs"])
                if shutil.which("ffmpeg"):
                    self.assertIsNotNone(quality["integrated_lufs"])
            # Repeating the exact Mock job is safe and deterministic.
            self.assertEqual(result, build_audio(audio_board(), audio_characters(), Path(tmp)))

    def test_frame_time_rounding_and_long_duration(self):
        self.assertEqual(frames_to_srt_time(1, 30), "00:00:00,033")
        self.assertEqual(frames_to_srt_time(30 * 3661, 30), "01:01:01,000")
        with self.assertRaises(ValueError):
            frames_to_srt_time(True, 30)

    def test_subtitle_overlap_and_bounds_fail(self):
        base = {"shot_id": "EP001-SC01-SH001", "character_id": "CHAR-001", "text": "测试", "start_frame": 0, "end_frame": 20}
        for subtitles in ([base, {**base, "start_frame": 10, "end_frame": 30}], [{**base, "end_frame": 31}]):
            with self.assertRaises(ValueError):
                subtitles_to_srt(audio_board(), subtitles)

    def test_paid_or_missing_local_tts_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PermissionError):
                build_audio(audio_board(), audio_characters(), Path(tmp), mode="live")
            with self.assertRaisesRegex(RuntimeError, "离线中文 TTS"):
                build_audio(audio_board(), audio_characters(), Path(tmp), mode="local")

    def test_does_not_overwrite_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "EP001-SC01-SH001-dialogue-001.wav"
            target.write_bytes(b"private original")
            with self.assertRaises(FileExistsError):
                build_audio(audio_board(), audio_characters(), Path(tmp))
            self.assertEqual(target.read_bytes(), b"private original")

    def test_duration_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silence.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(bytes(24000 * 2))
            result = inspect_audio(path, expected_seconds=2)
            self.assertTrue(any("时长" in error for error in result["errors"]))
            self.assertTrue(any("静音" in warning for warning in result["warnings"]))

    @unittest.skipUnless(shutil.which("ffmpeg"), "本地音频处理需要 FFmpeg")
    def test_local_recording_pipeline_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "recording.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                # A pre-existing local recording stub; no TTS service is contacted.
                wav.writeframes((b"\x10\x00\xf0\xff") * 6000)
            original = source.read_bytes()
            board = audio_board()
            board["shots"] = board["shots"][:1]
            board["shots"][0]["dialogue"][0]["audio_path"] = "recording.wav"
            board["shots"][0]["audio"] = []
            result = build_audio(board, audio_characters(), root / "out", mode="local", asset_root=root)
            self.assertEqual(source.read_bytes(), original)
            self.assertAlmostEqual(result["quality"][0]["duration_seconds"], .8, places=3)
            self.assertEqual(result["mode"], "local")


class PiperInterfaceTests(unittest.TestCase):
    """A local fake CLI tests process wiring; these tests do not synthesize Chinese."""
    def configured(self, root):
        executable = root / "fake-piper"
        executable.write_text("""#!/usr/bin/env python3
import argparse,sys,wave
parser=argparse.ArgumentParser()
parser.add_argument('--model',required=True)
parser.add_argument('--output_file',required=True)
parser.add_argument('--speaker',type=int)
args=parser.parse_args()
text=sys.stdin.read()
if 'FAIL' in text:
    sys.stderr.write('controlled fake CLI failure')
    sys.exit(4)
if not text.strip():
    sys.exit(5)
with wave.open(args.output_file,'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(24000)
    wav.writeframes(bytes(24000))
""", encoding="utf-8")
        executable.chmod(0o700)
        model = root / "zh_CN-test.onnx"
        model.write_bytes(b"TEST STUB, NOT A REAL TTS MODEL")
        Path(str(model) + ".json").write_text('{"phoneme_type":"espeak","espeak":{"voice":"cmn"},"num_speakers":1}')
        return PiperLocalTTSAdapter({"lin-test": model}, executable=str(executable))

    def test_local_cli_stdin_output_and_pipeline_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.configured(root)
            path = adapter.synthesize("中文接口测试。", audio_characters()["characters"][0]["voice"], root / "direct.wav")
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getnframes(), 12000)
            if shutil.which("ffmpeg"):
                board = audio_board()
                board["shots"] = board["shots"][:1]
                board["shots"][0]["audio"] = []
                result = build_audio(board, audio_characters(), root / "pipeline", mode="local", tts_adapter=adapter)
                self.assertAlmostEqual(result["quality"][0]["duration_seconds"], .8, places=3)

    def test_missing_model_missing_cli_and_failed_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voice = audio_characters()["characters"][0]["voice"]
            with self.assertRaises(FileNotFoundError):
                PiperLocalTTSAdapter({"lin-test": root / "missing.onnx"}).synthesize("测试", voice, root / "x.wav")
            adapter = self.configured(root)
            adapter.executable = str(root / "missing-cli")
            with self.assertRaisesRegex(RuntimeError, "未安装"):
                adapter.synthesize("测试", voice, root / "x.wav")
            adapter = self.configured(root)
            with self.assertRaisesRegex(RuntimeError, "exit 4"):
                adapter.synthesize("FAIL", voice, root / "x.wav")
            self.assertFalse((root / "x.wav").exists())

    def test_refuses_to_overwrite_outputs_and_unknown_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.configured(root)
            voice = audio_characters()["characters"][0]["voice"]
            path = root / "private.wav"
            path.write_bytes(b"private")
            with self.assertRaises(FileExistsError):
                adapter.synthesize("测试", voice, path)
            self.assertEqual(path.read_bytes(), b"private")
            with self.assertRaisesRegex(ValueError, "profile"):
                adapter.synthesize("测试", {**voice, "profile_id": "missing"}, root / "x.wav")

    def test_g2pw_potential_download_is_blocked_and_speaker_mapping_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.configured(root)
            voice = audio_characters()["characters"][0]["voice"]
            config = root / "zh_CN-test.onnx.json"
            config.write_text('{"phoneme_type":"g2pW"}')
            with self.assertRaisesRegex(ValueError, "自动下载"):
                adapter.synthesize("测试", voice, root / "x.wav")
            self.assertFalse((root / "x.wav").exists())
            config.write_text('{"phoneme_type":"espeak","espeak":{"voice":"cmn"},"num_speakers":1}')
            adapter.speaker_ids = {"lin-test": 0}
            self.assertTrue(adapter.synthesize("测试", voice, root / "x.wav").is_file())
            adapter.speaker_ids = {"lin-test": 1}
            with self.assertRaisesRegex(ValueError, "num_speakers"):
                adapter.synthesize("测试", voice, root / "out-of-range.wav")
            self.assertFalse((root / "out-of-range.wav").exists())


if __name__ == "__main__":
    unittest.main()
