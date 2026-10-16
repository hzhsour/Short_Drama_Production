"""Offline regression checks for the vendored scaffold's filesystem boundaries."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("create_storyboard_package.py")


class ScaffoldSafetyTests(unittest.TestCase):
    def run_scaffold(self, root: Path, slug: str, *extra: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), slug, "--root", str(root), *extra],
            capture_output=True, text=True, timeout=10,
        )

    def test_offline_package_has_expected_deliverables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.run_scaffold(root, "ep001-director", "--title", "技术分镜测试")
            self.assertEqual(result.returncode, 0, result.stderr)
            package = root / "storyboard_projects/ep001-director"
            self.assertEqual(len(list(package.rglob("*.md"))), 31)
            self.assertIn("9:16", (package / "01_script_brief/project_brief.md").read_text())
            self.assertTrue((package / "03_storyboard/handoff_design_matrix.md").is_file())
            self.assertTrue((package / "03_storyboard/edit_boundary_matrix.md").is_file())

    def test_rejects_path_traversal_and_absolute_slug(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for slug in ["../escape", "a/b", "/absolute", "a\\b", "a" * 65]:
                with self.subTest(slug=slug):
                    self.assertNotEqual(self.run_scaffold(root, slug).returncode, 0)
            self.assertFalse((root / "storyboard_projects").exists())

    def test_existing_package_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(self.run_scaffold(root, "ep001").returncode, 0)
            script = root / "storyboard_projects/ep001/01_script_brief/script.md"
            script.write_text("保留我的剧本", encoding="utf-8")
            self.assertNotEqual(self.run_scaffold(root, "ep001").returncode, 0)
            self.assertEqual(script.read_text(), "保留我的剧本")
            self.assertNotEqual(self.run_scaffold(root, "ep001", "--force").returncode, 0)
            self.assertEqual(script.read_text(), "保留我的剧本")

    def test_rejects_symlink_package_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "private"
            target.mkdir()
            (root / "storyboard_projects").symlink_to(target, target_is_directory=True)
            self.assertNotEqual(self.run_scaffold(root, "ep001").returncode, 0)
            self.assertEqual(list(target.iterdir()), [])

    def test_rejects_dangling_symlink_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages = root / "storyboard_projects"
            packages.mkdir()
            (packages / "ep001").symlink_to(root / "missing", target_is_directory=True)
            self.assertNotEqual(self.run_scaffold(root, "ep001").returncode, 0)
            self.assertFalse((root / "missing").exists())


if __name__ == "__main__":
    unittest.main()
