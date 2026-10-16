"""Volcengine Ark asynchronous API, disabled until the engine's live checks pass.

Official contract: https://www.volcengine.com/docs/82379/1520757
Only an injected fake transport is used by automated tests. No SDK, uploads, or
credential discovery runs at import time. HTTP submit ambiguity is never retried.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from .base import ProviderError, ProviderUnavailableError, SafeRetryError, SubmissionUnknownError


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def download(self, url: str, destination: Path) -> None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Do not forward auth headers or follow a CDN redirect to a private host.
        return None


class HttpTransport:
    def __init__(self, *, opener: Any = None, max_download_bytes: int = 512 * 1024 * 1024,
                 download_timeout_seconds: float = 180):
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.max_download_bytes = max_download_bytes
        self.download_timeout_seconds = download_timeout_seconds
        self.deadline: float | None = None

    def request(self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
        remaining = 60 if self.deadline is None else self.deadline - time.monotonic()
        if remaining <= 0:
            raise SafeRetryError("local wait deadline reached before HTTP request")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=min(60, remaining)) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Explicit HTTP rejection is known not to have returned a task ID.
            # 5xx and connection failures can follow successful task creation.
            if method == "POST" and error.code == 429:
                raise SafeRetryError("Ark rejected submit with HTTP 429") from None
            if method == "POST" and error.code >= 500:
                raise SubmissionUnknownError("Ark submit outcome unknown; reconcile in provider console") from None
            raise ProviderError(f"Ark HTTP {error.code}") from None
        except (OSError, ValueError) as error:
            if method == "POST":
                raise SubmissionUnknownError("Ark submit response unavailable; reconcile before any resubmission") from None
            raise SafeRetryError("Ark status response unavailable") from None

    def download(self, url: str, destination: Path) -> None:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
                or parsed.port not in {None, 443}
                or not (hostname == "volces.com" or hostname.endswith(".volces.com"))):
            raise ProviderError("Ark downloads require the approved HTTPS volces.com CDN; redirects/private hosts are disabled")
        created = False
        deadline = time.monotonic() + self.download_timeout_seconds
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        if time.monotonic() >= deadline:
            raise SafeRetryError("local wait deadline reached before artifact download")
        try:
            with destination.open("xb") as output:
                created = True
                with self.opener.open(url, timeout=min(30, max(0.001, deadline - time.monotonic()))) as response:
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) > self.max_download_bytes:
                        raise ProviderError("Ark download exceeds the configured byte limit")
                    total = 0
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if self.deadline is not None and deadline == self.deadline:
                                raise SafeRetryError("local wait deadline reached during artifact download")
                            raise ProviderError("Ark download exceeded the total time limit")
                        # read1 makes at most one raw read instead of waiting to
                        # fill 64 KiB while a peer slowly trickles bytes. Tighten
                        # the actual socket deadline for the final partial wait.
                        raw = getattr(getattr(response, "fp", None), "raw", None)
                        sock = getattr(raw, "_sock", None)
                        if sock is not None:
                            sock.settimeout(min(30, remaining))
                        chunk = getattr(response, "read1", response.read)(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > self.max_download_bytes:
                            raise ProviderError("Ark download exceeds the configured byte limit")
                        output.write(chunk)
        except (OSError, ProviderError, ValueError) as error:
            if created:
                destination.unlink(missing_ok=True)
            if isinstance(error, ProviderError):
                raise
            raise SafeRetryError("Ark artifact download failed; generation will not be resubmitted") from None


class ArkAdapter:
    provider_id = "volcengine-ark"
    paid = True
    api_key_env = "ARK_API_KEY"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, model_id: str, transport: Transport | None = None):
        if not model_id:
            raise ValueError("exact verified Ark model ID is required")
        self.model_id = model_id
        self.transport = transport or HttpTransport()

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderUnavailableError("ARK_API_KEY is not configured")
        return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def submit(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        # Ark does not document an idempotency header. The local ledger prevents
        # duplicates; adding an invented idempotency parameter would be unsafe.
        seconds = request["generation_duration_seconds"]
        maximum = 30 if self.model_id == "doubao-seedance-2-5-260628" else 15
        if int(seconds) != seconds or not 4 <= seconds <= maximum:
            raise ProviderError("Ark requires whole model-supported clip durations; use editorial trimming")
        if request.get("reference_videos"):
            raise ProviderError("input-video pricing minimums and editing are not implemented; request was not submitted")
        if (request["target"]["width"], request["target"]["height"]) != (1080, 1920):
            raise ProviderError("this Ark adapter currently implements the verified 1080p portrait profile only")
        content: list[dict[str, Any]] = [{"type": "text", "text": request["video_prompt"]}]
        for reference in request.get("reference_images", []):
            if reference.get("type") in {"first_frame", "last_frame"}:
                raise ProviderError("first/last-frame adaptive output requires a separate validated adapter profile")
            url = reference.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ProviderError("local reference images need separately authorized hosting; automatic upload is disabled")
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
        body = {
            "model": self.model_id, "content": content,
            "ratio": "9:16", "resolution": "1080p", "duration": int(seconds),
        }
        sound_mode = request.get("sound_mode")
        if sound_mode not in {"model", "dub", "silent"}:
            raise ProviderError("Ark requires an explicit sound_mode: model, dub, or silent")
        if request.get("generate_audio") is not (sound_mode == "model"):
            raise ProviderError("generate_audio must agree with the explicit sound_mode")
        body["generate_audio"] = sound_mode == "model"
        response = self.transport.request("POST", self.base_url + "/contents/generations/tasks", self._headers(), body)
        task_id = response.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise SubmissionUnknownError("Ark submit returned no task ID; manual reconciliation is required")
        return {"provider_job_id": task_id, "status": "submitted"}

    def poll(self, provider_job_id: str) -> dict[str, Any]:
        response = self.transport.request(
            "GET", self.base_url + "/contents/generations/tasks/" + urllib.parse.quote(provider_job_id, safe=""), self._headers()
        )
        status = response.get("status")
        if status not in {"queued", "running", "succeeded", "failed", "cancelled", "expired"}:
            raise ProviderError("Ark returned an unknown task status")
        result: dict[str, Any] = {"provider_job_id": provider_job_id, "status": status}
        # Keep only documented accounting/specification fields. Do not persist
        # the raw response, signed URLs outside artifact_url, prompts or headers.
        usage = response.get("usage")
        if isinstance(usage, dict):
            result["provider_usage"] = {
                key: value for key, value in usage.items()
                if key in {"completion_tokens", "total_tokens"}
                and isinstance(value, int) and not isinstance(value, bool) and value >= 0
            }
        metadata: dict[str, Any] = {"task_id": provider_job_id}
        for key in ("id", "model", "resolution", "ratio", "duration", "framespersecond", "generate_audio", "seed", "created_at", "updated_at"):
            value = response.get(key)
            if isinstance(value, (str, int, float, bool)) and (not isinstance(value, str) or len(value) <= 200):
                metadata[key] = value
        result["provider_task_metadata"] = metadata
        if status == "succeeded":
            url = response.get("content", {}).get("video_url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ProviderError("Ark succeeded without an HTTPS video URL")
            result["artifact_url"] = url
        return result

    def download(self, result: dict[str, Any], destination: Path) -> None:
        self.transport.download(result["artifact_url"], destination)


class UnavailableAdapter:
    paid = True
    api_key_env = "ARK_API_KEY"

    def __init__(self, provider: str):
        self.provider_id = provider
        self.model_id = "unconfigured"

    def submit(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        raise ProviderUnavailableError("provider is not configured; use verified exact model configuration and approval")

    def poll(self, provider_job_id: str) -> dict[str, Any]:
        raise ProviderUnavailableError("provider is not configured")

    def download(self, result: dict[str, Any], destination: Path) -> None:
        raise ProviderUnavailableError("provider is not configured")
