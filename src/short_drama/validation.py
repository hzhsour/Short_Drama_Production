"""Dependency-free, strict checks for production storyboards and project files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


EPISODE_ID = re.compile(r"EP\d{3}")
SCENE_ID = re.compile(r"EP\d{3}-SC\d{2}")
SHOT_ID = re.compile(r"EP\d{3}-SC\d{2}-SH\d{2,3}")
CHARACTER_ID = re.compile(r"CHAR-\d{3}")


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def safe_relative_path(value: Any) -> bool:
    """Only portable project-relative paths; no URLs, drive letters or traversal."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or any(ord(char) < 32 for char in value):
        return False
    path = Path(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in value.split("/"))


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, label: str, errors: list[str], *, pattern=None, paths=False) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} 必须是数组")
        return
    seen = set()
    for index, item in enumerate(value):
        if not _text(item):
            errors.append(f"{label}[{index}] 必须是非空字符串")
            continue
        if item in seen:
            errors.append(f"{label} 元素重复: {item}")
        seen.add(item)
        if pattern and not pattern.fullmatch(item):
            errors.append(f"{label}[{index}] ID 格式无效")
        if paths and not safe_relative_path(item):
            errors.append(f"{label}[{index}] 必须是安全的项目相对路径")


def _timing(item: dict, duration: Any, label: str, errors: list[str]) -> None:
    start, length = item.get("start_frame"), item.get("duration_frames")
    if not is_integer(start) or start < 0:
        errors.append(f"{label}.start_frame 必须是非负整数")
    if not is_integer(length) or length <= 0:
        errors.append(f"{label}.duration_frames 必须是正整数")
    if is_integer(start) and is_integer(length) and is_integer(duration) and start + length > duration:
        errors.append(f"{label} 时间范围超出镜头")


REQUIRED_DIRECTORIES = (
    "assets/reference",
    "assets/generated/characters",
    "assets/generated/locations",
    "assets/generated/storyboards",
    "assets/generated/video",
    "assets/voice",
    "assets/music",
    "assets/fonts",
    "docs/templates",
    "production/characters",
    "production/episodes/EP001",
    "renders",
    "src/remotion",
    "tests",
    "tools",
)
REQUIRED_SKILLS = (
    "chinese-short-drama-script",
    "character-consistency",
    "storyboard-breakdown",
    "ai-video-production",
    "remotion-production",
    "ffmpeg-postproduction",
)
SHOT_REQUIRED_FIELDS = (
    "shot_id",
    "scene_id",
    "duration_frames",
    "characters",
    "location",
    "action",
    "framing",
    "camera_move",
    "dialogue",
    "audio",
    "image_prompt",
    "video_prompt",
    "continuity_refs",
)


