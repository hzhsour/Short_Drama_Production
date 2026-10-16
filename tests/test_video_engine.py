from __future__ import annotations

import json
import io
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from short_drama.providers import MockAdapter, ProviderError, SafeRetryError
from short_drama.providers.ark import ArkAdapter, HttpTransport
from short_drama.video_engine import EngineError, LiveBlockedError, VideoEngine


def storyboard(episode: str = "EP001", shots: int = 1) -> dict:
    return {
        "episode_id": episode, "aspect_ratio": "9:16", "fps": 30,
        "target_resolution": {"width": 80, "height": 144},
        "shots": [{
            "shot_id": f"{episode}-SC01-SH{index:03}", "scene_id": "SC01", "duration_frames": 6,
            "characters": ["CHAR001"], "location": "楼梯间", "action": "抬头", "framing": "近景",
            "camera_move": "固定", "dialogue": [], "audio": [], "image_prompt": "技术测试",
            "video_prompt": "技术测试镜头，非剧情成片", "continuity_refs": [],
        } for index in range(1, shots + 1)],
    }


class CountingAdapter(MockAdapter):
    def __init__(self):
        self.submissions = 0
        self.polls = 0
        self.downloads = 0
        self.pending_once = False
        self.submit_error = None
        self.download_error = None

    def submit(self, request, idempotency_key):
        self.submissions += 1
        if self.submit_error:
            raise self.submit_error
        return super().submit(request, idempotency_key)

    def poll(self, provider_job_id):
        self.polls += 1
        if self.pending_once:
            self.pending_once = False
            return {"status": "running"}
        return super().poll(provider_job_id)

    def download(self, result, destination):
        self.downloads += 1
        if self.download_error:
            raise self.download_error
        return super().download(result, destination)


class FakePaidAdapter(CountingAdapter):
    provider_id = "fake-paid"
    model_id = "fake-model-v1"
    api_key_env = "TEST_VIDEO_API_KEY"
    paid = True


def live_config() -> dict:
    return {
        "verification_status": "official_documentation_verified", "live_enabled": True,
        "activation_verified_for_this_account": True, "model_id": "fake-model-v1",
        "capabilities": {"frame_rate": 30, "min_duration_seconds": 4, "max_duration_seconds": 15},
        "pricing": {"status": "verified_live_quote", "valid_until": "2099-01-01T00:00:00Z",
                    "unit": "second", "per_second": "1", "currency": "CNY", "source_url": "https://example.invalid/test-quote"},
    }


