from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.script import script_to_storyboard, validate_script
from test_validation import valid_shot
from test_continuity import valid_characters


def valid_script():
    shot = valid_shot()
    del shot["scene_id"]
    del shot["location"]
    shot["dialogue"] = [{"character_id": "CHAR-001", "text": "灯还亮着。", "start_frame": 0, "duration_frames": 30}]
    return {"episode_id": "EP001", "aspect_ratio": "9:16", "fps": 30, "title": "技术测试",
            "technical_test": True, "scenes": [{"scene_id": "EP001-SC01", "location": "LOC-001", "shots": [shot]}]}


class ScriptTests(unittest.TestCase):
    def test_deterministic_conversion_preserves_dialogue_timing_and_source(self):
        source = valid_script()
        original = deepcopy(source)
        board = script_to_storyboard(source, valid_characters())
        self.assertEqual(source, original)
        self.assertEqual(board, script_to_storyboard(source, valid_characters()))
        self.assertEqual(board["shots"][0]["scene_id"], "EP001-SC01")
        self.assertEqual(board["shots"][0]["location"], "LOC-001")
        self.assertEqual(board["shots"][0]["dialogue"][0]["duration_frames"], 30)
        self.assertTrue(board["technical_test"])

    def test_free_text_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(ValueError, "自由文本"):
            script_to_storyboard("写一部都市悬疑短剧")

    def test_invalid_scene_duplicate_ids_and_missing_timing_rejected(self):
        script = valid_script()
        script["scenes"].append(deepcopy(script["scenes"][0]))
        self.assertTrue(any("场景 ID 重复" in error for error in validate_script(script)))
        script = valid_script()
        del script["scenes"][0]["shots"][0]["dialogue"][0]["duration_frames"]
        with self.assertRaisesRegex(ValueError, "duration_frames"):
            script_to_storyboard(script)
        script = valid_script()
        script["scenes"][0]["shots"][0]["scene_id"] = "EP001-SC02"
        self.assertTrue(any("所在场景" in error for error in validate_script(script)))


if __name__ == "__main__":
    unittest.main()
