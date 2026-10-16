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
    def board(self):
        return {"episode_id": "EP001", "aspect_ratio": "9:16", "fps": 30, "shots": [valid_shot()]}

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

    def test_rejects_wrong_types_episode_and_unsafe_paths(self):
        for key, value in (("episode_id", []), ("aspect_ratio", 916), ("fps", True), ("fps", 0)):
            board = self.board()
            board[key] = value
            self.assertTrue(validate_storyboard(board))
        for path in ("../secret.png", "/tmp/x.png", "C:\\x.png", "https://x/a", "a//b.png"):
            board = self.board()
            board["shots"][0]["continuity_refs"] = [path]
            self.assertTrue(any("相对路径" in error for error in validate_storyboard(board)))

    def test_rejects_wrong_scene_and_duplicate_characters(self):
        board = self.board()
        board["shots"][0]["scene_id"] = "EP001-SC02"
        board["shots"][0]["characters"] *= 2
        errors = validate_storyboard(board)
        self.assertTrue(any("不匹配" in error for error in errors))
        self.assertTrue(any("重复" in error for error in errors))

    def test_rejects_dialogue_references_bounds_overlap_and_booleans(self):
        line = {"character_id": "CHAR-001", "text": "你来了。", "start_frame": 0, "duration_frames": 20}
        for field, value in (("character_id", "CHAR-999"), ("text", ""), ("start_frame", True), ("duration_frames", 46)):
            board = self.board()
            changed = {**line, field: value}
            board["shots"][0]["dialogue"] = [changed]
            self.assertTrue(validate_storyboard(board), (field, value))
        board = self.board()
        board["shots"][0]["dialogue"] = [line, {**line, "start_frame": 10}]
        self.assertTrue(any("重叠" in error for error in validate_storyboard(board)))

    def test_rejects_bad_audio_and_accepts_legacy_sound_directions(self):
        board = self.board()
        board["shots"][0]["audio"] = ["雨声"]
        self.assertEqual(validate_storyboard(board), [])
        cue = {"kind": "bgm", "path": "assets/music/test.wav", "start_frame": 0, "duration_frames": 45, "volume": .2}
        board["shots"][0]["audio"] = [cue]
        self.assertEqual(validate_storyboard(board), [])
        for key, value in (("kind", "voice"), ("path", "../../private.wav"), ("volume", float("nan")), ("start_frame", -1)):
            board["shots"][0]["audio"] = [{**cue, key: value}]
            self.assertTrue(validate_storyboard(board))

    def test_draft_empty_shots_remains_compatible(self):
        board = self.board()
        board["shots"] = []
        self.assertEqual(validate_storyboard(board), [])


class ProjectScaffoldTests(unittest.TestCase):
    def test_project_scaffold_is_complete(self):
        self.assertEqual(validate_project(ROOT), [])


if __name__ == "__main__":
    unittest.main()
