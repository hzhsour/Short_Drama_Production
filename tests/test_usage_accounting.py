"""Offline usage, reservation and bounded-poll acceptance contracts."""

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from short_drama.providers import MockAdapter, ProviderError, SafeRetryError
from short_drama.providers.ark import ArkAdapter, HttpTransport
from short_drama.video_engine import EngineError, VideoEngine


def board(episode="EP001", shots=1):
    return {"episode_id": episode, "fps": 30, "sound_mode": "dub", "shots": [
        {"shot_id": f"SH{index:03}", "duration_frames": 120, "video_prompt": "public offline fixture"}
        for index in range(shots)
    ]}


def config():
    return {
        "model_id": "fake-accounting-model", "live_enabled": True,
        "verification_status": "official_documentation_verified", "activation_verified_for_this_account": True,
        "capabilities": {"frame_rate": 24, "min_duration_seconds": 4, "max_duration_seconds": 30},
        "pricing": {"status": "verified_live_quote", "valid_until": "2099-01-01T00:00:00Z", "source_url": "https://example.invalid/offline-contract",
                    "currency": "CNY", "unit": "million_output_tokens", "estimate_supported_scope": "no_input_video_standard_generation_only",
                    "rates": {"1080p": {"without_input_video": "1"}}},
    }


class UsageAdapter(MockAdapter):
    paid = True
    provider_id = "fake-accounting"
    model_id = "fake-accounting-model"
    api_key_env = "TEST_VIDEO_API_KEY"

    def __init__(self, responses=None, submit_error=None):
        self.responses = list(responses or [{"status": "succeeded"}])
        self.submit_error = submit_error
        self.submissions = self.polls = self.downloads = 0

    def submit(self, request, idempotency_key):
        self.submissions += 1
        if self.submit_error:
            raise self.submit_error
        return {"provider_job_id": "fake-" + idempotency_key, "status": "submitted"}

    def poll(self, provider_job_id):
        self.polls += 1
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)

    def download(self, result, destination):
        self.downloads += 1
        destination.write_bytes(b"public mock accounting artifact; decoding mocked in these accounting tests")


def engine_for(root, adapter, data, *, project="20", episode="20", task="10"):
    model_config = config()
    limits = {"currency": "CNY", "per_task": task, "per_episode": episode, "project": project}
    approval = root / "fake-contract-approval.json"
    engine = VideoEngine(root, mode="live", provider="fake-accounting", adapter=adapter,
                         model_config=model_config, approval_file=approval, budgets=limits)
    approval.write_text(json.dumps({
        "approved": True, "approval_id": "OFFLINE-TEST-ONLY", "provider": "fake-accounting", "model_id": adapter.model_id,
        "currency": "CNY", "expires_at": "2099-01-01T00:00:00Z", "limits": limits,
        "request_hashes": [job["request_hash"] for job in engine.plan(data)],
    }), encoding="utf-8")
    return engine


QUALITY = {"has_audio": True, "audio_present": True, "source_audio_disposition": "discard_for_external_dub"}


@patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
class UsageAccountingTests(unittest.TestCase):
    def run_fixture(self, engine, data, **kwargs):
        with patch("short_drama.video_engine.probe_video", return_value=QUALITY):
            return engine.run(data, **kwargs)

    def test_estimate_reservation_provider_usage_calculation_and_final_invoice_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter([{"status": "succeeded", "provider_usage": {"completion_tokens": 100000},
                                     "provider_task_metadata": {"model": "fake-accounting-model", "resolution": "1080p"}}])
            engine = engine_for(Path(tmp), adapter, data)
            planned = engine.plan(data)[0]
            self.assertEqual(planned["estimated_cost"], "0.194400")
            self.assertIsNone(planned["reserved_budget"])
            result = self.run_fixture(engine, data)
            job = result["jobs"][0]
            self.assertEqual(job["reserved_budget"], "0.194400")
            self.assertEqual(job["provider_usage"], {"completion_tokens": 100000})
            self.assertEqual(job["calculated_cost"], "0.100000")
            self.assertEqual(job["billing_reconciliation_status"], "pending_final_invoice")
            self.assertEqual(result["financial_summary"]["conservative_budget_exposure"], "0.194400")
            self.assertNotIn("actual_cost", job)
            self.assertNotIn("charged_amount", job)
            self.assertEqual(job["provider_task_metadata"]["requested_output"]["generation_fps"], 24)

    def test_unknown_usage_retains_reservation_and_does_not_invent_charge(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            engine = engine_for(Path(tmp), UsageAdapter(), data)
            result = self.run_fixture(engine, data)
            job = result["jobs"][0]
            self.assertTrue(result["all_succeeded"])
            self.assertIsNone(job["provider_usage"])
            self.assertIsNone(job["calculated_cost"])
            self.assertEqual(job["billing_reconciliation_status"], "awaiting_provider_usage")
            self.assertEqual(result["reserved_project_cost"], "0.194400")

    def test_output_pricing_scope_mismatch_keeps_usage_unknown_cost_and_blocks_new_tasks(self):
        for mismatch in ({"resolution": "720p"}, {"model": "unexpected-model"}, {"framespersecond": 60}, {"ratio": "16:9"}):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                data = board(shots=2)
                adapter = UsageAdapter([{"status": "succeeded", "provider_usage": {"completion_tokens": 100000},
                                         "provider_task_metadata": mismatch}])
                result = self.run_fixture(engine_for(Path(tmp), adapter, data), data)
                job = result["jobs"][0]
                self.assertEqual(job["provider_usage"]["completion_tokens"], 100000)
                self.assertIsNone(job["calculated_cost"])
                self.assertEqual(job["billing_reconciliation_status"], "provider_usage_unpriced")
                self.assertEqual(result["jobs"][1]["status"], "blocked")
                self.assertEqual(adapter.submissions, 1)
                self.assertTrue(result["financial_summary"]["new_paid_tasks_blocked_by_cost_review"])

    def test_usage_exceeding_estimate_blocks_next_shot_and_next_episode_but_keeps_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = board(shots=2)
            adapter = UsageAdapter([{"status": "succeeded", "provider_usage": {"completion_tokens": 300000}}])
            result = self.run_fixture(engine_for(root, adapter, data), data)
            self.assertEqual([job["status"] for job in result["jobs"]], ["succeeded", "blocked"])
            self.assertEqual(adapter.downloads, 1)
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(result["reserved_project_cost"], "0.194400")
            self.assertEqual(result["financial_summary"]["conservative_budget_exposure"], "0.300000")
            self.assertTrue(result["financial_summary"]["new_paid_tasks_blocked_by_cost_review"])
            next_episode = board("EP002")
            second = self.run_fixture(engine_for(root, adapter, next_episode), next_episode)
            self.assertEqual(second["jobs"][0]["status"], "blocked")
            self.assertEqual(adapter.submissions, 1)

    def test_exact_project_limit_blocks_new_paid_task_without_releasing_prior_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = board()
            adapter = UsageAdapter()
            first = self.run_fixture(engine_for(root, adapter, data, project="0.194400"), data)
            self.assertTrue(first["all_succeeded"])
            next_episode = board("EP002")
            second = self.run_fixture(engine_for(root, adapter, next_episode, project="0.194400"), next_episode)
            self.assertEqual(second["jobs"][0]["status"], "blocked")
            self.assertIn("budget limit reached", second["jobs"][0]["last_error"])
            self.assertEqual(adapter.submissions, 1)

    def test_unknown_submit_keeps_reserved_budget_and_never_auto_resubmits(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter(submit_error=TimeoutError("unknown acceptance"))
            engine = engine_for(Path(tmp), adapter, data)
            first = self.run_fixture(engine, data)
            second = self.run_fixture(engine, data)
            self.assertEqual(first["jobs"][0]["status"], "submission_unknown")
            self.assertEqual(second["jobs"][0]["reserved_budget"], "0.194400")
            self.assertIsNone(second["jobs"][0]["calculated_cost"])
            self.assertEqual(adapter.submissions, 1)

    def test_poll_attempts_are_cumulative_success_does_not_exhaust_error_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter([{"status": "queued"}] * 5 + [{"status": "running"}, {"status": "succeeded"}])
            engine = engine_for(Path(tmp), adapter, data)
            for _ in range(7):
                result = self.run_fixture(engine, data)
            self.assertTrue(result["all_succeeded"])
            self.assertEqual(result["jobs"][0]["attempts"]["poll"], 7)
            self.assertEqual(result["jobs"][0]["error_counts"]["poll"], 0)
            self.assertEqual(adapter.submissions, 1)

    def test_poll_budget_includes_retry_requests_and_resume_reuses_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter([SafeRetryError("temporary HTTP error"), {"status": "running"}, {"status": "succeeded"}])
            engine = engine_for(Path(tmp), adapter, data)
            first = self.run_fixture(engine, data, poll_budget=1)
            self.assertEqual(first["jobs"][0]["status"], "submitted")
            self.assertEqual(first["wait_limits"]["polls_used"], 1)
            self.assertTrue(first["wait_limits"]["poll_budget_reached"])
            task_id = first["jobs"][0]["provider_job_id"]
            self.run_fixture(engine, data, poll_budget=1)
            last = self.run_fixture(engine, data, poll_budget=1)
            self.assertTrue(last["all_succeeded"])
            self.assertEqual(last["jobs"][0]["provider_job_id"], task_id)
            self.assertEqual(last["jobs"][0]["attempts"]["poll"], 3)
            self.assertEqual(adapter.submissions, 1)

    def test_expired_wait_deadline_does_not_submit_or_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter()
            engine = engine_for(Path(tmp), adapter, data)
            result = self.run_fixture(engine, data, deadline=time.monotonic() - 1)
            self.assertEqual(result["jobs"][0]["status"], "pending")
            self.assertEqual(adapter.submissions, 0)
            self.assertTrue(result["wait_limits"]["deadline_reached"])

    def test_deadline_after_submitting_checkpoint_before_call_is_pending_not_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter()
            engine = engine_for(Path(tmp), adapter, data)
            real_save = engine.state.save
            def expire_at_checkpoint(job):
                real_save(job)
                if job["status"] == "submitting":
                    engine._active_deadline = time.monotonic() - 1
            with patch.object(engine.state, "save", side_effect=expire_at_checkpoint):
                result = self.run_fixture(engine, data, deadline=time.monotonic() + 60)
            job = result["jobs"][0]
            self.assertEqual(job["status"], "pending")
            self.assertEqual(job["attempts"]["submit"], 0)
            self.assertNotIn("provider_job_id", job)
            self.assertEqual(adapter.submissions, 0)
            self.assertEqual(job["reserved_budget"], "0.194400")
            resumed = self.run_fixture(engine, data)
            self.assertTrue(resumed["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)

    def test_reduced_later_usage_keeps_highest_tokens_and_both_audit_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter([
                {"status": "running", "provider_usage": {"completion_tokens": 200000, "total_tokens": 200010}},
                {"status": "succeeded", "provider_usage": {"completion_tokens": 100000, "total_tokens": 100010}},
            ])
            engine = engine_for(Path(tmp), adapter, data)
            self.run_fixture(engine, data)
            result = self.run_fixture(engine, data)
            job = result["jobs"][0]
            self.assertTrue(result["all_succeeded"])
            self.assertEqual(job["provider_usage"]["completion_tokens"], 200000)
            self.assertEqual(job["provider_usage_latest"]["completion_tokens"], 100000)
            self.assertEqual(job["provider_usage_observations"], [
                {"completion_tokens": 200000, "total_tokens": 200010},
                {"completion_tokens": 100000, "total_tokens": 100010},
            ])
            self.assertEqual(job["calculated_cost"], "0.200000")
            self.assertEqual(job["billing_reconciliation_status"], "pending_final_invoice")

    def test_deadline_reached_after_successful_poll_retains_id_and_defers_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            adapter = UsageAdapter()
            engine = engine_for(Path(tmp), adapter, data)
            def completed_after_deadline(provider_job_id):
                engine._active_deadline = time.monotonic() - 1
                return {"status": "succeeded"}
            with patch.object(adapter, "poll", side_effect=completed_after_deadline):
                first = self.run_fixture(engine, data, deadline=time.monotonic() + 60)
            self.assertEqual(first["jobs"][0]["status"], "submitted")
            self.assertEqual(adapter.downloads, 0)
            self.assertTrue(first["wait_limits"]["deadline_reached"])
            second = self.run_fixture(engine, data)
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(adapter.downloads, 1)

    def test_live_requires_explicit_sound_mode_and_hashes_each_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = board()
            engine = engine_for(Path(tmp), UsageAdapter(), data)
            hashes = []
            for mode in ("model", "dub", "silent"):
                data["sound_mode"] = mode
                plan = engine.plan(data)[0]
                hashes.append(plan["request_hash"])
                self.assertEqual(plan["request"]["generate_audio"], mode == "model")
            self.assertEqual(len(set(hashes)), 3)
            del data["sound_mode"]
            with self.assertRaisesRegex(EngineError, "explicit sound_mode"):
                engine.plan(data)


class ArkUsageContractTests(unittest.TestCase):
    def test_http_deadline_shortens_timeout_and_blocks_expired_request_without_network(self):
        class FakeOpener:
            def __init__(self):
                self.timeouts = []
            def open(self, request, timeout):
                self.timeouts.append(timeout)
                return io.BytesIO(b'{"status":"queued"}')
        opener = FakeOpener()
        transport = HttpTransport(opener=opener)
        transport.deadline = 50
        with patch("short_drama.providers.ark.time.monotonic", return_value=40):
            self.assertEqual(transport.request("GET", "https://example.invalid/fake", {}), {"status": "queued"})
        self.assertEqual(opener.timeouts, [10])
        with patch("short_drama.providers.ark.time.monotonic", return_value=60):
            with self.assertRaises(SafeRetryError):
                transport.request("GET", "https://example.invalid/fake", {})
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "uncreated.mp4"
                with self.assertRaises(SafeRetryError):
                    transport.download("https://cdn.volces.com/fake.mp4", target)
                self.assertFalse(target.exists())
        self.assertEqual(opener.timeouts, [10])

    @patch.dict(os.environ, {"ARK_API_KEY": "fake-test-key"})
    def test_poll_preserves_safe_usage_model_and_output_fields_without_raw_secret_fields(self):
        class FakeTransport:
            def request(self, *args):
                return {"id": "public-fixture-task", "status": "succeeded", "model": "doubao-seedance-2-5-260628",
                        "resolution": "1080p", "duration": 4, "framespersecond": 24, "generate_audio": True,
                        "usage": {"completion_tokens": 200000, "total_tokens": 200000, "secret": "must-not-persist"},
                        "content": {"video_url": "https://cdn.volces.com/public-fixture.mp4"}, "api_key": "must-not-persist"}
        result = ArkAdapter("doubao-seedance-2-5-260628", FakeTransport()).poll("public-fixture-task")
        self.assertEqual(result["provider_usage"]["completion_tokens"], 200000)
        self.assertEqual(result["provider_task_metadata"]["framespersecond"], 24)
        self.assertNotIn("must-not-persist", json.dumps(result))

    @patch.dict(os.environ, {"ARK_API_KEY": "fake-test-key"})
    def test_submit_sets_generate_audio_for_all_explicit_modes_and_rejects_disagreement(self):
        class FakeTransport:
            def __init__(self):
                self.bodies = []
            def request(self, method, url, headers, body=None):
                self.bodies.append(body)
                return {"id": "public-fixture-task"}
        transport = FakeTransport()
        adapter = ArkAdapter("doubao-seedance-2-5-260628", transport)
        request = {"video_prompt": "public fixture", "generation_duration_seconds": 4, "target": {"width": 1080, "height": 1920}}
        for mode in ("model", "dub", "silent"):
            adapter.submit({**request, "sound_mode": mode, "generate_audio": mode == "model"}, "hash")
        self.assertEqual([body["generate_audio"] for body in transport.bodies], [True, False, False])
        with self.assertRaises(ProviderError):
            adapter.submit({**request, "sound_mode": "model", "generate_audio": False}, "hash")
