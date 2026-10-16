#!/usr/bin/env python3
"""Public fixture: queued -> running -> succeeded -> render; no network/API."""

from pathlib import Path
import argparse
import json
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.io import load_json, write_json
from short_drama.pipeline import run_pipeline
from short_drama.providers.mock import MockAdapter
from short_drama.video_engine import VideoEngine
from short_drama.waiting import WaitPolicy


class QueuedMock(MockAdapter):
    def __init__(self):
        self.polls = {}
        self.submissions = 0

    def submit(self, request, idempotency_key):
        self.submissions += 1
        return super().submit(request, idempotency_key)

    def poll(self, provider_job_id):
        count = self.polls.get(provider_job_id, 0)
        self.polls[provider_job_id] = count + 1
        return {"provider_job_id": provider_job_id, "status": ("queued", "running", "succeeded")[min(count, 2)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=ROOT / "runs/prelive-async")
    args = parser.parse_args()
    if (args.run_dir / "run.json").exists():
        raise SystemExit("请选择新的验收运行目录，避免把旧结果当成新测试")
    adapter = QueuedMock()
    def engine(*values, **options):
        return VideoEngine(*values, adapter=adapter, **options)
    fixture = ROOT / "examples/technical-demo"
    values = (fixture / "script.json", fixture / "characters.json", args.run_dir)
    with patch("short_drama.pipeline.VideoEngine", side_effect=engine):
        first = run_pipeline(*values, wait_policy=WaitPolicy(30, 2, 0, 1, 0))
        assert first["status"] == "waiting_video"
        before = load_json(args.run_dir / "video-result.json")
        assert before["wait"]["reason"] == "poll_limit"
        task_id = before["jobs"][0]["provider_job_id"]
        result = run_pipeline(*values, wait_policy=WaitPolicy(60, 10, 0, 1, 0), render=True)
    videos = load_json(args.run_dir / "video-result.json")
    assert result["status"] == "completed"
    assert videos["jobs"][0]["provider_job_id"] == task_id
    assert all(job["attempts"]["submit"] == 1 and job["attempts"]["poll"] == 3 for job in videos["jobs"])
    assert adapter.submissions == len(videos["jobs"])
    report = {"passed": True, "mock_only": True, "real_generation_api_called": False,
              "first_pass": "poll_limit_waiting_not_failed", "resumed_same_provider_id": True,
              "states_per_job": ["queued", "running", "succeeded"], "rendered_output": result["output"],
              "jobs": [{"shot_id": job["shot_id"], "attempts": job["attempts"], "sha256": job["artifact"]["sha256"]} for job in videos["jobs"]]}
    write_json(args.run_dir / "async-verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
