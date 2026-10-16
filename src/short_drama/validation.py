"""Small dependency-free checks for production storyboards and project files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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


def validate_storyboard(data: Any) -> list[str]:
    """Return human-readable errors for the project's storyboard JSON format."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["分镜顶层必须是 JSON 对象"]

    for field in ("episode_id", "aspect_ratio", "fps", "shots"):
        if field not in data:
            errors.append(f"分镜缺少字段: {field}")
    shots = data.get("shots")
    if not isinstance(shots, list):
        errors.append("shots 必须是数组")
        return errors

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
            if not re.fullmatch(r"EP\d{3}-SC\d{2}-SH\d{2,3}", shot_id):
                errors.append(f"{label}.shot_id 格式应为 EP001-SC01-SH001")
            if shot_id in seen_ids:
                errors.append(f"镜头 ID 重复: {shot_id}")
            seen_ids.add(shot_id)
        duration = shot.get("duration_frames")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            errors.append(f"{label}.duration_frames 必须是正整数")
        if not isinstance(shot.get("characters"), list):
            errors.append(f"{label}.characters 必须是数组")
        for field in ("dialogue", "audio", "continuity_refs"):
            if field in shot and not isinstance(shot[field], list):
                errors.append(f"{label}.{field} 必须是数组")
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

    storyboards = sorted((root / "production" / "episodes").glob("*/storyboard.json"))
    for path in storyboards:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"无法读取分镜 {path.relative_to(root)}: {error}")
            continue
        errors.extend(f"{path.relative_to(root)}: {message}" for message in validate_storyboard(data))
    return errors
