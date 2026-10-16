import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.cli import main
from short_drama.project import initialize_episode, initialize_series
from short_drama.pipeline import run_pipeline


class ProjectCommandsTests(unittest.TestCase):
    def test_init_and_episode_preserve_existing_creative_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            series = initialize_series(root, "rain-letter", title="雨夜来信", genre="都市悬疑")
            episode = initialize_episode(series, "EP001")
            script = episode / "script.md"
            script.write_text("已写好的剧本", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                initialize_episode(series, "EP001")
            with self.assertRaises(FileExistsError):
                initialize_series(root, "rain-letter", title="覆盖尝试")
            self.assertEqual(script.read_text(encoding="utf-8"), "已写好的剧本")

    def test_init_rejects_traversal_and_nonfinite_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            for slug, minutes in (("../escape", 2), ("safe", float("inf")), ("safe", float("nan"))):
                with self.assertRaises(ValueError):
                    initialize_series(Path(temporary), slug, title="测试", minutes=minutes)

    def test_cli_script_conversion_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            output = Path(temporary) / "storyboard.json"
            args = ["convert-script", str(ROOT / "examples/technical-demo/script.json"), "--characters", str(ROOT / "examples/technical-demo/characters.json"), "--output", str(output)]
            self.assertEqual(main(args), 0)
            before = output.read_bytes()
            self.assertEqual(len(json.loads(before)["shots"]), 2)
            self.assertEqual(main(args), 2)
            self.assertEqual(output.read_bytes(), before)

    def test_live_run_pauses_for_creative_review_without_submitting(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("short_drama.pipeline.VideoEngine") as engine:
                result = run_pipeline(ROOT / "examples/technical-demo/script.json", ROOT / "examples/technical-demo/characters.json", Path(temporary), mode="live", provider="volcengine-seedance-2.5")
                self.assertEqual(result["status"], "paused")
                self.assertEqual(result["tasks"]["creative_review"]["status"], "paused")
                engine.assert_not_called()

    def test_plan_result_cannot_replace_its_input_storyboard(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            from short_drama.script import script_to_storyboard
            root = Path(temporary)
            board = script_to_storyboard(json.loads((ROOT / "examples/technical-demo/script.json").read_text()), json.loads((ROOT / "examples/technical-demo/characters.json").read_text()))
            for command, name in (("plan", "video-plan.json"), ("generate", "video-result.json")):
                with self.subTest(command=command):
                    source = root / name
                    source.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
                    original = source.read_bytes()
                    with patch("short_drama.cli.VideoEngine") as engine:
                        self.assertEqual(main([command, str(source), "--run-dir", str(root)]), 2)
                        engine.assert_not_called()
                    self.assertEqual(source.read_bytes(), original)

    def test_two_workers_cannot_mutate_same_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            entered, release = threading.Event(), threading.Event()
            def work(*args, **kwargs):
                entered.set()
                release.wait(3)
                return {"status": "test"}
            with patch("short_drama.pipeline._run_pipeline", side_effect=work):
                thread = threading.Thread(target=run_pipeline, args=(Path("script"), Path("chars"), Path(temporary)))
                thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaisesRegex(RuntimeError, "worker"):
                        run_pipeline(Path("script"), Path("chars"), Path(temporary))
                finally:
                    release.set()
                    thread.join(3)
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
