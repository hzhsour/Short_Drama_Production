"""Local FFmpeg/ffprobe boundaries, normalization, and delivery checks.

No shell evaluation, remote media, or source-file overwrite is allowed. Machine
checks cannot certify acting, facial identity, dialogue quality, or readable glyphs.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from .timeline import local_media_path, validate_timeline


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    if not shutil.which(args[0]):
        raise RuntimeError(f"缺少本地依赖: {args[0]}")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"本地媒体操作超时 ({timeout}s)") from error
    if result.returncode:
        raise RuntimeError(f"{args[0]} 失败: {result.stderr[-3000:].strip()}")
    return result


def probe_media(path: str | Path) -> dict[str, Any]:
    source = local_media_path(path)
    result = _run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(source)])
    data = json.loads(result.stdout)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(source), "sha256": digest.hexdigest(), "streams": data.get("streams", []), "format": data.get("format", {})}


def normalize_media(
    source: str | Path,
    destination: str | Path,
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    sample_rate: int = 48000,
) -> dict[str, Any]:
    """Decode local H.264/H.265/etc into a new H.264/AAC 48 kHz artifact.

    Preserve framing using scale+pad. Missing source audio receives an explicit
    silent stereo track. Existing originals and destinations are never replaced.
    """
    original = local_media_path(source)
    if (re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", str(destination)) and not re.match(r"^[A-Za-z]:[\\/]", str(destination))) or str(destination).startswith(("//", "\\\\")):
        raise ValueError("输出仅允许本地路径")
    target = Path(destination).expanduser().resolve()
    if target.exists() or target == original:
        raise FileExistsError(f"禁止覆盖源文件或现有输出: {target}")
    if target.suffix.lower() != ".mp4":
        raise ValueError("标准化输出必须为 .mp4")
    if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in (width, height, fps, sample_rate)) or width % 2 or height % 2:
        raise ValueError("宽高须为正偶数，fps/sample_rate 须为正整数")
    metadata = probe_media(original)
    if not any(stream.get("codec_type") == "video" for stream in metadata["streams"]):
        raise ValueError("源媒体没有视频流")
    has_audio = any(stream.get("codec_type") == "audio" for stream in metadata["streams"])
    target.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-protocol_whitelist", "file,pipe", "-i", str(original)]
    if not has_audio:
        args += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={sample_rate}"]
    args += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", str(sample_rate), "-ac", "2", "-af", "aresample=async=1:first_pts=0", "-shortest", "-movflags", "+faststart", str(target)]
    _run(args, timeout=900)
    output = probe_media(target)
    output["source_sha256"] = metadata["sha256"]
    return output


def validate_timeline_media(timeline: dict[str, Any]) -> list[str]:
    """Ensure every staged source exists, matches its hash, and covers its trim.

    Image stills intentionally hold for their shot duration. Video and audio are
    never silently looped or truncated to hide an incomplete generation result.
    """
    errors = []
    cache: dict[str, dict[str, Any]] = {}
    fps = timeline.get("fps", 30)
    sources = [(shot.get("media", {}), shot, "video") for shot in timeline.get("shots", [])]
    sources += [(track, track, "audio") for track in timeline.get("tracks", [])]
    for source, item, wanted in sources:
        try:
            path = str(local_media_path(source.get("path")))
            if path not in cache:
                cache[path] = probe_media(path)
            metadata = cache[path]
            if source.get("sha256") and source["sha256"] != metadata["sha256"]:
                errors.append(f"源素材哈希发生变化: {item.get('shot_id', item.get('id'))}")
            if wanted == "video":
                has_source_audio = any(stream.get("codec_type") == "audio" for stream in metadata["streams"])
                declared = source.get("has_source_audio")
                if isinstance(declared, bool) and declared != has_source_audio:
                    errors.append(f"源音轨实测与时间线 has_source_audio 不一致: {item.get('shot_id')}")
                if source.get("sound_mode") == "model" and not has_source_audio:
                    errors.append(f"model 模式源素材实际没有音轨: {item.get('shot_id')}")
            matching = [stream for stream in metadata["streams"] if stream.get("codec_type") == wanted]
            if not matching:
                errors.append(f"源素材缺少 {wanted} 流: {path}")
                continue
            if source.get("kind") == "image":
                continue
            stream = matching[0]
            seconds = float(stream.get("duration") or metadata["format"].get("duration") or 0)
            required = (item["duration_frames"] + source.get("source_start_frame", 0)) / fps
            if seconds + 1 / fps < required:
                errors.append(f"源素材时长不足: {path} ({seconds:.3f}s < {required:.3f}s)")
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            errors.append(str(error))
    return errors


def qc_video(path: str | Path, timeline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fully decode video+audio and compare delivery specs to the manifest."""
    errors: list[str] = []
    warnings: list[str] = []
    manual_checks = ["人工观看字幕字形、遮挡与可读性", "人工复核人物脸部、服饰和道具一致性", "人工复核剧情连续性、口型同步与听感"]
    try:
        metadata = probe_media(path)
    except (ValueError, RuntimeError, json.JSONDecodeError) as error:
        return {"passed": False, "errors": [str(error)], "warnings": warnings, "manual_checks": manual_checks, "probe": None}
    videos = [stream for stream in metadata["streams"] if stream.get("codec_type") == "video"]
    audios = [stream for stream in metadata["streams"] if stream.get("codec_type") == "audio"]
    if not videos:
        errors.append("输出缺少视频流")
    if not audios:
        errors.append("输出缺少音轨")
    if timeline is not None:
        structure_errors = validate_timeline(timeline)
        if structure_errors:
            return {"passed": False, "errors": errors + structure_errors, "warnings": warnings, "manual_checks": manual_checks, "probe": metadata}
    expected_width = timeline.get("width", 1080) if timeline is not None else 1080
    expected_height = timeline.get("height", 1920) if timeline is not None else 1920
    expected_fps = timeline.get("fps", 30) if timeline is not None else 30
    for video in videos[:1]:
        if (video.get("width"), video.get("height")) != (expected_width, expected_height):
            errors.append(f"分辨率不符: {video.get('width')}x{video.get('height')}")
        try:
            actual_fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
        except (ValueError, ZeroDivisionError):
            actual_fps = 0
        if abs(actual_fps - expected_fps) > 0.01:
            errors.append(f"帧率不符: {actual_fps}, 预期 {expected_fps}")
        if video.get("codec_name") != "h264":
            errors.append(f"交付视频编码须为 H.264: {video.get('codec_name')}")
        if timeline is not None:
            duration = float(video.get("duration") or metadata["format"].get("duration") or 0)
            expected = timeline["duration_frames"] / expected_fps
            if abs(duration - expected) > max(2 / expected_fps, 0.08):
                errors.append(f"视频时长不符: {duration:.3f}s, 预期 {expected:.3f}s")
    if audios and audios[0].get("codec_name") != "aac":
        errors.append(f"交付音轨编码须为 AAC: {audios[0].get('codec_name')}")
    if audios and timeline is not None:
        duration = float(audios[0].get("duration") or metadata["format"].get("duration") or 0)
        expected = timeline["duration_frames"] / expected_fps
        if abs(duration - expected) > max(3 / expected_fps, 0.15):
            errors.append(f"音轨时长与全片不符: {duration:.3f}s, 预期 {expected:.3f}s")
    try:
        _run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", metadata["path"], "-map", "0:v:0?", "-map", "0:a:0?", "-f", "null", "-"], timeout=900)
    except RuntimeError as error:
        errors.append(f"媒体无法完整解码: {error}")
    if timeline is not None:
        # Caption safe geometry is checked above; no automatic vision claim.
        warnings.append("安全区域已按时间线几何校验；最终渲染字形和可读性仍需人工观看")
    return {"passed": not errors, "errors": errors, "warnings": warnings, "manual_checks": manual_checks, "probe": metadata}
