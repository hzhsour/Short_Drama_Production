"""Storyboard → resumable provider tasks → verified immutable local media.

The default is an entirely offline technical Mock. Live authorization is external
input, bound to exact request hashes; this module never creates approvals.
"""

from __future__ import annotations

import hashlib
import copy
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any

from .providers import MockAdapter, ProviderError, SafeRetryError, SubmissionUnknownError, VideoAdapter
from .providers.ark import ArkAdapter, UnavailableAdapter
from .state import StateError, StateStore
from .storage import ArtifactStorage, LocalStorage, StorageError, sha256_file


class EngineError(RuntimeError):
    pass


class LiveBlockedError(EngineError):
    pass


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def request_identity(request: dict[str, Any]) -> dict[str, Any]:
    """Exclude machine-local roots while retaining reference content/semantics.

    The persisted request still contains its original absolute source locations.
    Request hashes and approvals identify the same relative reference and bytes
    when a production workspace is explicitly restored on another cloud mount.
    """
    identity = copy.deepcopy(request)
    for reference in identity.get("reference_images", []):
        if "relative_path" in reference:
            reference["path"] = reference.pop("relative_path")
    return identity


def positive_decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise LiveBlockedError(f"{name} must be an explicit finite nonnegative amount") from None
    if not result.is_finite() or result < 0:
        raise LiveBlockedError(f"{name} must be an explicit finite nonnegative amount")
    return result


def _unexpired(value: Any, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed <= datetime.now(timezone.utc):
            raise ValueError
    except (AttributeError, ValueError, TypeError):
        raise LiveBlockedError(f"{label} must contain a future timestamp with timezone") from None


def probe_video(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise EngineError("local FFmpeg and FFprobe are required for artifact quality checks")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video:
        raise EngineError("downloaded artifact has no video stream")
    target = request["target"]
    if (video.get("width"), video.get("height")) != (target["width"], target["height"]):
        raise EngineError("downloaded artifact resolution differs from the generation request")
    duration = float(video.get("duration", data.get("format", {}).get("duration", 0)))
    if not math.isfinite(duration) or duration + 0.001 < request["duration_seconds"]:
        raise EngineError("downloaded artifact is shorter than the editorial shot")
    rate = video.get("avg_frame_rate", "0/1")
    numerator, denominator = rate.split("/")
    fps = float(numerator) / float(denominator) if float(denominator) else 0
    expected_fps = request.get("generation_fps", target["fps"])
    if abs(fps - expected_fps) > 0.05:
        raise EngineError("downloaded artifact frame rate differs from the model generation specification")
    # Decode every frame, not merely a container/header check.
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, check=True, timeout=300)
    return {
        "width": video["width"], "height": video["height"], "fps": fps,
        "duration_seconds": duration, "video_codec": video.get("codec_name"),
        "audio_present": any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])),
        "decode_checked": True,
    }


