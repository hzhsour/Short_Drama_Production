"""Exercise interrupted Live recovery with local ledgers and fake submissions.

No provider API or TTS service is used. The fake engine writes a provider ID to
the real StateStore, then interrupts before video-result.json can be published.
"""

import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.cli import _generate_once, main, parser
from short_drama.io import file_hash
from short_drama.pipeline import run_pipeline
from short_drama.script import script_to_storyboard
from short_drama.state import StateStore


class SimulatedInterruption(RuntimeError):
    """The fake provider accepted a task before the worker was interrupted."""


class LedgerRecoveryTests(unittest.TestCase):
    script = ROOT / "examples/technical-demo/script.json"
    characters = ROOT / "examples/technical-demo/characters.json"

    def interrupted_run(self, root: Path, *, generic: bool = False) -> dict:
        run_dir, workspace = root / "run", root / "original-workspace"
        approval = root / "fixture-creative-approval.json"
        approval.write_text(json.dumps({"creative": {"approved": True,
            "script_sha256": file_hash(self.script), "characters_sha256": file_hash(self.characters)}}))
        identity_path = run_dir / ("engine-context.json" if generic else "run.json")
        observed = {}
        test = self

        class InterruptedFakeEngine:
            def __init__(self, path, **kwargs):
                self.state = StateStore(Path(path) / "state/video-jobs.sqlite3")

            def plan(self, storyboard):
                return []

            def run(self, storyboard, **kwargs):
                # This assertion occurs at the submission boundary, before the
                # accepted task is written and before pipeline result output.
                persisted = json.loads(identity_path.read_text(encoding="utf-8"))
                context = persisted if generic else persisted["execution_context"]
                test.assertEqual(context["ledger_id"], self.state.ledger_id)
                test.assertEqual(context["engine_workspace"], str(workspace.resolve()))
                if not generic:
                    test.assertEqual(persisted["tasks"]["ledger"]["status"], "succeeded")
                observed["ledger_id"] = self.state.ledger_id
                self.state.ensure({"job_key": "fixture-accepted-job", "episode_id": storyboard["episode_id"],
                    "shot_id": storyboard["shots"][0]["shot_id"], "request_hash": "fixture-exact-request",
                    "provider_job_id": "fixture-no-network-provider-id", "status": "submitted"})
                raise SimulatedInterruption("fixture: accepted task, no result file yet")

        if generic:
            board = script_to_storyboard(json.loads(self.script.read_text()), json.loads(self.characters.read_text()))
            board_path = root / "storyboard.json"
            board_path.write_text(json.dumps(board), encoding="utf-8")
            args = parser().parse_args(["generate", str(board_path), "--run-dir", str(run_dir), "--mode", "live",
                "--provider", "volcengine-seedance-2.5", "--project-workspace", str(workspace)])
            with patch("short_drama.cli.VideoEngine", side_effect=InterruptedFakeEngine):
                with self.assertRaises(SimulatedInterruption):
                    _generate_once(args, board)
            observed.update(args=args, board=board)
        else:
            options = {"mode": "live", "provider": "fixture-no-network-provider", "approval_file": approval,
                       "project_workspace": workspace}
            with patch("short_drama.pipeline.VideoEngine", side_effect=InterruptedFakeEngine):
                with self.assertRaises(SimulatedInterruption):
                    run_pipeline(self.script, self.characters, run_dir, **options)
            observed["options"] = options
        self.assertFalse((run_dir / "video-result.json").exists())
        observed.update(root=root, run_dir=run_dir, workspace=workspace, identity_path=identity_path,
                        db_path=workspace / "state/video-jobs.sqlite3")
        self.assertEqual(StateStore.read_ledger_id(observed["db_path"]), observed["ledger_id"])
        return observed

    def test_pipeline_persists_ledger_uuid_before_first_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.interrupted_run(Path(temporary))
            state = StateStore(fixture["db_path"])
            self.assertEqual(state.get("fixture-accepted-job")["provider_job_id"], "fixture-no-network-provider-id")
            self.assertEqual(state.ledger_id, fixture["ledger_id"])

    def test_missing_or_replaced_ledger_blocks_before_engine_construction(self):
        for replacement in ("missing", "new-empty", "corrupt"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                fixture = self.interrupted_run(Path(temporary))
                original_context = fixture["identity_path"].read_bytes()
                fixture["db_path"].unlink()
                if replacement == "new-empty":
                    replacement_store = StateStore(fixture["db_path"])
                    self.assertNotEqual(replacement_store.ledger_id, fixture["ledger_id"])
                elif replacement == "corrupt":
                    fixture["db_path"].write_bytes(b"not a SQLite database")
                with patch("short_drama.pipeline.VideoEngine") as engine:
                    with self.assertRaisesRegex(ValueError, "账本丢失|身份已变化"):
                        run_pipeline(self.script, self.characters, fixture["run_dir"], **fixture["options"])
                    engine.assert_not_called()
                self.assertEqual(fixture["identity_path"].read_bytes(), original_context)
                if replacement == "missing":
                    self.assertFalse(fixture["db_path"].exists())

    def test_rebind_rejects_wrong_uuid_without_video_result_before_constructing_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self.interrupted_run(root)
            wrong_workspace = root / "empty-unrelated-workspace"
            StateStore(wrong_workspace / "state/video-jobs.sqlite3")
            before = fixture["identity_path"].read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("short_drama.cli.VideoEngine") as engine:
                code = main(["rebind-storage", str(wrong_workspace), str(root / "restored-media"),
                             "--run-dir", str(fixture["run_dir"])])
            self.assertEqual(code, 2)
            self.assertIn("UUID", output.getvalue())
            engine.assert_not_called()
            self.assertEqual(fixture["identity_path"].read_bytes(), before)

    def test_copied_original_uuid_can_be_explicitly_rebound_without_result_file(self):
        for generic in (False, True):
            with self.subTest(generic=generic), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self.interrupted_run(root, generic=generic)
                restored_workspace = root / "restored-original-workspace"
                restored_db = restored_workspace / "state/video-jobs.sqlite3"
                restored_db.parent.mkdir(parents=True)
                shutil.copy2(fixture["db_path"], restored_db)
                self.assertEqual(StateStore.read_ledger_id(restored_db), fixture["ledger_id"])
                # Rebind uses the real local storage code but never runs an
                # adapter. A socket guard makes accidental HTTP a hard failure.
                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch("socket.create_connection", side_effect=AssertionError("network forbidden in ledger recovery tests")):
                    code = main(["rebind-storage", str(restored_workspace), str(root / "restored-media"),
                                 "--run-dir", str(fixture["run_dir"])])
                self.assertEqual(code, 0, output.getvalue())
                record = json.loads(fixture["identity_path"].read_text())
                context = record if generic else record["execution_context"]
                self.assertEqual(context["ledger_id"], fixture["ledger_id"])
                self.assertEqual(context["engine_workspace"], str(restored_workspace.resolve()))
                state = StateStore(restored_db)
                self.assertEqual(state.get("fixture-accepted-job")["provider_job_id"], "fixture-no-network-provider-id")
                self.assertFalse((fixture["run_dir"] / "video-result.json").exists())

    def test_generic_generate_sidecar_persists_uuid_and_blocks_missing_or_replaced_db(self):
        for replacement in ("missing", "new-empty"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                fixture = self.interrupted_run(Path(temporary), generic=True)
                before = fixture["identity_path"].read_bytes()
                fixture["db_path"].unlink()
                if replacement == "new-empty":
                    StateStore(fixture["db_path"])
                with patch("short_drama.cli.VideoEngine") as engine:
                    with self.assertRaisesRegex(ValueError, "UUID"):
                        _generate_once(fixture["args"], fixture["board"])
                    engine.assert_not_called()
                self.assertEqual(fixture["identity_path"].read_bytes(), before)

    def test_uuid_reader_does_not_create_or_migrate_missing_or_corrupt_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.sqlite3"
            self.assertIsNone(StateStore.read_ledger_id(path))
            self.assertFalse(path.exists())
            path.write_bytes(b"unchanged corrupt fixture")
            original = path.read_bytes()
            self.assertIsNone(StateStore.read_ledger_id(path))
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
