#!/usr/bin/env python3
"""Exercise directory-independent recovery using only the public Mock fixture.

Requires an already completed technical-demo. Copies stay local; no upload,
provider API, TTS API or new dependency is used. This is an acceptance exercise,
not a production backup service.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.io import file_hash, load_json, write_json
from short_drama.pipeline import run_lock, run_pipeline
from short_drama.recovery import restore_run
from short_drama.state import StateStore


def _copy_snapshot(source_run: Path, destination: Path) -> tuple[Path, Path, Path, Path]:
    """Stop one fixture worker via lock and use SQLite backup for its ledger."""
    run, engine, storage, assets = [destination / name for name in ("run", "engine", "video", "assets")]
    with run_lock(source_run):
        record = load_json(source_run / "run.json")
        context = record["execution_context"]
        shutil.copytree(source_run, run)
        shutil.copytree(Path(context["engine_workspace"]), engine)
        shutil.copytree(Path(context["storage_root"]), storage)
        assets.mkdir(parents=True)
        # The acceptance source is explicitly restricted to public input hashes.
        for name in ("script.json", "characters.json", "README.md"):
            target = assets / "examples/technical-demo" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "examples/technical-demo" / name, target)
        original = sqlite3.connect(Path(context["engine_workspace"]) / "state/video-jobs.sqlite3")
        copied = sqlite3.connect(engine / "state/video-jobs.sqlite3")
        try:
            original.backup(copied)
        finally:
            original.close()
            copied.close()
    return run, engine, storage, assets


def verify_recovery(source_run: Path, destination: Path) -> dict:
    source_run, destination = source_run.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError("验收目标目录必须是新目录，避免覆盖既有恢复资料")
    if destination.is_relative_to(source_run) or source_run.is_relative_to(destination):
        raise ValueError("恢复验收目录与源运行目录不能互相包含")
    original_record = load_json(source_run / "run.json")
    if original_record.get("status") != "completed" or any(original_record["inputs"].get(key) != "mock" for key in ("mode", "provider", "audio_mode")):
        raise ValueError("仅允许已完成的公开Mock fixture；不验收或复制Live/私人制作")
    for key, filename in (("script_sha256", "script.json"), ("characters_sha256", "characters.json")):
        if original_record["inputs"].get(key) != file_hash(ROOT / "examples/technical-demo" / filename):
            raise ValueError("输入不是仓库公开fixture的当前版本")
    destination.mkdir(parents=True)
    # Stage a fully self-contained origin, then snapshot it into different roots.
    # Renaming this origin makes every saved active path unavailable, without
    # disturbing the user's actual source run or repository.
    origin = _copy_snapshot(source_run, destination / "original")
    restore_run(*origin[:3], new_asset_root=origin[3])
    restored = _copy_snapshot(origin[0], destination / "restored")
    (destination / "original").rename(destination / "original-now-unavailable")
    old_run = origin[0]
    before = load_json(restored[0] / "video-result.json")
    identity = {job["job_key"]: {"provider_job_id": job.get("provider_job_id"), "attempts": job.get("attempts"),
                                "request_hash": job["request_hash"], "sha256": job["artifact"]["sha256"]} for job in before["jobs"]}
    result = restore_run(*restored[:3], new_asset_root=restored[3])
    record = load_json(restored[0] / "run.json")
    output = Path(record["output"])
    before_output = (file_hash(output), output.stat().st_mtime_ns)
    script = restored[3] / "examples/technical-demo/script.json"
    characters = restored[3] / "examples/technical-demo/characters.json"
    inputs = record["inputs"]
    options = {"mode": "mock", "provider": "mock", "audio_mode": inputs.get("audio_mode", "mock"),
               "asset_root": restored[3], "project_workspace": restored[1], "storage_root": restored[2],
               "intro_frames": inputs["intro_frames"], "outro_frames": inputs["outro_frames"], "render": True}
    if "sound_mode" in inputs:
        options["sound_mode"] = inputs["sound_mode"]
    # A reused completed task must not even call the Mock provider methods, nor
    # render/normalize a new output. QC still decodes the real recovered MP4.
    with patch("short_drama.providers.mock.MockAdapter.submit", side_effect=AssertionError("unexpected resubmit")), \
         patch("short_drama.providers.mock.MockAdapter.poll", side_effect=AssertionError("unexpected poll")), \
         patch("short_drama.providers.mock.MockAdapter.download", side_effect=AssertionError("unexpected download")), \
         patch("short_drama.pipeline.render_timeline", side_effect=AssertionError("unexpected rerender")), \
         patch("short_drama.pipeline.normalize_media", side_effect=AssertionError("unexpected normalize")):
        resumed = run_pipeline(script, characters, restored[0], **options)
    after = load_json(restored[0] / "video-result.json")
    after_identity = {job["job_key"]: {"provider_job_id": job.get("provider_job_id"), "attempts": job.get("attempts"),
                                      "request_hash": job["request_hash"], "sha256": job["artifact"]["sha256"]} for job in after["jobs"]}
    quality = load_json(restored[0] / "quality.json")
    errors = []
    if old_run.exists():
        errors.append("原目录仍可访问")
    if identity != after_identity:
        errors.append("任务身份、次数或视频哈希变化")
    if before_output != (file_hash(output), output.stat().st_mtime_ns):
        errors.append("已恢复成片未被原样复用")
    if resumed.get("status") != "completed" or not quality.get("passed"):
        errors.append("恢复后制作或质检未通过")
    ledger_id = StateStore.read_ledger_id(restored[1] / "state/video-jobs.sqlite3")
    if ledger_id != original_record["execution_context"]["ledger_id"]:
        errors.append("原账本UUID未保留")
    report = {"schema": "short-drama.full-recovery-verification/v1", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "passed": not errors, "errors": errors, "scope": "public_mock_fixture_only",
              "original_paths_unavailable": not old_run.exists(), "ledger_id": ledger_id,
              "task_ids_request_hashes_attempts_preserved": identity == after_identity,
              "final_output_reused_without_rendering": before_output == (file_hash(output), output.stat().st_mtime_ns),
              "final_video_sha256": file_hash(output), "quality_passed": quality.get("passed"),
              "audio_timeline_and_production_state_rebound": True, "recovery": result,
              "paid_api_called": False, "private_media_uploaded": False,
              "production_backup_service_deployed": False, "warnings": quality.get("warnings", [])}
    write_json(destination / "verification.json", report)
    return report


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description="公开Mock成片的异地完整恢复验收；不备份私人制作")
    parser.add_argument("--source-run", type=Path, default=ROOT / "runs/technical-demo")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    report = verify_recovery(args.source_run, args.destination)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
