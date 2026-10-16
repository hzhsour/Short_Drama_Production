"""Deterministic conversion of explicit structured scripts, without LLM calls."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .validation import SCENE_ID, validate_storyboard


def _convert(script: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    result = {key: deepcopy(script.get(key)) for key in ("episode_id", "aspect_ratio", "fps")}
    result["shots"] = []
    scenes = script.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return result, ["结构化剧本 scenes 必须是非空数组"]
    scene_ids: set[str] = set()
    for number, scene in enumerate(scenes):
        label = f"scenes[{number}]"
        if not isinstance(scene, dict):
            errors.append(f"{label} 必须是对象")
            continue
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not SCENE_ID.fullmatch(scene_id):
            errors.append(f"{label}.scene_id 格式无效")
        elif scene_id in scene_ids:
            errors.append(f"场景 ID 重复: {scene_id}")
        else:
            scene_ids.add(scene_id)
        if isinstance(scene_id, str) and isinstance(script.get("episode_id"), str) and not scene_id.startswith(script["episode_id"] + "-"):
            errors.append(f"{label}.scene_id 与 episode_id 不匹配")
        if not isinstance(scene.get("location"), str) or not scene["location"].strip():
            errors.append(f"{label}.location 必须是非空字符串")
        shots = scene.get("shots")
        if not isinstance(shots, list) or not shots:
            errors.append(f"{label}.shots 必须是非空数组")
            continue
        for shot in shots:
            if not isinstance(shot, dict):
                errors.append(f"{label}.shots 每项必须是对象")
                continue
            converted = deepcopy(shot)
            if "scene_id" in shot and shot["scene_id"] != scene_id:
                errors.append(f"{label}: 镜头 scene_id 与所在场景不匹配")
            converted.setdefault("scene_id", scene_id)
            converted.setdefault("location", scene.get("location"))
            result["shots"].append(converted)
    for key in ("title", "technical_test", "version", "width", "height", "sound_mode"):
        if key in script:
            result[key] = deepcopy(script[key])
    return result, errors


def validate_script(script: Any, characters: dict | None = None) -> list[str]:
    if not isinstance(script, dict):
        return ["剧本必须是结构化 JSON 对象；自由文本需先由创作者拆为 scenes/shots"]
    storyboard, errors = _convert(script)
    return errors + validate_storyboard(storyboard, characters)


def script_to_storyboard(script: dict, characters: dict | None = None) -> dict:
    """Copy explicit scene/shot/timing declarations into the storyboard contract.

    This is a data conversion, not automatic creative writing or text-to-shot AI.
    Invalid inputs raise ValueError before any output is produced.
    """
    errors = validate_script(script, characters)
    if errors:
        raise ValueError("剧本校验失败:\n" + "\n".join(errors))
    return _convert(script)[0]