class VideoEngine:
    def __init__(
        self, workspace: Path, mode: str = "mock", provider: str = "mock", adapter: VideoAdapter | None = None,
        *, storage_root: Path | None = None, reference_root: Path | None = None,
        model_config: dict[str, Any] | None = None, approval_file: Path | None = None,
        budgets: dict[str, Any] | None = None, max_retries: int = 2,
        storage: ArtifactStorage | None = None,
    ):
        if mode not in {"mock", "live"}:
            raise ValueError("mode must be mock or live")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.reference_root = Path(reference_root or self.workspace).resolve()
        self.mode, self.provider, self.max_retries = mode, provider, max_retries
        self.model_config = model_config or self._load_catalog_entry(provider)
        self.approval_file = Path(approval_file) if approval_file else None
        self.budgets = budgets or {}
        if adapter is not None:
            self.adapter = adapter
        elif provider == "mock":
            self.adapter = MockAdapter()
        elif provider in {"volcengine-seedance-2.5", "volcengine-seedance-2.0", "volcengine-ark"} and self.model_config.get("model_id"):
            self.adapter = ArkAdapter(self.model_config["model_id"])
        else:
            self.adapter = UnavailableAdapter(provider)
        self.storage = storage or LocalStorage(storage_root or self.workspace / "artifacts" / "video")
        self.state = StateStore(self.workspace / "state" / "video-jobs.sqlite3")
        self.owner = uuid.uuid4().hex
        # SQLite coordinates distinct instances/processes. One instance shares
        # its lease owner, so its own mutating operations must also be serialized.
        self._operation_lock = threading.Lock()

    @property
    def ledger_id(self) -> str:
        return self.state.ledger_id

    @staticmethod
    def _load_catalog_entry(provider: str) -> dict[str, Any]:
        path = Path(__file__).resolve().parents[2] / "config" / "providers.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")).get("providers", {}).get(provider, {})

    def _references(self, shot: dict[str, Any]) -> list[dict[str, Any]]:
        references = shot.get("reference_images", [])
        if not isinstance(references, list):
            raise EngineError("reference_images must be a list")
        normalized = []
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                raise EngineError("reference_images entries require path and type")
            if reference.get("type") not in {"character", "scene", "location", "style", "first_frame", "last_frame", "reference_image"}:
                raise EngineError("reference_images.type is unsupported")
            path = Path(reference["path"])
            absolute = (self.reference_root / path).resolve() if not path.is_absolute() else path.resolve()
            if not absolute.is_relative_to(self.reference_root) or not absolute.is_file():
                raise EngineError("reference image is missing or outside the configured reference root")
            item = {
                "path": str(absolute), "type": reference["type"], "sha256": sha256_file(absolute),
                "relative_path": absolute.relative_to(self.reference_root).as_posix(),
                "character_id": reference.get("character_id"),
            }
            if reference.get("url") is not None:
                item["url"] = reference["url"]
            normalized.append(item)
        return normalized

    def _runtime_request(self, request: dict[str, Any]) -> dict[str, Any]:
        runtime = copy.deepcopy(request)
        for reference in runtime.get("reference_images", []):
            if "relative_path" not in reference:
                continue
            local = (self.reference_root / reference["relative_path"]).resolve()
            if not local.is_relative_to(self.reference_root) or not local.is_file() or sha256_file(local) != reference["sha256"]:
                raise EngineError("restored reference is missing or differs from the approved content hash")
            reference["path"] = str(local)
        return runtime

    def _estimate(self, request: dict[str, Any]) -> tuple[str | None, str | None, str]:
        if not self.adapter.paid:
            return "0", "CNY", "local technical fixture; no generation API used"
        pricing = self.model_config.get("pricing", {})
        currency = pricing.get("currency")
        if request.get("reference_videos") or pricing.get("status") in {None, "unknown"}:
            return None, currency, "unknown official price or unsupported input-video minimum billing"
        try:
            if pricing.get("unit") == "million_output_tokens":
                if pricing.get("estimate_supported_scope") != "no_input_video_standard_generation_only":
                    return None, currency, "pricing scope is not verified for this request"
                target = request["target"]
                if (target["width"], target["height"]) != (1080, 1920):
                    return None, currency, "only the verified 1080p portrait price estimate is implemented"
                rate = positive_decimal(pricing["rates"]["1080p"]["without_input_video"], "token price")
                tokens = Decimal(str(request["generation_duration_seconds"])) * target["width"] * target["height"] * request["generation_fps"] / 1024
                amount = tokens * rate / 1000000
            elif pricing.get("unit") == "second" and pricing.get("per_second") is not None:
                amount = positive_decimal(pricing["per_second"], "per-second price") * Decimal(str(request["generation_duration_seconds"]))
            else:
                return None, currency, "unknown or unsupported official billing unit"
            return str(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)), currency, "estimate from configured official price; billing is not a guaranteed cap"
        except (KeyError, TypeError, LiveBlockedError):
            return None, currency, "incomplete verified pricing configuration"

    def plan(self, storyboard: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan only: no requests, video generation, reference upload, or approval creation."""
        episode_id = storyboard.get("episode_id")
        if not isinstance(episode_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", episode_id):
            raise EngineError("episode_id must be a safe nonempty identifier")
        fps = storyboard.get("fps", 30)
        if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
            raise EngineError("storyboard fps must be an integer from 1 to 120")
        shots = storyboard.get("shots")
        if not isinstance(shots, list):
            raise EngineError("storyboard shots must be a list")
        target = storyboard.get("target_resolution", storyboard.get("resolution", {"width": 1080, "height": 1920}))
        if not isinstance(target, dict) or any(isinstance(target.get(key), bool) or not isinstance(target.get(key), int) or target[key] <= 0 or target[key] % 2 for key in ("width", "height")):
            raise EngineError("resolution requires positive even integer width and height")
        if target["width"] * target["height"] > 4096 * 4096:
            raise EngineError("generation dimensions exceed the local safety limit")
        seen = set()
        jobs = []
        for shot in shots:
            if not isinstance(shot, dict):
                raise EngineError("each shot must be an object")
            shot_id = shot.get("shot_id")
            if not isinstance(shot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", shot_id) or shot_id in seen:
                raise EngineError("shot IDs must be unique safe nonempty identifiers")
            seen.add(shot_id)
            frames = shot.get("duration_frames")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0 or frames > fps * 600:
                raise EngineError("shot duration_frames must be positive and at most ten minutes")
            duration = frames / fps
            generation_duration = duration
            if self.adapter.paid:
                generation_duration = max(self.model_config.get("capabilities", {}).get("min_duration_seconds", 4), math.ceil(duration))
                maximum = self.model_config.get("capabilities", {}).get("max_duration_seconds", 15)
                if generation_duration > maximum:
                    raise EngineError("shot exceeds provider duration; split the storyboard before generation")
            request: dict[str, Any] = {
                "schema_version": 1, "episode_id": episode_id, "shot_id": shot_id,
                "provider": self.provider, "adapter_provider": self.adapter.provider_id, "model_id": self.adapter.model_id,
                "mode": self.mode, "scene_id": shot.get("scene_id"), "characters": shot.get("characters", []),
                "location": shot.get("location"), "action": shot.get("action"), "framing": shot.get("framing"),
                "camera_move": shot.get("camera_move"), "image_prompt": shot.get("image_prompt", ""),
                "video_prompt": shot.get("video_prompt", ""), "audio": shot.get("audio", []),
                "dialogue": shot.get("dialogue", []), "continuity_refs": shot.get("continuity_refs", []),
                "reference_images": self._references(shot), "reference_videos": shot.get("reference_videos", []),
                "duration_frames": frames, "duration_seconds": duration,
                "generation_duration_seconds": generation_duration,
                "generation_fps": self.model_config.get("capabilities", {}).get("frame_rate", 24) if self.adapter.paid else fps,
                "target": {"width": target["width"], "height": target["height"], "fps": fps},
            }
            if self.adapter.paid:
                # A refreshed quote changes the request identity and invalidates
                # approvals issued for a previous price/billing configuration.
                request["pricing_context_hash"] = canonical_hash(self.model_config.get("pricing", {}))
            if not isinstance(request["video_prompt"], str):
                raise EngineError("video_prompt must be text")
            request_hash = canonical_hash(request_identity(request))
            estimate, currency, cost_reason = self._estimate(request)
            jobs.append({
                "job_key": f"{episode_id}:{shot_id}:{request_hash[:16]}", "request_hash": request_hash,
                "episode_id": episode_id, "shot_id": shot_id, "status": "pending", "request": request,
                "estimated_cost": estimate, "currency": currency, "cost_reason": cost_reason,
                "model_selection_reason": self.model_config.get("reason") or (
                    "default offline technical fixture validates the pipeline" if not self.adapter.paid
                    else "explicit provider selection using an exact documented model; live success is unverified"
                ),
                "provenance": {
                    "provider": self.provider, "model_id": self.adapter.model_id,
                    "verification_status": self.model_config.get("verification_status", "local_mock"),
                    "sources": self.model_config.get("sources", []),
                    "pricing": self.model_config.get("pricing", {"status": "local_mock"}),
                },
                "attempts": {"submit": 0, "poll": 0, "download": 0}, "artifact": None,
            })
        return jobs

    def _authorize(self, plans: list[dict[str, Any]]) -> tuple[dict[str, Decimal], str]:
        if self.mode == "mock":
            if self.adapter.paid:
                raise LiveBlockedError("paid adapters are forbidden in Mock mode")
            return {}, "CNY"
        if not self.adapter.paid:
            raise LiveBlockedError("Live mode requires a configured paid adapter; choose Mock mode for local fixtures")
        config = self.model_config
        if config.get("live_enabled") is not True or config.get("verification_status") != "official_documentation_verified":
            raise LiveBlockedError("officially verified model configuration and explicit live_enabled are required")
        if config.get("model_id") != self.adapter.model_id:
            raise LiveBlockedError("configured model does not match the selected adapter")
        if config.get("activation_verified_for_this_account") is not True:
            raise LiveBlockedError("provider account/model activation has not been verified")
        api_env = self.adapter.api_key_env
        if not api_env or not os.environ.get(api_env):
            raise LiveBlockedError("the provider API key is not configured")
        pricing = config.get("pricing", {})
        # Status queries/downloads for already accepted provider tasks never
        # create generation charges. An expired generation quote/approval must
        # not prevent recovery of those paid tasks. Identity/config/key gates
        # above still apply, and only a new submission may reserve new budget.
        if not plans:
            return {}, pricing.get("currency", "CNY")
        if pricing.get("status") != "verified_live_quote" or not pricing.get("source_url"):
            raise LiveBlockedError("a current verified_live_quote is required; published snapshots/unknown prices block Live")
        _unexpired(pricing.get("valid_until"), "live price quote")
        if not self.approval_file or not self.approval_file.is_file():
            raise LiveBlockedError("explicit external user approval file is required")
        try:
            approval = json.loads(self.approval_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise LiveBlockedError("approval file could not be read") from None
        if approval.get("approved") is not True or not isinstance(approval.get("approval_id"), str) or not approval["approval_id"].strip():
            raise LiveBlockedError("approval must contain approved=true and an external approval_id")
        _unexpired(approval.get("expires_at"), "approval")
        if approval.get("provider") != self.provider or approval.get("model_id") != self.adapter.model_id:
            raise LiveBlockedError("approval provider/model does not match the concrete request")
        hashes = approval.get("request_hashes")
        if not isinstance(hashes, list) or any(job["request_hash"] not in hashes for job in plans):
            raise LiveBlockedError("approval must explicitly include every exact request_hash")
        currency = pricing.get("currency")
        if not currency or approval.get("currency") != currency or self.budgets.get("currency") != currency:
            raise LiveBlockedError("approval, model pricing, and budgets must use one explicit currency")
        limits = {}
        for key in ("per_task", "per_episode", "project"):
            limits[key] = min(positive_decimal(self.budgets.get(key), f"budget.{key}"), positive_decimal(approval.get("limits", {}).get(key), f"approval.limits.{key}"))
        costs = []
        for job in plans:
            if job["estimated_cost"] is None or job["currency"] != currency:
                raise LiveBlockedError("unknown price or unsupported billing scope blocks Live submission")
            cost = positive_decimal(job["estimated_cost"], "estimated cost")
            if cost > limits["per_task"]:
                raise LiveBlockedError("per-task budget limit exceeded")
            costs.append(cost)
        if sum(costs, Decimal(0)) > limits["per_episode"] or sum(costs, Decimal(0)) > limits["project"]:
            raise LiveBlockedError("episode/project estimated cost exceeds approved budget")
        # Approval ID is provenance, not a bearer credential.
        for job in plans:
            job["approval_id"] = approval["approval_id"]
        return limits, currency

    def _error_text(self, error: Exception) -> str:
        text = f"{type(error).__name__}: {error}"
        api_env = self.adapter.api_key_env
        if api_env and os.environ.get(api_env):
            text = text.replace(os.environ[api_env], "[REDACTED]")
        return text[:1000]

    def _call(self, job: dict[str, Any], phase: str, operation: Any) -> Any:
        while job["attempts"][phase] < self.max_retries + 1:
            if not self.state.claim(job["job_key"], self.owner):
                raise EngineError("job lease belongs to another worker; no provider request was made")
            job["attempts"][phase] += 1
            self.state.save(job)
            try:
                return operation()
            except SafeRetryError as error:
                job["last_error"] = self._error_text(error)
                self.state.save(job)
                if job["attempts"][phase] >= self.max_retries + 1:
                    raise
        raise ProviderError(f"{phase} retry limit exhausted; operator review required")

    def _execute(self, job: dict[str, Any], limits: dict[str, Decimal], currency: str) -> None:
        if job["status"] in {"succeeded", "artifact_invalid"}:
            if job.get("artifact") and self.storage.verify(job["artifact"]):
                job["status"] = "succeeded"
                self.state.save(job)
                return
            job["status"] = "artifact_invalid"
            job["last_error"] = "completed artifact is missing or has a checksum mismatch; not silently skipped"
            self.state.save(job)
            self.state.event(job["job_key"], "artifact_invalid")
            # A provider task is reused for downloads; never pay for regeneration.
            if not job.get("provider_job_id"):
                return
            job["attempts"]["download"] = 0
            job["attempts"]["poll"] = 0
            job["status"] = "submitted"
        if job["status"] in {"submission_unknown", "failed"}:
            return
        if job["status"] == "submitting" and not job.get("provider_job_id"):
            job["status"] = "submission_unknown"
            job["last_error"] = "interrupted during submit; reconcile provider console before any new generation"
            self.state.save(job)
            return
        try:
            if not job.get("provider_job_id"):
                if self.mode == "live":
                    # A batch can outlive the initial approval/quote. Recheck
                    # immediately before each potentially billable submission.
                    limits, currency = self._authorize([job])
                    self.state.reserve(job["job_key"], job["episode_id"], currency, Decimal(job["estimated_cost"]), limits["per_task"], limits["per_episode"], limits["project"])
                job["status"] = "submitting"
                self.state.save(job)
                try:
                    submitted = self._call(job, "submit", lambda: self.adapter.submit(self._runtime_request(job["request"]), job["request_hash"]))
                except SafeRetryError:
                    job["status"] = "failed"
                    raise
                except Exception:
                    job["status"] = "submission_unknown"
                    raise
                if not isinstance(submitted.get("provider_job_id"), str) or not submitted["provider_job_id"]:
                    job["status"] = "submission_unknown"
                    raise SubmissionUnknownError("provider returned no task ID")
                job["provider_job_id"] = submitted["provider_job_id"]
                job["status"] = "submitted"
                self.state.save(job)
                self.state.event(job["job_key"], "submitted")
            result = self._call(job, "poll", lambda: self.adapter.poll(job["provider_job_id"]))
            status = result.get("status")
            if status in {"queued", "pending", "submitted", "running"}:
                job["status"] = "running" if status == "running" else "submitted"
                # Pending is a successful status check, not a failure/retry. A later
                # invocation can poll again without exhausting the error budget.
                job["attempts"]["poll"] = 0
                self.state.save(job)
                return
            if status != "succeeded":
                job["status"] = "failed"
                raise ProviderError("provider task failed/cancelled/expired or returned an unknown status")
            job["status"] = "downloading"
            self.state.save(job)
            temporary_root = self.workspace / "tmp"
            temporary_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="video-", dir=temporary_root) as directory:
                download_path = Path(directory) / "download.mp4"
                result["request"] = self._runtime_request(job["request"])

                def download() -> None:
                    download_path.unlink(missing_ok=True)
                    self.adapter.download(result, download_path)

                self._call(job, "download", download)
                quality = probe_video(download_path, job["request"])
                key = f"{job['episode_id']}/{job['shot_id']}/{job['request_hash']}.mp4"
                # If stored bytes were modified, preserve them as evidence and put
                # recovered bytes under a fresh immutable key.
                if job.get("artifact") and not self.storage.verify(job["artifact"]):
                    key = f"{job['episode_id']}/{job['shot_id']}/{job['request_hash']}-recovered-{uuid.uuid4().hex[:8]}.mp4"
                artifact = self.storage.put(download_path, key)
                artifact.update({"quality": quality, "technical_mock": self.mode == "mock", "human_review": "pending"})
                job["artifact"] = artifact
            job["status"] = "succeeded"
            job.pop("last_error", None)
            self.state.save(job)
            self.state.event(job["job_key"], "succeeded", json.dumps({"key": artifact["key"], "sha256": artifact["sha256"]}))
        except Exception as error:
            job["last_error"] = self._error_text(error)
            if isinstance(error, (LiveBlockedError, StateError)):
                job["status"] = "blocked"
            elif job["status"] not in {"submission_unknown", "failed"}:
                # The retained provider ID permits only poll/download recovery.
                # Retry counts persist and are never automatically reset here.
                job["status"] = "failed" if not job.get("provider_job_id") else "retry_exhausted" if any(value >= self.max_retries + 1 for phase, value in job["attempts"].items() if phase != "submit") else "submitted"
            self.state.save(job)
            self.state.event(job["job_key"], "error", job["last_error"])

    def run(self, storyboard: dict[str, Any], max_jobs: int | None = None) -> dict[str, Any]:
        with self._operation_lock:
            return self._run_unlocked(storyboard, max_jobs)

    def _run_unlocked(self, storyboard: dict[str, Any], max_jobs: int | None = None) -> dict[str, Any]:
        if max_jobs is not None and (isinstance(max_jobs, bool) or not isinstance(max_jobs, int) or max_jobs < 0):
            raise ValueError("max_jobs must be a nonnegative integer")
        plans = self.plan(storyboard)
        authorize_plans = plans
        if self.mode == "live":
            authorize_plans = []
            for plan in plans:
                existing = self.state.get(plan["job_key"])
                if not existing or (not existing.get("provider_job_id") and existing["status"] not in {"failed", "submission_unknown", "submitting"}):
                    authorize_plans.append(plan)
        limits, currency = self._authorize(authorize_plans)
        for job in plans:
            self.state.ensure(job)
        processed = 0
        for plan in plans:
            if max_jobs is not None and processed >= max_jobs:
                break
            if not self.state.claim(plan["job_key"], self.owner):
                continue
            try:
                job = self.state.get(plan["job_key"])
                assert job is not None
                if plan.get("approval_id"):
                    # Update only after ownership and a fresh read; writing a
                    # stale pre-claim payload can roll a concurrent worker back
                    # to pending and cause duplicate paid submissions.
                    job["approval_id"] = plan["approval_id"]
                    self.state.save(job)
                if job["status"] == "succeeded" and job.get("artifact") and self.storage.verify(job["artifact"]):
                    continue
                processed += 1
                self._execute(job, limits, currency)
            finally:
                self.state.release(plan["job_key"], self.owner)
        jobs = [self.state.get(plan["job_key"]) for plan in plans]
        known_costs = [Decimal(plan["estimated_cost"]) for plan in plans if plan["estimated_cost"] is not None]
        return {
            "episode_id": storyboard["episode_id"], "mode": self.mode, "provider": self.provider,
            "technical_mock": self.mode == "mock", "jobs": jobs,
            "estimated_cost": str(sum(known_costs, Decimal(0))) if len(known_costs) == len(plans) else None,
            "currency": currency, "reserved_project_cost": str(self.state.reserved_total(currency)),
            "all_succeeded": all(job and job["status"] == "succeeded" for job in jobs),
            "state_path": str(self.state.path),
            "ledger_id": self.state.ledger_id,
        }

    def status(self) -> list[dict[str, Any]]:
        jobs = self.state.list_jobs()
        for job in jobs:
            if job["status"] == "succeeded" and (not job.get("artifact") or not self.storage.verify(job["artifact"])):
                job["status"] = "artifact_invalid"
                job["last_error"] = "completed artifact is missing or has a checksum mismatch; not silently skipped"
        return jobs

    def rebind_storage(self, storage_root: Path) -> list[dict[str, Any]]:
        """Explicitly rebind restored media keys to a new local/mounted root.

        The SQLite state directory must already have been restored separately.
        Every referenced artifact is verified before metadata changes. This does
        not upload, copy, submit, poll, or download any provider task.
        """
        with self._operation_lock:
            return self._rebind_storage_unlocked(storage_root)

    def _rebind_storage_unlocked(self, storage_root: Path) -> list[dict[str, Any]]:
        storage = LocalStorage(storage_root)
        jobs = self.state.list_jobs()
        claimed = []
        try:
            restored = []
            for job in jobs:
                if not job.get("artifact"):
                    continue
                if not self.state.claim(job["job_key"], self.owner):
                    raise EngineError("cannot rebind storage while another worker owns an artifact job")
                claimed.append(job["job_key"])
                latest = self.state.get(job["job_key"])
                assert latest is not None
                latest["artifact"] = storage.rebind(latest["artifact"])
                restored.append(latest)
            for job in restored:
                self.state.save(job)
                self.state.event(job["job_key"], "storage_rebound", str(storage.root))
            self.storage = storage
        finally:
            for key in claimed:
                self.state.release(key, self.owner)
        return self.state.list_jobs()
