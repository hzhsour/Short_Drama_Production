from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.providers.mock import MockAdapter
from short_drama.providers.base import SafeRetryError
from short_drama.video_engine import VideoEngine
from short_drama.waiting import WaitPolicy, run_with_wait
from test_video_engine import storyboard


class SequenceMockAdapter(MockAdapter):
    def __init__(self):
        self.submissions = 0
        self.polls = 0

    def submit(self, request, idempotency_key):
        self.submissions += 1
        return super().submit(request, idempotency_key)

    def poll(self, provider_job_id):
        self.polls += 1
        return {"provider_job_id": provider_job_id, "status": ("queued", "running", "succeeded")[min(self.polls - 1, 2)]}


class FakeClock:
    def __init__(self):
        self.value = 0
        self.delays = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.value += seconds


class PendingEngine:
    def __init__(self, clock):
        self.clock = clock
        self.calls = 0

    def run(self, board, max_jobs=None, *, deadline=None, poll_budget=None):
        reached = deadline is not None and self.clock() >= deadline
        used = 0 if reached else 1
        self.calls += used
        return {"all_succeeded": False, "jobs": [{"status": "running", "provider_job_id": "same-task"}],
                "wait_limits": {"polls_used": used, "deadline_reached": reached}}


class WaitPolicyTests(unittest.TestCase):
    def test_wait_does_not_silently_override_explicit_job_limit(self):
        clock = FakeClock()
        engine = PendingEngine(clock)
        with self.assertRaisesRegex(ValueError, "max_jobs"):
            run_with_wait(engine, {}, max_jobs=1, policy=WaitPolicy(10))
        self.assertEqual(engine.calls, 0)

    def test_rejects_unbounded_invalid_configuration(self):
        for kwargs in ({"total_seconds": 0}, {"total_seconds": float("nan")}, {"total_seconds": 3601},
                       {"total_seconds": 1, "max_polls": 0}, {"total_seconds": 1, "backoff": .5},
                       {"total_seconds": 1, "initial_interval": 61, "max_interval": 61}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                WaitPolicy(**kwargs)

    def test_deadline_is_waiting_not_failure_and_checkpoint_retains_id(self):
        clock = FakeClock()
        engine = PendingEngine(clock)
        records = []
        result = run_with_wait(engine, {}, policy=WaitPolicy(.15, 10, .1, 2, .2),
                               checkpoint=lambda value: records.append(deepcopy(value)), clock=clock, sleep=clock.sleep)
        self.assertEqual(result["wait"]["reason"], "deadline")
        self.assertEqual(engine.calls, 2)
        self.assertEqual(result["jobs"][0]["status"], "running")
        self.assertEqual(result["jobs"][0]["provider_job_id"], "same-task")
        self.assertAlmostEqual(sum(clock.delays), .15)
        self.assertEqual(len(records), 3)

    def test_poll_count_bound_and_backoff_cap(self):
        clock = FakeClock()
        engine = PendingEngine(clock)
        result = run_with_wait(engine, {}, policy=WaitPolicy(10, 4, .1, 2, .25), clock=clock, sleep=clock.sleep)
        self.assertEqual(result["wait"]["reason"], "poll_limit")
        self.assertEqual(result["wait"]["polls_used"], 4)
        self.assertEqual(clock.delays, [.1, .2, .25])

    def test_unknown_submit_is_not_automatically_retried(self):
        class Unknown(PendingEngine):
            def run(self, *args, **kwargs):
                result = super().run(*args, **kwargs)
                result["jobs"][0]["status"] = "submission_unknown"
                return result
        clock = FakeClock()
        engine = Unknown(clock)
        result = run_with_wait(engine, {}, policy=WaitPolicy(10), clock=clock, sleep=clock.sleep)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(result["wait"]["reason"], "operator_attention")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local media tools required")
class WaitEngineIntegrationTests(unittest.TestCase):
    def test_inflight_local_deadline_does_not_consume_failure_retry_budget(self):
        class ExpiringAdapter(SequenceMockAdapter):
            expire = True
            def poll(self, provider_job_id):
                self.polls += 1
                if self.expire:
                    self.expire = False
                    self.engine._active_deadline = time.monotonic() - 1
                    raise SafeRetryError("local status request timeout")
                return {"provider_job_id": provider_job_id, "status": "succeeded"}
        with tempfile.TemporaryDirectory() as temporary:
            adapter = ExpiringAdapter()
            engine = VideoEngine(Path(temporary), adapter=adapter, max_retries=0)
            adapter.engine = engine
            first = engine.run(storyboard(), deadline=time.monotonic() + 10, poll_budget=1)
            job = first["jobs"][0]
            task = job["provider_job_id"]
            self.assertEqual(job["status"], "submitted")
            self.assertEqual(job["error_counts"]["poll"], 0)
            second = engine.run(storyboard())
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(second["jobs"][0]["provider_job_id"], task)
            self.assertEqual(adapter.submissions, 1)

    def test_queued_running_succeeded_downloads_once_without_resubmit(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = SequenceMockAdapter()
            engine = VideoEngine(Path(temporary), adapter=adapter)
            checkpoints = []
            result = run_with_wait(engine, storyboard(), policy=WaitPolicy(30, 3, 0, 1, 0),
                                   checkpoint=lambda value: checkpoints.append(deepcopy(value)))
            self.assertTrue(result["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(adapter.polls, 3)
            self.assertEqual(result["jobs"][0]["attempts"]["poll"], 3)
            self.assertTrue(Path(result["jobs"][0]["artifact"]["path"]).is_file())
            self.assertEqual([value["jobs"][0]["status"] for value in checkpoints], ["submitted", "running", "succeeded"])

    def test_poll_limit_then_new_process_reuses_provider_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = SequenceMockAdapter()
            workspace = Path(temporary)
            first = run_with_wait(VideoEngine(workspace, adapter=adapter), storyboard(), policy=WaitPolicy(30, 2, 0, 1, 0))
            self.assertFalse(first["all_succeeded"])
            self.assertEqual(first["wait"]["reason"], "poll_limit")
            task = first["jobs"][0]["provider_job_id"]
            second = run_with_wait(VideoEngine(workspace, adapter=adapter), storyboard(), policy=WaitPolicy(30, 1, 0, 1, 0))
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(second["jobs"][0]["provider_job_id"], task)
            self.assertEqual(adapter.submissions, 1)


if __name__ == "__main__":
    unittest.main()
