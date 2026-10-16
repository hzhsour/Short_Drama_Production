"""Build a deterministic, local-media Remotion manifest from production results.

All incoming dialogue/audio frame offsets are relative to their shot. The manifest
uses absolute episode frames, including the intro. Transitions fade *inside* each
shot, so a visual transition never silently shifts dialogue or shortens an episode.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any


SCHEMA = "short-drama.timeline/v1"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} 必须为 >= {minimum} 的整数")
    return value


def local_media_path(value: Any) -> Path:
    """Resolve an existing local file; FFmpeg/renderer never receive network URLs."""
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("媒体路径不能为空")
    raw = str(value)
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:[\\/]", raw):
        raise ValueError("仅允许本地媒体文件，禁止 URL/协议路径")
    if raw.startswith(("//", "\\\\")):
        raise ValueError("禁止网络共享路径")
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"媒体文件不存在: {path}")
    return path


def _hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def build_timeline(
    storyboard: dict[str, Any],
    video_result: dict[str, Any],
    audio_result: dict[str, Any],
    intro_frames: int = 30,
    outro_frames: int = 30,
    *,
    title: str | None = None,
    subtitle: str = "本地占位素材 · 技术测试视频",
    transition_frames: int = 6,
) -> dict[str, Any]:
    """Join shot IDs to artifacts; raise on incomplete or inconsistent inputs.

    Artifacts and tracks must already exist on disk. A renderer helper copies
    these files to its temporary public directory; no file:// browser workaround
    or remote downloads are necessary. This function does not modify any file.
    """
    fps = _integer(storyboard.get("fps", 30), "fps", 1)
    width = _integer(storyboard.get("width", 1080), "width", 2)
    height = _integer(storyboard.get("height", 1920), "height", 2)
    if width % 2 or height % 2:
        raise ValueError("H.264 yuv420p 要求宽高均为偶数")
    intro_frames = _integer(intro_frames, "intro_frames")
    outro_frames = _integer(outro_frames, "outro_frames")
    transition_frames = _integer(transition_frames, "transition_frames")
    episode_id = storyboard.get("episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        raise ValueError("缺少 episode_id")
    for result in (video_result, audio_result):
        if result.get("episode_id", episode_id) != episode_id:
            raise ValueError("分镜、视频和音频的 episode_id 必须一致")
    source_shots = storyboard.get("shots")
    if not isinstance(source_shots, list) or not source_shots:
        raise ValueError("至少需要一个分镜镜头")

    jobs: dict[str, dict[str, Any]] = {}
    for job in video_result.get("jobs", []):
        shot_id = job.get("shot_id")
        if shot_id in jobs:
            raise ValueError(f"重复的视频结果: {shot_id}")
        jobs[shot_id] = job
    shots: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    cursor = intro_frames
    for source in source_shots:
        shot_id = source.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id or shot_id in by_id:
            raise ValueError(f"无效或重复的镜头 ID: {shot_id}")
        duration = _integer(source.get("duration_frames"), f"{shot_id}.duration_frames", 1)
        job = jobs.get(shot_id, {})
        if job.get("status") not in {"succeeded", "completed", "complete"}:
            raise ValueError(f"镜头素材尚未完成: {shot_id}")
        artifact = job.get("artifact") or {}
        path = local_media_path(artifact.get("path"))
        kind = "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video"
        if path.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            raise ValueError(f"不支持的镜头媒体格式: {path.suffix}")
        digest = _hash(path)
        if artifact.get("sha256") and artifact["sha256"] != digest:
            raise ValueError(f"镜头素材哈希不匹配: {shot_id}")
        shot = {
            "shot_id": shot_id,
            "scene_id": source.get("scene_id", ""),
            "characters": source.get("characters", []),
            "start_frame": cursor,
            "duration_frames": duration,
            "media": {
                "kind": kind, "path": str(path), "sha256": digest,
                "source_start_frame": _integer(source.get("source_start_frame", 0), "source_start_frame"),
            },
            "transition": {"kind": "fade" if transition_frames else "cut", "duration_frames": min(transition_frames, (duration - 1) // 2)},
        }
        by_id[shot_id] = shot
        shots.append(shot)
        cursor += duration

    duration_frames = cursor + outro_frames
    tracks = []
    track_ids: set[str] = set()
    for index, track in enumerate(audio_result.get("tracks", [])):
        track_id = str(track.get("id", f"audio-{index + 1}"))
        if track_id in track_ids:
            raise ValueError(f"重复音轨 ID: {track_id}")
        track_ids.add(track_id)
        shot_id = track.get("shot_id")
        shot = by_id.get(shot_id)
        if shot_id and not shot:
            raise ValueError(f"音轨引用未知镜头: {shot_id}")
        relative = _integer(track.get("start_frame", 0), f"{track_id}.start_frame")
        length = _integer(track.get("duration_frames"), f"{track_id}.duration_frames", 1)
        limit = shot["duration_frames"] if shot else duration_frames
        if relative + length > limit:
            raise ValueError(f"音轨超出镜头/全片范围: {track_id}")
        volume = track.get("volume", 1.0)
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not math.isfinite(volume) or not 0 <= volume <= 2:
            raise ValueError(f"音轨音量必须在 0..2: {track_id}")
        audio_path = local_media_path(track.get("path"))
        audio_hash = _hash(audio_path)
        if track.get("sha256") and track["sha256"] != audio_hash:
            raise ValueError(f"音轨素材哈希不匹配: {track_id}")
        tracks.append({
            "id": track_id, "shot_id": shot_id, "kind": track.get("kind", "voice"),
            "character_id": track.get("character_id"), "path": str(audio_path), "sha256": audio_hash,
            "start_frame": (shot["start_frame"] if shot else 0) + relative,
            "duration_frames": length, "source_start_frame": _integer(track.get("source_start_frame", 0), "source_start_frame"),
            "volume": volume,
        })

    source_subtitles = audio_result.get("subtitles")
    if source_subtitles is None:
        source_subtitles = [dict(line, shot_id=shot["shot_id"]) for shot in source_shots for line in shot.get("dialogue", []) if isinstance(line, dict)]
    subtitles = []
    for index, line in enumerate(source_subtitles):
        shot_id = line.get("shot_id")
        shot = by_id.get(shot_id)
        if not shot:
            raise ValueError(f"字幕引用未知镜头: {shot_id}")
        start = _integer(line.get("start_frame", 0), "subtitle.start_frame")
        end = line.get("end_frame", start + line.get("duration_frames", 0))
        end = _integer(end, "subtitle.end_frame", 1)
        if end <= start or end > shot["duration_frames"]:
            raise ValueError(f"字幕超出镜头范围或无时长: {shot_id}")
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("字幕文本不能为空")
        subtitles.append({
            "id": f"subtitle-{index + 1}", "shot_id": shot_id,
            "character_id": line.get("character_id"), "text": text,
            "start_frame": shot["start_frame"] + start,
            "end_frame": shot["start_frame"] + end,
        })
    subtitles.sort(key=lambda line: (line["start_frame"], line["end_frame"], line["id"]))
    manifest = {
        "schema": SCHEMA, "episode_id": episode_id,
        "fps": fps, "width": width, "height": height, "duration_frames": duration_frames,
        "title": title or episode_id, "technical_test": video_result.get("mode", "mock") == "mock",
        "intro": {"start_frame": 0, "duration_frames": intro_frames, "title": title or episode_id, "subtitle": subtitle},
        "outro": {"start_frame": cursor, "duration_frames": outro_frames, "title": "本集结束", "subtitle": subtitle},
        "shots": shots, "tracks": tracks, "subtitles": subtitles,
        "safe_area": {"x": round(width * 0.08), "y": round(height * 0.68), "width": round(width * 0.84), "height": round(height * 0.16)},
        "quality": {"automatic": "结构、时码、媒体解码与交付规格", "manual_required": ["字幕最终可读性与字形", "人脸/服饰/道具一致性", "剧情连续性", "口型、表演与听感"]},
    }
    errors = validate_timeline(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


def validate_timeline(timeline: dict[str, Any]) -> list[str]:
    """Check contiguous coverage, caption safe area, and shot traceability."""
    errors = []
    if not isinstance(timeline, dict):
        return ["时间线必须为 JSON 对象"]
    if timeline.get("schema") != SCHEMA:
        errors.append("不支持的时间线 schema")
    try:
        total = _integer(timeline.get("duration_frames"), "duration_frames", 1)
        width = _integer(timeline.get("width"), "width", 2)
        height = _integer(timeline.get("height"), "height", 2)
        _integer(timeline.get("fps"), "fps", 1)
        intro = timeline.get("intro", {})
        outro = timeline.get("outro", {})
        cursor = _integer(intro.get("duration_frames", 0), "intro.duration_frames")
        if intro.get("start_frame", 0) != 0:
            errors.append("片头必须从第 0 帧开始")
        ids = set()
        by_id = {}
        shots = timeline.get("shots", [])
        if not isinstance(shots, list) or any(not isinstance(shot, dict) for shot in shots):
            raise ValueError("shots 必须为镜头对象数组")
        if not shots:
            errors.append("时间线没有镜头")
        for shot in shots:
            shot_id = shot.get("shot_id")
            if not isinstance(shot_id, str) or not shot_id or shot_id in ids:
                errors.append(f"镜头无法追溯或重复: {shot_id}")
            ids.add(shot_id)
            by_id[shot_id] = shot
            if shot.get("start_frame") != cursor:
                errors.append(f"镜头时间线存在缺口或重叠: {shot_id}")
            cursor += _integer(shot.get("duration_frames"), "shot.duration_frames", 1)
            media = shot.get("media", {})
            if not isinstance(media, dict):
                raise ValueError("镜头 media 必须为对象")
            if not media.get("path") or not media.get("sha256"):
                errors.append(f"镜头缺少素材路径或哈希: {shot_id}")
            if media.get("kind") not in {"image", "video"}:
                errors.append(f"镜头媒体类型无效: {shot_id}")
        if outro.get("start_frame", cursor) != cursor:
            errors.append("片尾与镜头时间线存在缺口或重叠")
        if cursor + _integer(outro.get("duration_frames", 0), "outro.duration_frames") != total:
            errors.append("总时长与片头/镜头/片尾之和不符")
        area = timeline.get("safe_area", {})
        x, y, aw, ah = (area.get(key, -1) for key in ("x", "y", "width", "height"))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (x, y, aw, ah)):
            errors.append("字幕安全区域必须为有限数字")
        elif aw <= 0 or ah <= 0 or x < width * 0.05 or y < height * 0.05 or x + aw > width * 0.95 or y + ah > height * 0.90:
            errors.append("字幕区域超出移动端安全范围")
        lines = timeline.get("subtitles", [])
        tracks = timeline.get("tracks", [])
        if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
            raise ValueError("subtitles 必须为字幕对象数组")
        if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
            raise ValueError("tracks 必须为音轨对象数组")
        for line in lines:
            shot = by_id.get(line.get("shot_id"))
            if not shot:
                errors.append("字幕不能追溯到分镜")
                continue
            start = _integer(line.get("start_frame"), "subtitle.start_frame")
            end = _integer(line.get("end_frame"), "subtitle.end_frame", 1)
            if not shot["start_frame"] <= start < end <= shot["start_frame"] + shot["duration_frames"]:
                errors.append(f"字幕时间不在镜头内: {line.get('id')}")
        for track in tracks:
            start = _integer(track.get("start_frame"), "track.start_frame")
            length = _integer(track.get("duration_frames"), "track.duration_frames", 1)
            if start + length > total:
                errors.append(f"音轨超出全片范围: {track.get('id')}")
            shot_id = track.get("shot_id")
            if shot_id:
                shot = by_id.get(shot_id)
                if not shot or not shot["start_frame"] <= start < start + length <= shot["start_frame"] + shot["duration_frames"]:
                    errors.append(f"音轨不能追溯到镜头或超出镜头: {track.get('id')}")
    except (ValueError, TypeError, KeyError) as error:
        errors.append(str(error))
    return errors


def timeline_srt(timeline: dict[str, Any]) -> str:
    """Export delivery subtitles with the same intro offsets as Remotion."""
    errors = validate_timeline(timeline)
    if errors:
        raise ValueError("; ".join(errors))
    fps = timeline["fps"]

    def timestamp(frame: int) -> str:
        milliseconds = round(frame * 1000 / fps)
        hours, remaining = divmod(milliseconds, 3600000)
        minutes, remaining = divmod(remaining, 60000)
        seconds, remaining = divmod(remaining, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{remaining:03}"

    blocks = [f"{index}\n{timestamp(line['start_frame'])} --> {timestamp(line['end_frame'])}\n{line['text']}" for index, line in enumerate(timeline.get("subtitles", []), 1)]
    return "\n\n".join(blocks) + ("\n" if blocks else "")