def validate_storyboard(data: Any, characters: Any = None) -> list[str]:
    """Return human-readable errors for the project's storyboard JSON format."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["分镜顶层必须是 JSON 对象"]

    for field in ("episode_id", "aspect_ratio", "fps", "shots"):
        if field not in data:
            errors.append(f"分镜缺少字段: {field}")
    episode_id = data.get("episode_id")
    if not isinstance(episode_id, str) or not EPISODE_ID.fullmatch(episode_id):
        errors.append("episode_id 格式应为 EP001")
    if not isinstance(data.get("aspect_ratio"), str) or not re.fullmatch(r"[1-9]\d*:[1-9]\d*", data["aspect_ratio"]):
        errors.append("aspect_ratio 必须是正整数比例，例如 9:16")
    fps = data.get("fps")
    if not is_integer(fps) or not 1 <= fps <= 120:
        errors.append("fps 必须是 1 到 120 的整数")
    shots = data.get("shots")
    if not isinstance(shots, list):
        errors.append("shots 必须是数组")
        return errors
    known_characters = None
    if characters is not None:
        from .continuity import character_index, validate_characters
        errors.extend(validate_characters(characters))
        known_characters = set(character_index(characters))

    seen_ids: set[str] = set()
    for index, shot in enumerate(shots):
        label = f"shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{label} 必须是对象")
            continue
        for field in SHOT_REQUIRED_FIELDS:
            if field not in shot:
                errors.append(f"{label} 缺少字段: {field}")
        shot_id = shot.get("shot_id")
        if isinstance(shot_id, str):
            if not SHOT_ID.fullmatch(shot_id):
                errors.append(f"{label}.shot_id 格式应为 EP001-SC01-SH001")
            if isinstance(episode_id, str) and not shot_id.startswith(episode_id + "-"):
                errors.append(f"{label}.shot_id 与 episode_id 不匹配")
            if shot_id in seen_ids:
                errors.append(f"镜头 ID 重复: {shot_id}")
            seen_ids.add(shot_id)
        else:
            errors.append(f"{label}.shot_id 必须是字符串")
        scene_id = shot.get("scene_id")
        if not isinstance(scene_id, str) or not SCENE_ID.fullmatch(scene_id):
            errors.append(f"{label}.scene_id 格式应为 EP001-SC01")
        elif isinstance(shot_id, str) and not shot_id.startswith(scene_id + "-"):
            errors.append(f"{label}.scene_id 与 shot_id 不匹配")
        duration = shot.get("duration_frames")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            errors.append(f"{label}.duration_frames 必须是正整数")
        _string_list(shot.get("characters"), f"{label}.characters", errors, pattern=CHARACTER_ID)
        cast = shot.get("characters") if isinstance(shot.get("characters"), list) else []
        if known_characters is not None:
            for character in cast:
                if isinstance(character, str) and character not in known_characters:
                    errors.append(f"{label}.characters 引用了未知角色: {character}")
        for field in ("location", "action", "framing", "camera_move", "image_prompt", "video_prompt"):
            if not _text(shot.get(field)):
                errors.append(f"{label}.{field} 必须是非空字符串")
        _string_list(shot.get("continuity_refs"), f"{label}.continuity_refs", errors, paths=True)
        dialogue = shot.get("dialogue")
        intervals: list[tuple[int, int]] = []
        if not isinstance(dialogue, list):
            errors.append(f"{label}.dialogue 必须是数组")
        else:
            for number, line in enumerate(dialogue):
                line_label = f"{label}.dialogue[{number}]"
                if not isinstance(line, dict):
                    errors.append(f"{line_label} 必须是对象")
                    continue
                if not _text(line.get("text")):
                    errors.append(f"{line_label}.text 必须是非空字符串")
                if not isinstance(line.get("character_id"), str) or line["character_id"] not in cast:
                    errors.append(f"{line_label}.character_id 必须引用本镜头角色")
                if "audio_path" in line and not safe_relative_path(line["audio_path"]):
                    errors.append(f"{line_label}.audio_path 必须是安全的项目相对路径")
                volume = line.get("volume", 1.0)
                if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
                    errors.append(f"{line_label}.volume 必须在 0 到 1 之间")
                _timing(line, duration, line_label, errors)
                start, length = line.get("start_frame"), line.get("duration_frames")
                if is_integer(start) and is_integer(length) and start >= 0 and length > 0:
                    end = start + length
                    if any(start < previous_end and end > previous_start for previous_start, previous_end in intervals):
                        errors.append(f"{line_label} 对白时间重叠；单轨字幕要求顺序对白")
                    intervals.append((start, end))
        audio = shot.get("audio")
        if not isinstance(audio, list):
            errors.append(f"{label}.audio 必须是数组")
        else:
            audio_ids = set()
            for number, item in enumerate(audio):
                audio_label = f"{label}.audio[{number}]"
                if isinstance(item, str) and item.strip():
                    continue  # Legacy sound directions become explicitly marked mock cues.
                if not isinstance(item, dict):
                    errors.append(f"{audio_label} 必须是非空声音说明或对象")
                    continue
                if item.get("kind") not in ("bgm", "sfx", "ambience"):
                    errors.append(f"{audio_label}.kind 必须是 bgm/sfx/ambience")
                _timing(item, duration, audio_label, errors)
                if "path" in item and not safe_relative_path(item["path"]):
                    errors.append(f"{audio_label}.path 必须是安全的项目相对路径")
                volume = item.get("volume", 1.0)
                if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
                    errors.append(f"{audio_label}.volume 必须在 0 到 1 之间")
                if "id" in item:
                    if not _text(item["id"]) or item["id"] in audio_ids:
                        errors.append(f"{audio_label}.id 必须是非空且不重复的字符串")
                    else:
                        audio_ids.add(item["id"])
        if "continuity" in shot:
            from .continuity import validate_shot_continuity
            errors.extend(validate_shot_continuity(shot["continuity"], cast, label))
    return errors


def validate_project(root: Path) -> list[str]:
    """Check required files, project-local Skills and committed storyboards."""
    errors: list[str] = []
    for relative in REQUIRED_DIRECTORIES:
        if not (root / relative).is_dir():
            errors.append(f"缺少目录: {relative}")

    for name in REQUIRED_SKILLS:
        skill_path = root / ".agents" / "skills" / name / "SKILL.md"
        if not skill_path.is_file():
            errors.append(f"缺少 Codex Skill: .agents/skills/{name}/SKILL.md")
            continue
        content = skill_path.read_text(encoding="utf-8")
        if not content.startswith("---\n") or "\nname:" not in content or "\ndescription:" not in content:
            errors.append(f"Skill frontmatter 无效: {skill_path.relative_to(root)}")
    for skill_path in sorted((root / ".agents" / "skills").glob("*/SKILL.md")):
        content = skill_path.read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|$)", content, re.DOTALL)
        if not frontmatter:
            errors.append(f"Skill frontmatter 无效: {skill_path.relative_to(root)}")
            continue
        name = re.search(r"^name:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*$", frontmatter[1], re.MULTILINE)
        description = re.search(r"^description:\s*\S.+$", frontmatter[1], re.MULTILINE)
        if not name or len(name[1]) > 64 or not description:
            errors.append(f"Skill name/description 无效: {skill_path.relative_to(root)}")

    storyboards = sorted((root / "production" / "episodes").glob("*/storyboard.json"))
    for path in storyboards:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"无法读取分镜 {path.relative_to(root)}: {error}")
            continue
        errors.extend(f"{path.relative_to(root)}: {message}" for message in validate_storyboard(data))
    from .continuity import validate_characters
    for path in sorted((root / "production" / "characters").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            errors.extend(f"{path.relative_to(root)}: {message}" for message in validate_characters(data))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"无法读取人物 {path.relative_to(root)}: {error}")
    for directory in sorted((root / "examples").glob("*/")):
        profiles = None
        profile_path = directory / "characters.json"
        if profile_path.is_file():
            try:
                profiles = json.loads(profile_path.read_text(encoding="utf-8"))
                errors.extend(f"{profile_path.relative_to(root)}: {message}" for message in validate_characters(profiles))
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"无法读取示例人物 {profile_path.relative_to(root)}: {error}")
        for filename in ("script.json", "storyboard.json"):
            path = directory / filename
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if filename == "script.json":
                    from .script import validate_script
                    messages = validate_script(data, profiles)
                else:
                    messages = validate_storyboard(data, profiles)
                errors.extend(f"{path.relative_to(root)}: {message}" for message in messages)
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"无法读取示例 {path.relative_to(root)}: {error}")
    for path in sorted((root / "docs" / "templates").glob("*.example.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.name.startswith("storyboard"):
                errors.extend(f"{path.relative_to(root)}: {message}" for message in validate_storyboard(data))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"无法读取模板 {path.relative_to(root)}: {error}")
    return errors
