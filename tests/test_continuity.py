from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.continuity import check_continuity, validate_characters
from short_drama.validation import validate_storyboard
from test_validation import valid_shot


def valid_characters():
    return {"characters": [{"character_id": "CHAR-001", "name": "林知夏", "age": "25岁",
        "face_features": "椭圆脸，左眼下淡痣", "hairstyle": "黑色齐肩发", "body": "中等身高，纤细",
        "outfits": {"default": {"description": "深蓝外套", "props": ["旧钥匙"]}},
        "reference_images": {view: f"assets/reference/CHAR-001-{view}.png" for view in ("front", "side", "back")},
        "expressions": ["警惕", "释然"], "fixed_props": ["旧钥匙"],
        "scene_looks": {"EP001-SC01": "default"}, "historical_shots": [], "relationships": {},
        "voice": {"profile_id": "lin-test", "language": "zh-CN", "pitch_hz": 220, "rate": 1.0}}]}


def continuity_state():
    return {"time": "雨夜23:10", "space": "书店门口", "time_jump": False,
            "characters": {"CHAR-001": {"outfit": "default", "props": ["旧钥匙"], "expression": "警惕",
                                       "screen_position": "left", "entry": "none", "exit": "none"}},
            "relationship_changes": [], "previous_shot_id": None}


class CharacterTests(unittest.TestCase):
    def test_valid_profile_and_optional_reference_existence(self):
        self.assertEqual(validate_characters(valid_characters()), [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(any("参考图不存在" in error for error in validate_characters(valid_characters(), Path(tmp))))

    def test_rejects_missing_visuals_duplicate_ids_unknown_relationships(self):
        profiles = valid_characters()
        del profiles["characters"][0]["face_features"]
        profiles["characters"].append(deepcopy(profiles["characters"][0]))
        profiles["characters"][0]["relationships"]["CHAR-099"] = "旧友"
        errors = validate_characters(profiles)
        self.assertTrue(any("face_features" in error for error in errors))
        self.assertTrue(any("ID 重复" in error for error in errors))
        self.assertTrue(any("未知关系角色" in error for error in errors))

    def test_reference_traversal_voice_types_outfit_links(self):
        for edit in (lambda p: p["reference_images"].update(front="../x.png"),
                     lambda p: p["voice"].update(pitch_hz=True),
                     lambda p: p["scene_looks"].update({"EP001-SC01": "unknown"})):
            profiles = valid_characters()
            edit(profiles["characters"][0])
            self.assertTrue(validate_characters(profiles))

    def test_unknown_storyboard_character_is_rejected(self):
        shot = valid_shot()
        shot["characters"] = ["CHAR-999"]
        self.assertTrue(any("未知角色" in error for error in validate_storyboard(
            {"episode_id": "EP001", "fps": 30, "aspect_ratio": "9:16", "shots": [shot]}, valid_characters())))


class ContinuityTests(unittest.TestCase):
    def board(self):
        first, second = valid_shot(), valid_shot("EP001-SC01-SH002")
        first["continuity"] = continuity_state()
        second["continuity"] = continuity_state()
        second["continuity"]["previous_shot_id"] = first["shot_id"]
        return {"episode_id": "EP001", "fps": 30, "aspect_ratio": "9:16", "shots": [first, second]}

    def test_declared_continuity_passes_and_limit_is_explicit(self):
        report = check_continuity(self.board(), valid_characters())
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertIn("不保证", report["scope"])

    def test_changes_and_direction_generate_actionable_warnings(self):
        board = self.board()
        first, second = board["shots"]
        first["continuity"]["characters"]["CHAR-001"]["exit"] = "right"
        second["continuity"]["characters"]["CHAR-001"].update(props=[], entry="right")
        warnings = check_continuity(board, valid_characters())["warnings"]
        self.assertTrue(any("道具" in warning for warning in warnings))
        self.assertTrue(any("props" in warning for warning in warnings))
        self.assertTrue(any("方向" in warning for warning in warnings))

    def test_time_space_and_previous_shot(self):
        board = self.board()
        board["shots"][1]["continuity"].update(time="翌日", space="室内", previous_shot_id="EP001-SC02-SH003")
        report = check_continuity(board, valid_characters())
        self.assertTrue(any("previous_shot_id" in error for error in report["errors"]))
        self.assertTrue(any("time_jump" in warning for warning in report["warnings"]))
        self.assertTrue(any("空间" in warning for warning in report["warnings"]))

    def test_malformed_metadata_returns_errors(self):
        board = self.board()
        board["shots"][0]["continuity"]["characters"] = []
        self.assertTrue(check_continuity(board, valid_characters())["errors"])


if __name__ == "__main__":
    unittest.main()
