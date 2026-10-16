"""A bounded, resumable production pass from an approved script to a local MP4.

This process is a worker, not a permanent scheduler. Provider submissions and
polls are bounded by VideoEngine; a subsequent invocation resumes durable jobs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from contextlib import contextmanager

from .audio import build_audio, inspect_audio
from .continuity import check_continuity, validate_characters
from .io import file_hash, load_json, write_json
from .media import normalize_media, qc_video
from .script import script_to_storyboard
from .state import StateStore
from .timeline import build_timeline, timeline_srt
from .video_engine import LiveBlockedError, VideoEngine
from .validation import safe_relative_path


def project_root() -> Path:
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "tools" / "render_episode.mjs").is_file():
        return source_root
    if (Path.cwd() / "tools" / "render_episode.mjs").is_file():
        return Path.cwd()
    raise RuntimeError("请在 Short_Drama_Production 项目内运行渲染命令")


def render_timeline(timeline_path: Path, output: Path) -> None:
    root = project_root()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("需要已安装的 Node.js 与 npm ci 依赖")
    # Tell the JS renderer exactly which interpreter ran the CLI (also Windows).
    env = {**os.environ, "PYTHON": sys.executable}
    subprocess.run([node, str(root / "tools" / "render_episode.mjs"), str(timeline_path.resolve()), str(output.resolve())], cwd=root, env=env, check=True)


def _media_checksums(audio: dict) -> dict[str, str]:
    paths = [track["path"] for track in audio.get("tracks", [])]
    if audio.get("srt_path"):
        paths.append(audio["srt_path"])
    return {path: file_hash(Path(path)) for path in paths}


def _same_media(checksums: dict) -> bool:
    try:
        return isinstance(checksums, dict) and bool(checksums) and all(Path(path).is_file() and file_hash(Path(path)) == digest for path, digest in checksums.items())
    except (OSError, TypeError):
        return False


def _source_audio_hashes(storyboard: dict, root: Path, mode: str) -> dict[str, str]:
    if mode == "mock":
        return {}
    result = {"asset_root": str(root)}
    for shot in storyboard["shots"]:
        sources = [line.get("audio_path") for line in shot["dialogue"]]
        sources += [cue.get("path") for cue in shot["audio"] if isinstance(cue, dict)]
        for relative in sources:
            if relative is None:
                continue
            if not safe_relative_path(relative):
                raise ValueError("源音频必须是安全的项目相对路径")
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("源音频不存在或越出asset_root")
            result[relative] = file_hash(path)
    return result


def _next_directory(parent: Path, prefix: str) -> Path:
    for number in range(1, 10000):
        path = parent / f"{prefix}-v{number:03}"
        if not path.exists():
            return path
    raise RuntimeError("产物版本过多，请选择新的运行目录")


def _next_video(root: Path, episode_id: str) -> Path:
    for number in range(1, 10000):
        path = root / f"{episode_id}-v{number:03}.mp4"
        if not path.exists():
            return path
    raise RuntimeError("渲染版本过多，请选择新的运行目录")


def _run_pipeline(
    script_path: Path,
    characters_path: Path,
    run_dir: Path,
    *,
    mode: str = "mock",
    provider: str = "mock",
    audio_mode: str = "mock",
    render: bool = False,
    max_jobs: int | None = None,
    asset_root: Path | None = None,
    storage_root: Path | None = None,
    project_workspace: Path | None = None,
    model_config: dict | None = None,
    approval_file: Path | None = None,
    budgets: dict | None = None,
    output: Path | None = None,
    intro_frames: int = 30,
    outro_frames: int = 30,
) -> dict:
    script_path, characters_path = Path(script_path).resolve(), Path(characters_path).resolve()
    script, characters = load_json(script_path), load_json(characters_path)
    errors = validate_characters(characters)
    if errors:
        raise ValueError("角色档案校验失败:\n" + "\n".join(errors))
    storyboard = script_to_storyboard(script, characters)
    continuity = check_continuity(storyboard, characters)
    if continuity["errors"]:
        raise ValueError("连续性声明冲突:\n" + "\n".join(continuity["errors"]))
    if Path(run_dir).is_symlink():
        raise ValueError("运行目录不能是符号链接")
    root = Path(run_dir).resolve()
    engine_workspace = Path(project_workspace or root / "engine").resolve()
    reference_root = Path(asset_root or project_root()).resolve()
    context = {"engine_workspace": str(engine_workspace), "reference_root": str(reference_root),
               "storage_root": str(Path(storage_root or engine_workspace / "artifacts/video").resolve())}
    signature = {
        "script_sha256": file_hash(script_path), "characters_sha256": file_hash(characters_path),
        "mode": mode, "provider": provider, "audio_mode": audio_mode,
        "intro_frames": intro_frames, "outro_frames": outro_frames,
    }
    record_path = root / "run.json"
    if record_path.exists():
        record = load_json(record_path)
        if record.get("inputs") != signature:
            raise ValueError("输入、模式或时间线参数已变化，请使用新运行目录，避免混用旧素材/审批")
        previous_context = record.get("execution_context", {})
        if previous_context and any(previous_context.get(key) != value for key, value in context.items()):
            raise ValueError("共享账本或素材根目录已变化；请先恢复原账本并显式rebind-storage，不得以新空账本继续收费任务")
        ledger_id = previous_context.get("ledger_id")
        if ledger_id:
            if StateStore.read_ledger_id(engine_workspace / "state/video-jobs.sqlite3") != ledger_id:
                raise ValueError("原任务账本丢失或身份已变化；请恢复同一UUID的备份，禁止新建账本后继续收费任务")
            context["ledger_id"] = ledger_id
        elif mode == "live" and (record.get("tasks", {}).get("creative_review", {}).get("status") == "succeeded" or "video" in record.get("tasks", {})):
            raise ValueError("已有Live运行缺少账本UUID，需先人工核对原任务并迁移，禁止自动重提")
        if not record.get("execution_context") and mode == "live":
            raise ValueError("旧Live运行缺少账本身份记录，需人工核对已有任务后迁移")
        prior_video = root / "video-result.json"
        if not record.get("execution_context") and prior_video.is_file():
            old_state = Path(load_json(prior_video)["state_path"]).resolve()
            if old_state.parent.parent != engine_workspace:
                raise ValueError("已有任务账本与当前project_workspace不一致")
    else:
        if root.exists() and any(path.name not in (".pipeline-lock.sqlite3", ".pipeline-lock.sqlite3-journal") for path in root.iterdir()):
            raise FileExistsError("现有非空目录没有 run.json；请选择新的运行目录")
        root.mkdir(parents=True, exist_ok=True)
        record = {"schema": "short-drama.run/v1", "episode_id": storyboard["episode_id"], "inputs": signature,
                  "technical_test": mode == "mock" or audio_mode == "mock", "tasks": {}, "status": "initialized"}
    record["execution_context"] = context
    record["technical_test"] = mode == "mock" or audio_mode == "mock"
    record["mock_video"] = mode == "mock"
    record["mock_audio"] = audio_mode == "mock"
    record["speech_status"] = "test_tones_not_speech" if audio_mode == "mock" else "local_audio_requires_listening_review"

    def checkpoint(stage: str, status: str = "succeeded", **details) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        record["tasks"][stage] = {"status": status, "updated_at": timestamp, **details}
        record["status"] = status if status in ("paused", "failed", "waiting_video") else stage
        record["updated_at"] = timestamp
        write_json(record_path, record)
        with (root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": timestamp, "stage": stage, "status": status, **details}, ensure_ascii=False) + "\n")

    checkpoint("validation", continuity_warnings=continuity["warnings"])
    write_json(root / "continuity.json", continuity)
    write_json(root / "storyboard.json", storyboard)
    checkpoint("storyboard", path=str(root / "storyboard.json"))
    if mode == "live":
        approval = load_json(approval_file) if approval_file and Path(approval_file).is_file() else {}
        creative = approval.get("creative", {})
        if creative.get("approved") is not True or any(creative.get(key) != signature[key] for key in ("script_sha256", "characters_sha256")):
            checkpoint("creative_review", "paused", reason="需要用户确认当前剧本和人物档案哈希；尚未提交模型任务")
            return record
    checkpoint("creative_review", "mock_only" if mode == "mock" else "succeeded", note="Mock 技术测试不等于创意批准" if mode == "mock" else "批准绑定当前输入哈希")
    if mode == "live" and project_workspace is None:
        checkpoint("video", "paused", reason="需要所有集共享的project_workspace全剧预算账本")
        return record
    engine = VideoEngine(engine_workspace, mode=mode, provider=provider, reference_root=reference_root,
                         storage_root=storage_root, model_config=model_config, approval_file=approval_file, budgets=budgets)
    record["execution_context"]["ledger_id"] = engine.state.ledger_id
    checkpoint("ledger", ledger_id=engine.state.ledger_id, note="首次提交前持久化账本身份；恢复时先只读核验")
    plan = engine.plan(storyboard)
    write_json(root / "video-plan.json", {"episode_id": storyboard["episode_id"], "mode": mode, "jobs": plan})
    try:
        videos = engine.run(storyboard, max_jobs=max_jobs)
    except LiveBlockedError as error:
        checkpoint("video", "paused", reason=str(error))
        return record
    write_json(root / "video-result.json", videos)
    if not videos["all_succeeded"]:
        statuses = {job["shot_id"]: job["status"] for job in videos["jobs"]}
        terminal = {"failed", "retry_exhausted", "artifact_invalid"}
        paused = {"submission_unknown", "blocked"}
        status = "paused" if paused.intersection(statuses.values()) else "failed" if terminal.intersection(statuses.values()) else "waiting_video"
        checkpoint("video", status, jobs=statuses, note="结果不明的提交需人工对账；耗尽重试的任务不会无限重试")
        return record
    checkpoint("video", estimated_cost=videos["estimated_cost"], currency=videos["currency"], jobs=len(videos["jobs"]))

    audio_record_path = root / "audio-result.json"
    previous_audio = record["tasks"].get("audio", {})
    source_hashes = _source_audio_hashes(storyboard, reference_root, audio_mode)
    if audio_record_path.is_file() and previous_audio.get("source_hashes", {}) == source_hashes and previous_audio.get("manifest_sha256") == file_hash(audio_record_path) and _same_media(previous_audio.get("checksums", {})):
        audio = load_json(audio_record_path)
    else:
        audio = build_audio(storyboard, characters, _next_directory(root, "audio"), mode=audio_mode, asset_root=asset_root or project_root())
        write_json(audio_record_path, audio)
    checkpoint("audio", checksums=_media_checksums(audio), source_hashes=source_hashes, manifest_sha256=file_hash(audio_record_path), notice=audio.get("notice"))
    timeline = build_timeline(storyboard, videos, audio, intro_frames=intro_frames, outro_frames=outro_frames,
                              title=storyboard.get("title", storyboard["episode_id"]),
                              subtitle="本地占位素材 · 测试音调 · 非AI剧情成片" if mode == "mock" else "测试音调 · 非真实配音 · 制作预览" if audio_mode == "mock" else "制作预览 · 等待人工审片")
    timeline["technical_test"] = record["technical_test"]
    timeline_path = root / "timeline.json"
    write_json(timeline_path, timeline)
    (root / "subtitles.srt").write_text(timeline_srt(timeline), encoding="utf-8")
    checkpoint("timeline", path=str(timeline_path), sha256=file_hash(timeline_path), duration_frames=timeline["duration_frames"])
    if not render:
        record["status"] = "ready_to_render"
        write_json(record_path, record)
        return record

    prior_render = record["tasks"].get("render", {})
    previous = Path(prior_render["path"]) if prior_render.get("path") else None
    timeline_hash = file_hash(timeline_path)
    if previous and previous.is_file() and prior_render.get("sha256") == file_hash(previous) and prior_render.get("timeline_sha256") == timeline_hash:
        candidate = previous
    else:
        candidate = Path(output).resolve() if output else _next_video(root, storyboard["episode_id"])
        checkpoint("render", "running", path=str(candidate), timeline_sha256=timeline_hash)
        try:
            intermediate_root = root / "remotion"
            intermediate_root.mkdir(exist_ok=True)
            intermediate = _next_video(intermediate_root, storyboard["episode_id"])
            render_timeline(timeline_path, intermediate)
            normalize_media(intermediate, candidate, width=timeline["width"], height=timeline["height"], fps=timeline["fps"])
            checkpoint("postproduction", source=str(intermediate), source_sha256=file_hash(intermediate), output=str(candidate), sample_rate=48000)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            checkpoint("render", "failed", reason=f"本地渲染未完成: {type(error).__name__}")
            raise
    checkpoint("render", path=str(candidate), sha256=file_hash(candidate), timeline_sha256=timeline_hash)
    quality = qc_video(candidate, timeline)
    final_audio = inspect_audio(candidate, timeline["duration_frames"] / timeline["fps"], tolerance=.15)
    quality["audio_loudness"] = final_audio
    quality["errors"].extend(final_audio["errors"])
    quality["warnings"].extend(final_audio["warnings"])
    quality["passed"] = not quality["errors"]
    write_json(root / "quality.json", quality)
    checkpoint("quality", "succeeded" if quality["passed"] else "failed", passed=quality["passed"], errors=quality["errors"], warnings=quality.get("warnings", []))
    record["status"] = "completed" if quality["passed"] else "quality_failed"
    record["output"] = str(candidate)
    record["human_review_required"] = quality.get("manual_checks", [])
    write_json(record_path, record)
    return record


@contextmanager
def run_lock(run_dir: Path, *, allow_untracked: bool = False):
    """Acquire an OS-released SQLite lock before mutating one run directory.

    The lock survives ordinary files as a small DB; the OS releases its live
    transaction on interruption. No stale PID deletion or wall-clock timeout
    can let a second worker overwrite an active run.
    """
    path = Path(run_dir)
    if path.is_symlink():
        raise ValueError("运行目录不能是符号链接")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    allowed = {".pipeline-lock.sqlite3", ".pipeline-lock.sqlite3-journal"}
    if not allow_untracked and not (path / "run.json").exists() and any(item.name not in allowed for item in path.iterdir()):
        raise FileExistsError("现有非空目录没有 run.json；请选择新的运行目录")
    connection = sqlite3.connect(path / ".pipeline-lock.sqlite3", timeout=.1)
    try:
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            raise RuntimeError("该运行目录正由另一个worker处理；请稍后查看状态并恢复") from error
        yield path
    finally:
        connection.close()


def run_pipeline(script_path: Path, characters_path: Path, run_dir: Path, **options) -> dict:
    with run_lock(run_dir) as path:
        return _run_pipeline(script_path, characters_path, path, **options)
