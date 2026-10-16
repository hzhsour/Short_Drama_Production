"""Local signal-level media analysis; no ASR, semantic model, or upload."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .media import probe_media


def _ffmpeg_analysis(source: str, options: list[str]) -> str:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("缺少本地依赖: ffmpeg")
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", source, *options, "-f", "null", "-"], capture_output=True, text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("本地媒体分析超时 (180s)") from error
    if result.returncode:
        raise RuntimeError(f"本地媒体分析失败: {result.stderr[-3000:].strip()}")
    return result.stderr


def analyze_video(path: str | Path, detect_silence: bool = False, detect_scenes: bool = False) -> dict[str, Any]:
    """Return metadata, optional -35 dB/0.3 s silence and 0.30 cut candidates.

    Scene candidates are pixel-change scores, not semantic shot recognition.
    This function never edits the media or invokes video-use/ElevenLabs.
    """
    if not isinstance(detect_silence, bool) or not isinstance(detect_scenes, bool):
        raise ValueError("静音/场景检测开关须为布尔值")
    metadata = probe_media(path)
    videos = [item for item in metadata["streams"] if item.get("codec_type") == "video"]
    audios = [item for item in metadata["streams"] if item.get("codec_type") == "audio"]
    if not videos:
        raise ValueError("本地视频分析需要视频流")
    raw_duration = metadata["format"].get("duration") or videos[0].get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        duration = None
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        duration = None
    result: dict[str, Any] = {
        "provider": "local_ffmpeg", "external_api_called": False, "modified_source": False,
        "probe": metadata, "duration_seconds": duration,
        "silence": {"status": "not_requested", "segments": []},
        "scenes": {"status": "not_requested", "cut_candidates_seconds": []},
        "capabilities": {"metadata": True, "signal_silence_detection": True, "pixel_change_scene_candidates": True, "asr": False, "semantic_shot_recognition": False, "character_identity_recognition": False, "automatic_editing": False},
        "optional_providers": {"video-use": {"enabled": False, "reason": "尚未接入外部分析API；不接管Remotion时间线"}},
    }
    if detect_silence:
        result["silence"].update({"noise_threshold_db": -35, "minimum_duration_seconds": 0.3})
        if not audios:
            result["silence"]["status"] = "unavailable_no_audio"
        else:
            logs = _ffmpeg_analysis(metadata["path"], ["-vn", "-map", "0:a:0", "-af", "silencedetect=noise=-35dB:d=0.3"])
            segments = []
            start = None
            for match in re.finditer(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)", logs):
                kind, raw = match.groups()
                instant = max(0.0, float(raw))
                if kind == "start":
                    start = instant
                elif start is not None:
                    segments.append({"start_seconds": start, "end_seconds": instant, "duration_seconds": max(0.0, instant - start)})
                    start = None
            if start is not None and duration is not None:
                segments.append({"start_seconds": start, "end_seconds": duration, "duration_seconds": max(0.0, duration - start)})
            result["silence"].update({"status": "completed", "segments": segments})
    if detect_scenes:
        logs = _ffmpeg_analysis(metadata["path"], ["-an", "-map", "0:v:0", "-vf", "select=gt(scene\\,0.30),showinfo", "-fps_mode", "vfr"])
        cuts = sorted({float(value) for value in re.findall(r"pts_time:(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)", logs) if float(value) > 0 and (duration is None or float(value) < duration)})
        result["scenes"].update({"status": "completed", "threshold": 0.30, "cut_candidates_seconds": cuts, "interpretation": "仅像素变化候选，渐变、闪光、运动可能误报；不代表语义镜头边界"})
    return result
