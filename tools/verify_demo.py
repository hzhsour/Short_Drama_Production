#!/usr/bin/env python3
"""Independently verify the public technical fixture after the production run."""

from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.io import file_hash, load_json, write_json
from short_drama.media import qc_video


def verify(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    record = load_json(run_dir / "run.json")
    videos = load_json(run_dir / "video-result.json")
    timeline = load_json(run_dir / "timeline.json")
    errors = []
    if record.get("status") != "completed" or record.get("technical_test") is not True:
        errors.append("技术制作未完成")
    for name, filename in (("script_sha256", "script.json"), ("characters_sha256", "characters.json")):
        if record["inputs"].get(name) != file_hash(ROOT / "examples/technical-demo" / filename):
            errors.append("不是公开fixture的当前输入")
    if any(record["inputs"].get(key) != "mock" for key in ("mode", "provider", "audio_mode")):
        errors.append("技术验收只允许Mock，不得替代真实API验收")
    for job in videos["jobs"]:
        if job["status"] != "succeeded" or job.get("attempts", {}).get("submit") != 1:
            errors.append(f"镜头未完成或重复提交: {job['shot_id']}")
        artifact = job.get("artifact", {})
        if not artifact.get("path") or file_hash(Path(artifact["path"])) != artifact.get("sha256"):
            errors.append(f"镜头素材哈希不符: {job['shot_id']}")
    output = Path(record["output"])
    quality = qc_video(output, timeline)
    errors.extend(quality["errors"])
    if file_hash(output) != record["tasks"]["render"].get("sha256"):
        errors.append("最终成片哈希不符")
    srt = (run_dir / "subtitles.srt").read_text(encoding="utf-8")
    if "有人留下了这把钥匙。" not in srt or "先别开门。" not in srt or "00:00:01,167" not in srt:
        errors.append("中文对白或片头字幕偏移不符")
    audios = [stream for stream in (quality.get("probe") or {}).get("streams", []) if stream.get("codec_type") == "audio"]
    if not audios or str(audios[0].get("sample_rate")) != "48000":
        errors.append("最终音轨采样率不是48kHz")
    if record["tasks"].get("postproduction", {}).get("status") != "succeeded":
        errors.append("没有FFmpeg后期记录")
    return {
        "schema": "short-drama.technical-verification/v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not errors,
        "errors": errors,
        "technical_test": True,
        "real_generation_api_called": False,
        "real_chinese_tts_synthesized": False,
        "episode_id": record["episode_id"],
        "input_hashes": {key: record["inputs"][key] for key in ("script_sha256", "characters_sha256")},
        "video_sha256": file_hash(output),
        "duration_frames": timeline["duration_frames"],
        "width": timeline["width"], "height": timeline["height"], "fps": timeline["fps"],
        "video_codec": "h264", "audio_codec": "aac", "audio_sample_rate": 48000,
        "shot_ids": [job["shot_id"] for job in videos["jobs"]],
        "submissions_per_shot": {job["shot_id"]: job["attempts"]["submit"] for job in videos["jobs"]},
        "warnings": load_json(run_dir / "quality.json").get("warnings", []),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立检查公开Mock技术片与恢复幂等性")
    parser.add_argument("run_dir", type=Path, nargs="?", default=ROOT / "runs/technical-demo")
    parser.add_argument("--check-resume", action="store_true")
    args = parser.parse_args()
    result = verify(args.run_dir)
    if result["passed"] and args.check_resume:
        output = Path(load_json(args.run_dir / "run.json")["output"])
        before = (file_hash(output), output.stat().st_mtime_ns)
        resumed = subprocess.run([sys.executable, str(ROOT / "tools/drama.py"), "demo", "--run-dir", str(args.run_dir), "--render"], cwd=ROOT, capture_output=True, text=True, timeout=180)
        healthy = resumed.returncode == 0 and before == (file_hash(output), output.stat().st_mtime_ns)
        healthy = healthy and verify(args.run_dir)["passed"]
        result["resume_reused_final_file_without_resubmission"] = healthy
        if not healthy:
            result["errors"].append("恢复运行未复用已有成片，或重新提交了镜头")
            result["passed"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    write_json(args.run_dir / "verification.json", result)
    raise SystemExit(0 if result["passed"] else 1)