def approved_engine(root: Path, adapter: FakePaidAdapter, data: dict, config=None, project="100") -> VideoEngine:
    approval_file = root / "external-approval.json"
    engine = VideoEngine(root, mode="live", provider="fake", adapter=adapter, model_config=config or live_config(),
                         approval_file=approval_file, budgets={"per_task": "10", "per_episode": "30", "project": project, "currency": "CNY"})
    approval_file.write_text(json.dumps({
        "approved": True, "approval_id": "external-test-approval", "provider": "fake", "model_id": adapter.model_id,
        "request_hashes": [job["request_hash"] for job in engine.plan(data)], "expires_at": "2099-01-01T00:00:00Z", "currency": "CNY",
        "limits": {"per_task": "10", "per_episode": "30", "project": project},
    }), encoding="utf-8")
    return engine


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
class VideoEngineTests(unittest.TestCase):
    def test_mock_media_is_real_decodable_h264_and_restart_does_not_submit_again(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CountingAdapter()
            root = Path(directory)
            engine = VideoEngine(root, adapter=adapter)
            self.assertEqual(engine.plan(storyboard())[0]["estimated_cost"], "0")
            self.assertEqual(adapter.submissions, 0)
            result = engine.run(storyboard())
            self.assertTrue(result["all_succeeded"])
            artifact = result["jobs"][0]["artifact"]
            self.assertTrue(artifact["technical_mock"])
            self.assertEqual(artifact["quality"]["video_codec"], "h264")
            self.assertTrue(artifact["quality"]["decode_checked"])
            self.assertTrue(artifact["quality"]["audio_present"])
            self.assertGreaterEqual(artifact["quality"]["duration_seconds"], 0.2)
            restarted = VideoEngine(root, adapter=adapter)
            self.assertTrue(restarted.run(storyboard())["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(adapter.downloads, 1)

    def test_pending_job_recovers_from_persisted_provider_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            adapter.pending_once = True
            first = VideoEngine(root, adapter=adapter).run(storyboard())
            self.assertEqual(first["jobs"][0]["status"], "running")
            self.assertTrue(VideoEngine(root, adapter=adapter).run(storyboard())["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)

    def test_partial_episode_then_restart_processes_only_unfinished_shots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            first = VideoEngine(root, adapter=adapter).run(storyboard(shots=2), max_jobs=1)
            self.assertEqual([job["status"] for job in first["jobs"]], ["succeeded", "pending"])
            second = VideoEngine(root, adapter=adapter).run(storyboard(shots=2))
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(adapter.submissions, 2)

    def test_missing_and_corrupt_completed_media_recovers_without_new_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            engine = VideoEngine(root, adapter=adapter)
            first = engine.run(storyboard())
            original = Path(first["jobs"][0]["artifact"]["path"])
            original.write_bytes(b"damaged original must remain")
            self.assertEqual(engine.status()[0]["status"], "artifact_invalid")
            recovered = VideoEngine(root, adapter=adapter).run(storyboard())
            self.assertTrue(recovered["all_succeeded"])
            self.assertEqual(original.read_bytes(), b"damaged original must remain")
            self.assertNotEqual(recovered["jobs"][0]["artifact"]["path"], str(original))
            Path(recovered["jobs"][0]["artifact"]["path"]).unlink()
            self.assertTrue(VideoEngine(root, adapter=adapter).run(storyboard())["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)

    def test_ambiguous_or_interrupted_submit_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            adapter.submit_error = TimeoutError("provider might have accepted the request")
            first = VideoEngine(root, adapter=adapter).run(storyboard())
            self.assertEqual(first["jobs"][0]["status"], "submission_unknown")
            adapter.submit_error = None
            second = VideoEngine(root, adapter=adapter).run(storyboard())
            self.assertEqual(second["jobs"][0]["status"], "submission_unknown")
            self.assertEqual(adapter.submissions, 1)
        with tempfile.TemporaryDirectory() as directory:
            engine = VideoEngine(Path(directory), adapter=adapter)
            job = engine.plan(storyboard())[0]
            job["status"] = "submitting"
            engine.state.ensure(job)
            self.assertEqual(engine.run(storyboard())["jobs"][0]["status"], "submission_unknown")
            self.assertEqual(adapter.submissions, 1)

    def test_proven_safe_submit_retries_are_limited_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            adapter.submit_error = SafeRetryError("explicit rejection before task acceptance")
            result = VideoEngine(root, adapter=adapter, max_retries=1).run(storyboard())
            self.assertEqual(result["jobs"][0]["status"], "failed")
            self.assertEqual(adapter.submissions, 2)
            VideoEngine(root, adapter=adapter, max_retries=1).run(storyboard())
            self.assertEqual(adapter.submissions, 2)

    def test_download_retries_never_submit_generation_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            adapter.download_error = SafeRetryError("CDN temporarily unavailable")
            first = VideoEngine(root, adapter=adapter, max_retries=1).run(storyboard())
            self.assertEqual(first["jobs"][0]["status"], "retry_exhausted")
            self.assertEqual(adapter.downloads, 2)
            VideoEngine(root, adapter=adapter, max_retries=1).run(storyboard())
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(adapter.downloads, 2)

    def test_reference_content_changes_request_hash_and_missing_reference_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "character.png"
            reference.write_bytes(b"reference-v1")
            data = storyboard()
            data["shots"][0]["reference_images"] = [{"path": "character.png", "type": "character", "character_id": "CHAR001"}]
            engine = VideoEngine(root)
            first = engine.plan(data)[0]["request_hash"]
            reference.write_bytes(b"reference-v2")
            self.assertNotEqual(engine.plan(data)[0]["request_hash"], first)
            reference.unlink()
            with self.assertRaises(EngineError):
                engine.plan(data)

    def test_restored_cloud_media_can_rebind_without_any_new_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CountingAdapter()
            engine = VideoEngine(root / "workspace", adapter=adapter)
            first = engine.run(storyboard())
            checksum = first["jobs"][0]["artifact"]["sha256"]
            new_mount = root / "new-persistent-mount"
            shutil.copytree(engine.storage.root, new_mount)
            shutil.rmtree(engine.storage.root)
            restored = VideoEngine(root / "workspace", adapter=adapter)
            jobs = restored.rebind_storage(new_mount)
            self.assertEqual(jobs[0]["artifact"]["sha256"], checksum)
            self.assertTrue(Path(jobs[0]["artifact"]["path"]).is_relative_to(new_mount))
            self.assertTrue(restored.run(storyboard())["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)

    def test_reference_root_relocation_preserves_hash_approval_identity_and_completed_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_cloud = root / "old-cloud"
            references = old_cloud / "references"
            (references / "characters").mkdir(parents=True)
            original_reference = references / "characters" / "CHAR001.png"
            original_reference.write_bytes(b"same reference content across cloud mounts")
            data = storyboard()
            data["shots"][0]["reference_images"] = [{"path": "characters/CHAR001.png", "type": "character", "character_id": "CHAR001"}]
            adapter = CountingAdapter()
            original = VideoEngine(old_cloud / "workspace", adapter=adapter, reference_root=references)
            first = original.run(data)
            first_job = first["jobs"][0]
            new_cloud = root / "new-cloud"
            shutil.copytree(old_cloud, new_cloud)
            shutil.rmtree(old_cloud)
            restored = VideoEngine(new_cloud / "workspace", adapter=adapter, reference_root=new_cloud / "references")
            restored.rebind_storage(new_cloud / "workspace" / "artifacts" / "video")
            planned = restored.plan(data)[0]
            self.assertEqual(planned["request_hash"], first_job["request_hash"])
            self.assertNotEqual(planned["request"]["reference_images"][0]["path"], first_job["request"]["reference_images"][0]["path"])
            second = restored.run(data)
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(second["jobs"][0]["job_key"], first_job["job_key"])
            # The recorded original source location remains available for audit.
            self.assertEqual(second["jobs"][0]["request"]["reference_images"][0]["path"], str(original_reference))
            self.assertEqual(adapter.submissions, 1)
            (new_cloud / "references" / "characters" / "CHAR001.png").write_bytes(b"changed reference")
            self.assertNotEqual(restored.plan(data)[0]["request_hash"], first_job["request_hash"])


class LiveSafetyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_paid_accepted_job_with_references_resumes_after_cloud_root_move_without_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_cloud = root / "old-cloud"
            old_workspace = old_cloud / "workspace"
            reference = old_workspace / "characters" / "CHAR001.png"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"approved reference bytes")
            data = storyboard()
            data["shots"][0]["reference_images"] = [{
                "path": "characters/CHAR001.png", "type": "character", "character_id": "CHAR001",
                "url": "https://example.invalid/already-hosted-reference.png",
            }]
            adapter = FakePaidAdapter()
            adapter.pending_once = True
            original = approved_engine(old_workspace, adapter, data)
            first = original.run(data)
            self.assertEqual(first["jobs"][0]["status"], "running")
            new_cloud = root / "new-cloud"
            shutil.copytree(old_cloud, new_cloud)
            shutil.rmtree(old_cloud)
            new_workspace = new_cloud / "workspace"
            restored = VideoEngine(new_workspace, mode="live", provider="fake", adapter=adapter, model_config=live_config())
            restored.rebind_storage(new_workspace / "artifacts" / "video")
            self.assertEqual(restored.plan(data)[0]["request_hash"], first["jobs"][0]["request_hash"])
            result = restored.run(data)
            self.assertTrue(result["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(result["reserved_project_cost"], "4.000000")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_same_engine_instance_serializes_concurrent_runs_without_duplicate_paid_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            both_executing = threading.Barrier(2)
            adapter = FakePaidAdapter()
            data = storyboard()
            engine = approved_engine(root, adapter, data)
            original_execute = engine._execute

            def synchronized_execute(job, limits, currency):
                # The reproduced race requires both workers to hold pending
                # snapshots before either persists "submitting". With the lock
                # the second run cannot enter execution and this times out.
                try:
                    both_executing.wait(timeout=0.5)
                except threading.BrokenBarrierError:
                    pass
                return original_execute(job, limits, currency)

            with patch.object(engine, "_execute", side_effect=synchronized_execute), ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(engine.run, data)
                second = executor.submit(engine.run, data)
                self.assertTrue(first.result(timeout=10)["all_succeeded"])
                self.assertTrue(second.result(timeout=10)["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(engine.state.reserved_total("CNY"), 4)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_approval_expiry_during_batch_blocks_each_later_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval_path = root / "external-approval.json"

            class ExpiringAdapter(FakePaidAdapter):
                def submit(self, request, idempotency_key):
                    result = super().submit(request, idempotency_key)
                    approval = json.loads(approval_path.read_text(encoding="utf-8"))
                    approval["expires_at"] = "2000-01-01T00:00:00Z"
                    approval_path.write_text(json.dumps(approval), encoding="utf-8")
                    return result

            adapter = ExpiringAdapter()
            data = storyboard(shots=2)
            result = approved_engine(root, adapter, data).run(data)
            self.assertEqual([job["status"] for job in result["jobs"]], ["succeeded", "blocked"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(result["reserved_project_cost"], "4.000000")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_competing_worker_completion_cannot_be_rolled_back_by_stale_approval_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = storyboard()
            adapter = FakePaidAdapter()
            adapter.pending_once = True
            worker_a = approved_engine(root, adapter, data)
            worker_b = approved_engine(root, adapter, data)
            original_ensure = worker_b.state.ensure
            raced = False

            def ensure_with_race(job):
                nonlocal raced
                stale = original_ensure(job)
                if not raced:
                    raced = True
                    self.assertEqual(worker_a.run(data)["jobs"][0]["status"], "running")
                return stale

            with patch.object(worker_b.state, "ensure", side_effect=ensure_with_race):
                result = worker_b.run(data)
            self.assertTrue(result["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)

    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "very-long-fake-secret-value"})
    def test_secret_is_redacted_before_log_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = VideoEngine(Path(directory), adapter=FakePaidAdapter())
            message = "x" * 975 + os.environ["TEST_VIDEO_API_KEY"]
            sanitized = engine._error_text(ProviderError(message))
            self.assertNotIn("very-long-fake", sanitized)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg/FFprobe required")
    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_accepted_task_recovery_does_not_require_new_generation_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = storyboard()
            adapter = FakePaidAdapter()
            adapter.pending_once = True
            engine = approved_engine(root, adapter, data)
            first = engine.run(data)
            self.assertEqual(first["jobs"][0]["status"], "running")
            engine.approval_file.unlink()
            restarted = VideoEngine(root, mode="live", provider="fake", adapter=adapter, model_config=live_config())
            second = restarted.run(data)
            self.assertTrue(second["all_succeeded"])
            self.assertEqual(adapter.submissions, 1)
            self.assertEqual(second["reserved_project_cost"], "4.000000")

    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_unapproved_changed_request_unknown_price_disabled_model_and_budget_block_before_submit(self):
        mutations = ("approval", "request", "price", "enabled", "budget", "quote", "account", "currency")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data = storyboard()
                adapter = FakePaidAdapter()
                engine = approved_engine(root, adapter, data)
                if mutation == "approval":
                    engine.approval_file.unlink()
                elif mutation == "request":
                    data["shots"][0]["video_prompt"] = "changed prompt was not approved"
                elif mutation == "price":
                    engine.model_config["pricing"]["status"] = "unknown"
                elif mutation == "enabled":
                    engine.model_config["live_enabled"] = False
                elif mutation == "budget":
                    engine.budgets["per_task"] = "0.01"
                elif mutation == "quote":
                    engine.model_config["pricing"]["valid_until"] = "2000-01-01T00:00:00Z"
                elif mutation == "account":
                    engine.model_config["activation_verified_for_this_account"] = False
                elif mutation == "currency":
                    engine.budgets["currency"] = "USD"
                with self.assertRaises(LiveBlockedError):
                    engine.run(data)
                self.assertEqual(adapter.submissions, 0)

    def test_missing_key_and_paid_adapter_in_mock_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            adapter = FakePaidAdapter()
            engine = approved_engine(root, adapter, storyboard())
            with self.assertRaises(LiveBlockedError):
                engine.run(storyboard())
            with self.assertRaises(LiveBlockedError):
                VideoEngine(root, adapter=adapter).run(storyboard())
            self.assertEqual(adapter.submissions, 0)

    @patch.dict(os.environ, {"TEST_VIDEO_API_KEY": "fake-test-key-not-a-real-secret"})
    def test_failed_paid_submission_keeps_reservation_and_project_limit_blocks_next_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = FakePaidAdapter()
            adapter.submit_error = TimeoutError("uncertain charged outcome")
            first = approved_engine(root, adapter, storyboard(), project="7").run(storyboard())
            self.assertEqual(first["reserved_project_cost"], "4.000000")
            second_data = storyboard("EP002")
            second = approved_engine(root, adapter, second_data, project="7").run(second_data)
            self.assertEqual(second["jobs"][0]["status"], "blocked")
            self.assertIn("budget limit exceeded", second["jobs"][0]["last_error"])
            self.assertEqual(adapter.submissions, 1)

    def test_official_snapshot_estimate_accounts_for_minimum_duration_and_native_fps(self):
        with tempfile.TemporaryDirectory() as directory:
            data = storyboard()
            del data["target_resolution"]
            engine = VideoEngine(Path(directory), mode="live", provider="volcengine-seedance-2.5")
            planned = engine.plan(data)[0]
            self.assertEqual(planned["request"]["generation_duration_seconds"], 4)
            self.assertEqual(planned["request"]["generation_fps"], 24)
            # 4 * 1080 * 1920 * 24 / 1024 * 77 / 1_000_000.
            self.assertEqual(planned["estimated_cost"], "14.968800")
            with self.assertRaises(LiveBlockedError):
                engine.run(data)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.downloads = []

    def request(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if method == "POST":
            return {"id": "fake-provider-task"}
        return {"id": "fake-provider-task", "status": "succeeded", "content": {"video_url": "https://example.invalid/fixture.mp4"}}

    def download(self, url, destination):
        self.downloads.append(url)
        destination.write_bytes(b"fake transport contract only; not video")


class ArkContractTests(unittest.TestCase):
    @patch.dict(os.environ, {"ARK_API_KEY": "fake-test-key"})
    def test_official_submit_poll_download_contract_uses_only_injected_fake_transport(self):
        transport = FakeTransport()
        adapter = ArkAdapter("doubao-seedance-2-5-260628", transport=transport)
        request = {
            "video_prompt": "雨夜楼梯间，技术合同测试", "duration_seconds": 0.2, "generation_duration_seconds": 4,
            "target": {"width": 1080, "height": 1920},
            "reference_images": [{"type": "character", "url": "https://example.invalid/character.png"}],
        }
        submitted = adapter.submit(request, "local-idempotency-hash")
        self.assertEqual(submitted["provider_job_id"], "fake-provider-task")
        method, url, headers, body = transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
        self.assertEqual(headers["Authorization"], "Bearer fake-test-key")
        self.assertEqual(body["model"], "doubao-seedance-2-5-260628")
        self.assertEqual(body["duration"], 4)
        self.assertEqual(body["content"][1]["role"], "reference_image")
        self.assertNotIn("idempotency_key", body)
        result = adapter.poll(submitted["provider_job_id"])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "download.mp4"
            adapter.download(result, destination)
            self.assertTrue(destination.exists())
        self.assertEqual(transport.downloads, ["https://example.invalid/fixture.mp4"])

    @patch.dict(os.environ, {"ARK_API_KEY": "fake-test-key"})
    def test_unsupported_local_upload_and_video_input_are_blocked_without_http(self):
        transport = FakeTransport()
        adapter = ArkAdapter("doubao-seedance-2-5-260628", transport=transport)
        base = {"video_prompt": "test", "generation_duration_seconds": 4, "target": {"width": 1080, "height": 1920}}
        for additions in ({"reference_images": [{"path": "/private.png"}]}, {"reference_videos": [{"url": "https://example.invalid/input.mp4"}]}):
            with self.assertRaises(ProviderError):
                adapter.submit({**base, **additions}, "hash")
        self.assertFalse(transport.calls)


class DownloadTransportTests(unittest.TestCase):
    url = "https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/fixture.mp4"

    def test_existing_destination_is_preserved_and_no_network_request_is_started(self):
        class NeverOpen:
            def open(self, *args, **kwargs):
                raise AssertionError("existing originals must be rejected before networking")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original.mp4"
            target.write_bytes(b"original media")
            with self.assertRaises(SafeRetryError):
                HttpTransport(opener=NeverOpen()).download(self.url, target)
            self.assertEqual(target.read_bytes(), b"original media")

    def test_untrusted_hosts_credentials_ports_and_redirects_cannot_download(self):
        class RedirectResponse:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError(args[0], 302, "redirect forbidden", {}, None)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "download.mp4"
            for url in ("https://127.0.0.1/private", "https://localhost/private", "https://192.168.1.1/private",
                        "https://volces.com.evil.invalid/x", "https://user:password@cdn.volces.com/x", "https://cdn.volces.com:8443/x"):
                with self.subTest(url=url), self.assertRaises(ProviderError):
                    HttpTransport(opener=RedirectResponse()).download(url, target)
                self.assertFalse(target.exists())
            with self.assertRaises(SafeRetryError):
                HttpTransport(opener=RedirectResponse()).download(self.url, target)
            self.assertFalse(target.exists())
            # The production opener itself rejects redirects; no external URL is
            # opened to verify its configured redirect behavior.
            opener = HttpTransport().opener
            handler = next(handler for handler in opener.handlers if isinstance(handler, __import__("urllib.request", fromlist=["HTTPRedirectHandler"]).HTTPRedirectHandler))
            self.assertIsNone(handler.redirect_request(None, None, 302, "redirect", {}, "https://127.0.0.1/private"))

    def test_size_and_total_deadline_limits_remove_only_partial_downloads(self):
        class Response(io.BytesIO):
            headers = {}

        class Opener:
            def open(self, *args, **kwargs):
                return Response(b"123456")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "download.mp4"
            with self.assertRaisesRegex(ProviderError, "byte limit"):
                HttpTransport(opener=Opener(), max_download_bytes=3).download(self.url, target)
            self.assertFalse(target.exists())
            with patch("short_drama.providers.ark.time.monotonic", side_effect=[0, 0, 200]):
                with self.assertRaisesRegex(ProviderError, "time limit"):
                    HttpTransport(opener=Opener(), download_timeout_seconds=180).download(self.url, target)
            self.assertFalse(target.exists())
