"""Character metadata and continuity checks, not visual identity guarantees.

These rules compare declared metadata. They cannot detect a changed generated
face or establish semantic story continuity; human review remains necessary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation import CHARACTER_ID, SCENE_ID, SHOT_ID, _string_list, _text, safe_relative_path


def character_index(data: Any) -> dict[str, dict]:
    if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
        return {}
    return {item["character_id"]: item for item in data["characters"]
            if isinstance(item, dict) and isinstance(item.get("character_id"), str)}


def validate_characters(data: Any, root: Path | None = None) -> list[str]:
    """Check canonical {characters: [profile]} data; root also checks reference files."""
    if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
        return ["角色档案必须是含 characters 数组的对象"]
    errors: list[str] = []
    seen: set[str] = set()
    voices: set[str] = set()
    for number, profile in enumerate(data["characters"]):
        label = f"characters[{number}]"
        if not isinstance(profile, dict):
            errors.append(f"{label} 必须是对象")
            continue
        character_id = profile.get("character_id")
        if not isinstance(character_id, str) or not CHARACTER_ID.fullmatch(character_id):
            errors.append(f"{label}.character_id 格式应为 CHAR-001")
        elif character_id in seen:
            errors.append(f"角色 ID 重复: {character_id}")
        else:
            seen.add(character_id)
        for field in ("name", "age", "face_features", "hairstyle", "body"):
            if not _text(profile.get(field)):
                errors.append(f"{label}.{field} 必须是非空字符串")
        for field in ("expressions", "fixed_props"):
            _string_list(profile.get(field), f"{label}.{field}", errors)
        _string_list(profile.get("historical_shots"), f"{label}.historical_shots", errors, pattern=SHOT_ID)
        outfits = profile.get("outfits")
        if not isinstance(outfits, dict) or not outfits:
            errors.append(f"{label}.outfits 必须是非空造型对象")
            outfits = {}
        for outfit_id, outfit in outfits.items():
            if not _text(outfit_id) or not isinstance(outfit, dict) or not _text(outfit.get("description")):
                errors.append(f"{label}.outfits.{outfit_id} 需有 description")
                continue
            _string_list(outfit.get("props"), f"{label}.outfits.{outfit_id}.props", errors)
        refs = profile.get("reference_images")
        if not isinstance(refs, dict):
            errors.append(f"{label}.reference_images 必须是多视角路径对象")
        else:
            for view in ("front", "side", "back"):
                if view not in refs:
                    errors.append(f"{label}.reference_images 缺少视角: {view}")
            for view, reference in refs.items():
                if not safe_relative_path(reference):
                    errors.append(f"{label}.reference_images.{view} 必须是安全的项目相对路径")
                elif root is not None:
                    target = (root / reference).resolve()
                    if not target.is_relative_to(root.resolve()) or not target.is_file():
                        errors.append(f"{label}.reference_images.{view} 参考图不存在或越出项目")
        looks = profile.get("scene_looks")
        if not isinstance(looks, dict):
            errors.append(f"{label}.scene_looks 必须是场景到造型的对象")
        else:
            for scene, outfit_id in looks.items():
                if not isinstance(scene, str) or not SCENE_ID.fullmatch(scene) or not isinstance(outfit_id, str) or outfit_id not in outfits:
                    errors.append(f"{label}.scene_looks.{scene} 场景 ID 或造型引用无效")
        relationships = profile.get("relationships")
        if not isinstance(relationships, dict):
            errors.append(f"{label}.relationships 必须是角色 ID 到关系描述的对象")
        else:
            for other_id, relationship in relationships.items():
                if not isinstance(other_id, str) or not CHARACTER_ID.fullmatch(other_id) or other_id == character_id or not _text(relationship):
                    errors.append(f"{label}.relationships.{other_id} 关系声明无效")
        voice = profile.get("voice")
        if not isinstance(voice, dict):
            errors.append(f"{label}.voice 必须是声音设定对象")
        else:
            if not _text(voice.get("profile_id")):
                errors.append(f"{label}.voice.profile_id 必须是非空字符串")
            elif voice["profile_id"] in voices:
                errors.append(f"{label}.voice.profile_id 应为不同角色使用独立声音设定")
            else:
                voices.add(voice["profile_id"])
            if voice.get("language") != "zh-CN":
                errors.append(f"{label}.voice.language 当前必须为 zh-CN")
            for field, minimum, maximum in (("pitch_hz", 80, 500), ("rate", .5, 2)):
                value = voice.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
                    errors.append(f"{label}.voice.{field} 必须在 {minimum} 到 {maximum} 之间")
    for profile in data["characters"]:
        if not isinstance(profile, dict):
            continue
        relationships = profile.get("relationships")
        if isinstance(relationships, dict):
            for other_id in relationships:
                if other_id not in seen:
                    errors.append(f"{profile.get('character_id', label)} 引用了未知关系角色: {other_id}")
    return errors


def validate_shot_continuity(data: Any, cast: list, label: str = "shot") -> list[str]:
    errors: list[str] = []
    prefix = f"{label}.continuity"
    if not isinstance(data, dict):
        return [f"{prefix} 必须是对象"]
    for field in ("time", "space"):
        if not _text(data.get(field)):
            errors.append(f"{prefix}.{field} 必须是非空字符串")
    if "time_jump" in data and not isinstance(data["time_jump"], bool):
        errors.append(f"{prefix}.time_jump 必须是布尔值")
    if data.get("previous_shot_id") is not None and (
            not isinstance(data["previous_shot_id"], str) or not SHOT_ID.fullmatch(data["previous_shot_id"])):
        errors.append(f"{prefix}.previous_shot_id 格式无效")
    states = data.get("characters")
    if not isinstance(states, dict):
        errors.append(f"{prefix}.characters 必须是角色状态对象")
        return errors
    for character_id, state in states.items():
        if character_id not in cast:
            errors.append(f"{prefix}.characters 引用了镜头外角色: {character_id}")
        if not isinstance(state, dict):
            errors.append(f"{prefix}.characters.{character_id} 必须是对象")
            continue
        for field in ("outfit", "expression"):
            if not _text(state.get(field)):
                errors.append(f"{prefix}.characters.{character_id}.{field} 必须是非空字符串")
        _string_list(state.get("props"), f"{prefix}.characters.{character_id}.props", errors)
        for field in ("screen_position", "entry", "exit"):
            if field in state and state[field] not in ("left", "center", "right", "none"):
                errors.append(f"{prefix}.characters.{character_id}.{field} 必须为 left/center/right/none")
    for character_id in cast:
        if isinstance(character_id, str) and character_id not in states:
            errors.append(f"{prefix}.characters 缺少角色状态: {character_id}")
    changes = data.get("relationship_changes", [])
    if not isinstance(changes, list):
        errors.append(f"{prefix}.relationship_changes 必须是数组")
    else:
        for change in changes:
            if not isinstance(change, dict) or not _text(change.get("reason")) or not _text(change.get("relationship")):
                errors.append(f"{prefix}.relationship_changes 需含角色 character_id/other_id、relationship 与 reason")
            elif change.get("character_id") not in cast or not isinstance(change.get("other_id"), str) or not CHARACTER_ID.fullmatch(change["other_id"]):
                errors.append(f"{prefix}.relationship_changes 角色引用无效")
    return errors


def check_continuity(storyboard: dict, characters: dict) -> dict:
    """Report missing metadata and unexplained changes without inferring story facts."""
    from .validation import validate_storyboard
    errors = validate_storyboard(storyboard, characters)
    warnings: list[str] = []
    if errors:
        return {"episode_id": storyboard.get("episode_id"), "errors": errors, "warnings": warnings,
                "scope": "仅元数据检查；格式错误需先修复；不能保证生成角色不变脸"}
    profiles = character_index(characters)
    history: dict[str, tuple[dict, dict]] = {}
    history_records: dict[str, list[dict]] = {character_id: [] for character_id in profiles}
    relationships = {cid: dict(profile.get("relationships", {})) for cid, profile in profiles.items()}
    previous = None
    for shot in storyboard.get("shots", []):
        if not isinstance(shot, dict):
            continue
        shot_id = shot.get("shot_id", "unknown")
        continuity = shot.get("continuity")
        if not isinstance(continuity, dict):
            warnings.append(f"{shot_id}: 未声明时空/人物状态，无法执行连续性对照")
            previous = shot
            continue
        if continuity.get("previous_shot_id") is not None:
            if previous is None or continuity["previous_shot_id"] != previous.get("shot_id"):
                errors.append(f"{shot_id}: previous_shot_id 与实际前镜头不匹配")
        if previous and previous.get("scene_id") == shot.get("scene_id"):
            prior = previous.get("continuity", {})
            if isinstance(prior, dict) and prior.get("time") != continuity.get("time") and not continuity.get("time_jump"):
                warnings.append(f"{shot_id}: 同场时间声明变化但没有 time_jump")
            if isinstance(prior, dict) and prior.get("space") != continuity.get("space") and not continuity.get("transition_reason"):
                warnings.append(f"{shot_id}: 场景空间变化需记录 transition_reason")
        states = continuity.get("characters", {})
        if not isinstance(states, dict):
            previous = shot
            continue
        for character_id, state in states.items():
            if not isinstance(state, dict) or character_id not in profiles:
                continue
            profile = profiles[character_id]
            outfit = state.get("outfit")
            if isinstance(outfit, str) and outfit not in profile.get("outfits", {}):
                errors.append(f"{shot_id}/{character_id}: 未知造型 {outfit}")
            expected = profile.get("scene_looks", {}).get(shot.get("scene_id"))
            if expected and outfit != expected and not state.get("change_reason"):
                warnings.append(f"{shot_id}/{character_id}: 与场景固定造型不同且缺少 change_reason")
            props = state.get("props", [])
            if isinstance(props, list):
                for prop in profile.get("fixed_props", []):
                    if prop not in props and not state.get("change_reason"):
                        warnings.append(f"{shot_id}/{character_id}: 固定道具 {prop} 缺少去向说明")
            if character_id in history:
                old_shot, old_state = history[character_id]
                same_time = old_shot.get("continuity", {}).get("time") == continuity.get("time")
                same_scene = old_shot.get("scene_id") == shot.get("scene_id")
                if same_scene and same_time and not state.get("change_reason"):
                    for field in ("outfit", "props"):
                        if old_state.get(field) != state.get(field):
                            warnings.append(f"{shot_id}/{character_id}: 连续时间中 {field} 变化缺少 change_reason")
                if previous == old_shot and old_state.get("exit") in ("left", "right"):
                    expected_entry = "left" if old_state["exit"] == "right" else "right"
                    if state.get("entry") in ("left", "right") and state["entry"] != expected_entry and not continuity.get("transition_reason"):
                        warnings.append(f"{shot_id}/{character_id}: 前镜头出画与本镜头入画方向可能不衔接")
            history[character_id] = (shot, state)
            history_records[character_id].append({"shot_id": shot_id, "scene_id": shot.get("scene_id"),
                "time": continuity.get("time"), "space": continuity.get("space"),
                "outfit": state.get("outfit"), "props": list(state.get("props", [])),
                "expression": state.get("expression")})
        for change in continuity.get("relationship_changes", []) if isinstance(continuity.get("relationship_changes", []), list) else []:
            if not isinstance(change, dict):
                continue
            cid, other = change.get("character_id"), change.get("other_id")
            if isinstance(cid, str) and isinstance(other, str) and cid in relationships and other in profiles:
                old = relationships[cid].get(other)
                if "previous_relationship" in change and change["previous_relationship"] != old:
                    warnings.append(f"{shot_id}/{cid}: 人物关系前态与历史记录不同")
                relationships[cid][other] = change.get("relationship")
        previous = shot
    return {"episode_id": storyboard.get("episode_id"), "errors": errors, "warnings": warnings,
            "character_history": history_records, "relationship_state": relationships,
            "scope": "仅比较声明的元数据；不保证生成角色脸部、表演或剧情语义一致，需人工审阅"}


validate_continuity = check_continuity
