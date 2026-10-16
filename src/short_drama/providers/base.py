"""Video provider contract. Submission ambiguity must never cause blind retries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ProviderError(RuntimeError):
    pass


class SafeRetryError(ProviderError):
    """A retry is safe; for submit this proves the request was not accepted."""


class SubmissionUnknownError(ProviderError):
    """The provider may have accepted/charged a request. Reconcile manually."""


class ProviderUnavailableError(ProviderError):
    pass


class VideoAdapter(Protocol):
    provider_id: str
    model_id: str
    paid: bool
    api_key_env: str | None

    def submit(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def poll(self, provider_job_id: str) -> dict[str, Any]: ...

    def download(self, result: dict[str, Any], destination: Path) -> None: ...
