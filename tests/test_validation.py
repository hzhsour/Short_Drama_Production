from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.validation import validate_project, validate_storyboard


def valid_shot(shot_id="EP001-SC01-SH001"):
    return {
        "shot_id": shot_id,
        "scene_id": "EP001-SC01",
        "duration_frames": 45,
        "characters": ["CHAR-001"],
        "location": "LOC-001",
        "action": "人物停下脚步，望向门外。",
        "framing": "中近景",
        "camera_move": "缓慢推进",
        "dialogue": [],
        "audio": [],
        "image_prompt": "夜晚的老街，电影感，竖屏构图",
        "video_prompt": "镜头缓慢推进，人物自然转头",
        "continuity_refs": ["CHAR-001-front-reference.png"],
    }


class StoryboardValidationTests(unittest.TestCase):
    def test_accepts_valid_storyboard(self):
        storyboard = {
            "episode_id": "EP001",
            "aspect_ratio": "9:16",
            "fps": 30,
            "shots": [valid_shot()],
        }
        self.assertEqual(validate_storyboard(storyboard), [])

    def test_rejects_missing_fields_and_nonpositive_duration(self):
        storyboard = {
            "episode_id": "EP001",
            "aspect_ratio": "9:16",
            "fps": 30,
            "shots": [{"shot_id": "EP001-SC01-SH001", "duration_frames": 0}],
        }
        errors = validate_storyboard(storyboard)
        self.assertIn("shots[0].duration_frames 必须是正整数", errors)
        self.assertTrue(any("缺少字段: action" in error for error in errors))

    def test_rejects_duplicate_shot_ids(self):
        storyboard = {
            "episode_id": "EP001",
            "aspect_ratio": "9:16",
            "fps": 30,
            "shots": [valid_shot(), valid_shot()],
        }
        self.assertIn("镜头 ID 重复: EP001-SC01-SH001", validate_storyboard(storyboard))

    def test_rejects_invalid_top_level_type(self):
        self.assertEqual(validate_storyboard([]), ["分镜顶层必须是 JSON 对象"])


class ProjectScaffoldTests(unittest.TestCase):
    def test_project_scaffold_is_complete(self):
        self.assertEqual(validate_project(ROOT), [])


if __name__ == "__main__":
    unittest.main()
