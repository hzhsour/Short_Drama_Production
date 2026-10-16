"""Local technical fixtures, explicitly not AI generated drama footage."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import ProviderError


class MockAdapter:
    provider_id = "mock"
    model_id = "local-ffmpeg-technical-placeholder-v1"
    paid = False
    api_key_env = None

    def submit(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return {"provider_job_id": "mock-" + idempotency_key, "status": "submitted"}

    def poll(self, provider_job_id: str) -> dict[str, Any]:
        return {"provider_job_id": provider_job_id, "status": "succeeded", "technical_mock": True}

    def download(self, result: dict[str, Any], destination: Path) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ProviderError("Mock video requires local FFmpeg on PATH")
        request = result["request"]
        target = request["target"]
        colour = hashlib.sha256(request["shot_id"].encode()).hexdigest()[:6]
        with tempfile.TemporaryDirectory(prefix="mock-label-", dir=destination.parent) as temporary:
            label = Path(temporary) / "label.txt"
            label.write_text("TECHNICAL MOCK\nNOT AI STORY FOOTAGE", encoding="utf-8")
            # Only controlled filesystem text enters drawtext, never untrusted prompts.
            command = [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                "-f", "lavfi", "-i", f"color=c=0x{colour}:s={target['width']}x{target['height']}:r={target['fps']}",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf", f"drawtext=textfile={label}:fontcolor=white:fontsize=42:x=(w-tw)/2:y=(h-th)/2",
                "-frames:v", str(request["duration_frames"]), "-r", str(target["fps"]),
                "-t", str(request["duration_seconds"]), "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-movflags", "+faststart",
                "-metadata", "comment=TECHNICAL MOCK; NOT AI GENERATED DRAMA", str(destination),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=300)
