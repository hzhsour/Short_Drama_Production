"""Chinese command-line entry point for bounded production work."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from .audio import build_audio, PiperLocalTTSAdapter
from .continuity import check_continuity, validate_characters
from .io import file_hash, load_json, write_json
from .media import normalize_media, qc_video
from .pipeline import project_root, render_timeline, run_lock, run_pipeline
from .project import initialize_episode, initialize_series
from .script import script_to_storyboard, validate_script
from .state import StateStore
from .timeline import build_timeline, timeline_srt
from .validation import validate_project, validate_storyboard
from .video_engine import EngineError, VideoEngine


def _emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _engine_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--approval", type=Path, help="外部人工批准文件，工具不会自动创建批准")
    parser.add_argument("--budgets", type=Path, help="per_task/per_episode/project/currency JSON")
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--storage-root", type=Path, help="可挂载私有外部存储的本地目录")
    parser.add_argument("--project-workspace", type=Path, help="整部剧共享的引擎账本目录；Live必填")


def _provider_config(args) -> dict | None:
    catalog = args.catalog or project_root() / "config" / "providers.json"
    providers = load_json(catalog)["providers"]
    if args.provider not in providers:
        raise ValueError(f"未注册模型: {args.provider}")
    if args.mode == "mock" and args.provider != "mock":
        raise ValueError("Mock模式请使用mock提供商；官方模型只做plan或明确批准后的Live")
    if args.mode == "live" and args.provider == "mock":
        raise ValueError("Live模式必须选择具体官方提供商；技术测试请使用Mock")
    return providers[args.provider]


def _engine(args) -> VideoEngine:
    if args.mode == "live" and args.command != "plan" and args.project_workspace is None:
        raise ValueError("Live需要--project-workspace，将各集预算计入同一个全剧账本")
    return VideoEngine(args.project_workspace or args.run_dir / "engine", mode=args.mode, provider=args.provider,
                       reference_root=args.asset_root or project_root(), storage_root=args.storage_root,
                       model_config=_provider_config(args), approval_file=args.approval,
                       budgets=load_json(args.budgets) if args.budgets else None)


def _generate_once(args, board: dict) -> dict:
    # Persist identity before any provider submit, including when the process
    # is interrupted before video-result.json can be written.
    with run_lock(args.run_dir, allow_untracked=True) as directory:
        if (directory / "run.json").is_file():
            raise ValueError("完整管线目录请用run或demo恢复，不能混用generate入口")
        workspace = (args.project_workspace or directory / "engine").resolve()
        context = {"engine_workspace": str(workspace), "reference_root": str((args.asset_root or project_root()).resolve()),
                   "storage_root": str((args.storage_root or workspace / "artifacts/video").resolve()),
                   "mode": args.mode, "provider": args.provider}
        context_path = directory / "engine-context.json"
        if context_path.is_file():
            previous = load_json(context_path)
            if any(previous.get(key) != value for key, value in context.items()):
                raise ValueError("生成上下文已变化；请先恢复原账本并显式重绑")
            ledger_id = previous.get("ledger_id")
            if not ledger_id or StateStore.read_ledger_id(workspace / "state/video-jobs.sqlite3") != ledger_id:
                raise ValueError("原任务账本丢失或UUID不符；禁止自动创建新账本后重复提交")
        elif args.mode == "live" and (directory / "video-result.json").is_file():
            raise ValueError("旧Live结果缺少账本身份；请人工核对后迁移")
        engine = _engine(args)
        context["ledger_id"] = engine.state.ledger_id
        write_json(context_path, context)
        result = engine.run(board, max_jobs=args.max_jobs)
        write_json(directory / "video-result.json", result)
        return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="short-drama", description="中文短剧制作工具；默认Mock，不调用付费API")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-series", help="创建系列草稿，不覆盖原项目")
    init.add_argument("slug")
    init.add_argument("--root", type=Path, default=Path("production/series"))
    init.add_argument("--title", required=True)
    init.add_argument("--genre", default="待确认")
    init.add_argument("--episodes", type=int, default=10)
    init.add_argument("--minutes", type=float, default=2)
    episode = commands.add_parser("init-episode", help="创建独立分集草稿与任务表")
    episode.add_argument("series_dir", type=Path)
    episode.add_argument("episode_id")
    validation = commands.add_parser("validate", help="校验项目、人物、剧本或分镜")
    validation.add_argument("--characters", type=Path)
    validation.add_argument("--script", type=Path)
    validation.add_argument("--storyboard", type=Path)
    validation.add_argument("--check-reference-files", action="store_true")
    conversion = commands.add_parser("convert-script", help="结构化剧本JSON转分镜；不代替创意写作")
    conversion.add_argument("script", type=Path)
    conversion.add_argument("--characters", type=Path)
    conversion.add_argument("--output", type=Path, required=True)
    for name in ("plan", "generate"):
        command = commands.add_parser(name, help="本地估算视频任务" if name == "plan" else "执行一轮有界任务并持久化")
        command.add_argument("storyboard", type=Path)
        command.add_argument("--run-dir", type=Path, required=True)
        command.add_argument("--max-jobs", type=int)
        command.add_argument("--episodes", type=int, default=1, help="plan按相同分集镜头表投影全剧估算")
        _engine_flags(command)
    status = commands.add_parser("status", help="读取运行和已完成镜头状态")
    status.add_argument("--run-dir", type=Path, required=True)
    rebind = commands.add_parser("rebind-storage", help="离线按key和SHA重绑已恢复的备份素材路径")
    rebind.add_argument("project_workspace", type=Path)
    rebind.add_argument("new_storage_root", type=Path)
    rebind.add_argument("--run-dir", type=Path, help="同时离线迁移此run的后端身份；须有已恢复账本")
    rebind.add_argument("--asset-root", type=Path)
    audio = commands.add_parser("audio", help="Mock测试音/本地录音/已配置Piper与字幕")
    audio.add_argument("storyboard", type=Path)
    audio.add_argument("--characters", type=Path, required=True)
    audio.add_argument("--output-dir", type=Path, required=True)
    audio.add_argument("--mode", choices=("mock", "local"), default="mock")
    audio.add_argument("--asset-root", type=Path)
    audio.add_argument("--piper-models", type=Path, help="voice profile到本地ONNX模型路径的JSON对象")
    audio.add_argument("--piper-executable", default="piper")
    timeline = commands.add_parser("timeline", help="连接镜头素材、声音和字幕，导出Remotion清单")
    timeline.add_argument("storyboard", type=Path)
    timeline.add_argument("--videos", type=Path, required=True)
    timeline.add_argument("--audio", type=Path, required=True)
    timeline.add_argument("--output", type=Path, required=True)
    render = commands.add_parser("render", help="本地Remotion渲染；禁止覆盖输出")
    render.add_argument("timeline", type=Path)
    render.add_argument("output", type=Path)
    quality = commands.add_parser("quality", help="解码与交付规格质检")
    quality.add_argument("video", type=Path)
    quality.add_argument("--timeline", type=Path)
    normalize = commands.add_parser("normalize", help="本地帧率/采样率/H.264规格整理")
    normalize.add_argument("source", type=Path)
    normalize.add_argument("destination", type=Path)
    analysis = commands.add_parser("analyze", help="本地媒体/静音/像素变化分析，不做ASR")
    analysis.add_argument("video", type=Path)
    analysis.add_argument("--silence", action="store_true")
    analysis.add_argument("--scenes", action="store_true")
    packaging = commands.add_parser("packaging", help="生成独立包装资产，Remotion管理主时间线")
    packaging.add_argument("output", type=Path)
    packaging.add_argument("--title", required=True)
    packaging.add_argument("--backend", choices=("ffmpeg", "hyperframes"), default="ffmpeg")
    packaging.add_argument("--seconds", type=float, default=2)
    packaging.add_argument("--project-dir", type=Path)
    run = commands.add_parser("run", help="结构化剧本到本地成片的有界、可恢复工作流")
    run.add_argument("script", type=Path)
    run.add_argument("--characters", type=Path, required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--render", action="store_true")
    run.add_argument("--output", type=Path)
    run.add_argument("--max-jobs", type=int)
    run.add_argument("--audio-mode", choices=("mock", "local"), default="mock")
    _engine_flags(run)
    demo = commands.add_parser("demo", help="仅用已公开虚构文本跑Mock技术测试")
    demo.add_argument("--run-dir", type=Path, default=Path("runs/technical-demo"))
    demo.add_argument("--render", action="store_true")
    demo.add_argument("--max-jobs", type=int)
    export = commands.add_parser("export-metadata", help="显式导出文本摘要；不会自动Git提交或上传")
    export.add_argument("run_dir", type=Path)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--confirm-public", action="store_true", help="仅在已确认内容可公开时用于非技术任务")
    commands.add_parser("doctor", help="检查本地工具，不获取凭证或请求API")
    commands.add_parser("check", help="运行全部自动代码检查；渲染用preview/demo另行执行")
    return root


def _execute(args) -> int:
    command = args.command
    if command == "init-series":
        _emit({"created": str(initialize_series(args.root, args.slug, title=args.title, genre=args.genre, episodes=args.episodes, minutes=args.minutes)), "status": "creative_review_required"})
    elif command == "init-episode":
        _emit({"created": str(initialize_episode(args.series_dir, args.episode_id)), "mode": "draft"})
    elif command == "validate":
        characters = load_json(args.characters) if args.characters else None
        errors = []
        if characters is not None:
            errors += validate_characters(characters, root=project_root() if args.check_reference_files else None)
        if args.script:
            errors += validate_script(load_json(args.script), characters)
        if args.storyboard:
            board = load_json(args.storyboard)
            errors += validate_storyboard(board, characters)
            if not errors and characters is not None:
                continuity = check_continuity(board, characters)
                errors += continuity["errors"]
        if not any((args.characters, args.script, args.storyboard)):
            errors = validate_project(project_root())
        _emit({"passed": not errors, "errors": errors})
        return 1 if errors else 0
    elif command == "convert-script":
        board = script_to_storyboard(load_json(args.script), load_json(args.characters) if args.characters else None)
        write_json(args.output, board, overwrite=False)
        _emit({"output": str(args.output.resolve()), "shots": len(board["shots"])})
    elif command in ("plan", "generate"):
        output_path = args.run_dir / ("video-plan.json" if command == "plan" else "video-result.json")
        if output_path.resolve() == args.storyboard.resolve():
            raise ValueError("结果路径与输入分镜相同，禁止覆盖输入")
        board = load_json(args.storyboard)
        errors = validate_storyboard(board)
        if errors:
            raise ValueError("; ".join(errors))
        if command == "plan":
            engine = _engine(args)
            if args.episodes < 1:
                raise ValueError("episodes必须为正整数")
            jobs = engine.plan(board)
            known = all(job.get("estimated_cost") is not None for job in jobs)
            total = sum((Decimal(job["estimated_cost"]) for job in jobs), Decimal(0)) if known else None
            result = {"episode_id": board["episode_id"], "mode": args.mode, "jobs": jobs,
                      "episode_estimated_cost": str(total) if total is not None else None,
                      "projected_same_episode_count": args.episodes,
                      "project_estimated_cost": str(total * args.episodes) if total is not None else None,
                      "notice": "价格未知时为null；文档快照不是账户报价或付费批准"}
        else:
            result = _generate_once(args, board)
        if command == "plan":
            write_json(output_path, result)
        _emit(result)
        return 0 if command == "plan" or result["all_succeeded"] else 2
    elif command == "status":
        root = args.run_dir.resolve()
        record = load_json(root / "run.json") if (root / "run.json").exists() else {"status": "not_started"}
        video = load_json(root / "video-result.json") if (root / "video-result.json").exists() else {}
        path = Path(video.get("state_path", root / "engine/state/video-jobs.sqlite3"))
        jobs = StateStore(path).list_jobs() if path.is_file() else []
        for job in jobs:
            if job.get("status") == "succeeded":
                artifact = job.get("artifact", {})
                media = Path(artifact["path"]) if artifact.get("path") else None
                healthy = bool(media and media.is_file() and file_hash(media) == artifact.get("sha256"))
                job["artifact_health"] = "verified" if healthy else "missing_or_changed"
                if not healthy:
                    job["observed_status"] = "artifact_invalid"
        _emit({"run": record, "jobs": [job for job in jobs if not record.get("episode_id") or job["episode_id"] == record["episode_id"]]})
    elif command == "rebind-storage":
        if not (args.project_workspace / "state/video-jobs.sqlite3").is_file():
            raise FileNotFoundError("请先恢复原项目SQLite账本，不能用空状态识别已收费任务")
        if args.run_dir:
            with run_lock(args.run_dir, allow_untracked=True) as directory:
                is_pipeline = (directory / "run.json").is_file()
                record_path = directory / "run.json" if is_pipeline else directory / "engine-context.json"
                record = load_json(record_path)
                previous_context = record.get("execution_context", {}) if is_pipeline else record
                ledger_id = previous_context.get("ledger_id")
                if not ledger_id or StateStore.read_ledger_id(args.project_workspace / "state/video-jobs.sqlite3") != ledger_id:
                    raise ValueError("恢复账本UUID与原运行不符；禁止以空账本重绑收费任务")
                engine = VideoEngine(args.project_workspace)
                previous = load_json(directory / "video-result.json") if (directory / "video-result.json").exists() else {"jobs": []}
                for old in previous["jobs"]:
                    restored = engine.state.get(old["job_key"])
                    if not restored or any(restored.get(key) != old.get(key) for key in ("request_hash", "provider_job_id")):
                        raise ValueError("恢复账本不包含原任务身份，禁止重绑或创建新收费任务")
                jobs = engine.rebind_storage(args.new_storage_root)
                context = {**previous_context, "engine_workspace": str(args.project_workspace.resolve()), "storage_root": str(args.new_storage_root.resolve()), "reference_root": str((args.asset_root or project_root()).resolve()), "ledger_id": ledger_id}
                if is_pipeline:
                    record["execution_context"] = context
                else:
                    record = context
                write_json(record_path, record)
                previous["state_path"] = str(engine.state.path)
                if (directory / "video-result.json").is_file():
                    previous["jobs"] = [job for job in jobs if not is_pipeline or job["episode_id"] == record["episode_id"]]
                    write_json(directory / "video-result.json", previous)
                _emit({"rebound": len(jobs), "run_dir": str(directory), "network_called": False})
        else:
            engine = VideoEngine(args.project_workspace)
            _emit(engine.rebind_storage(args.new_storage_root))
    elif command == "audio":
        adapter = None
        if args.piper_models:
            if args.mode != "local":
                raise ValueError("Piper需要显式--mode local")
            adapter = PiperLocalTTSAdapter({key: Path(value) for key, value in load_json(args.piper_models).items()}, executable=args.piper_executable)
        _emit(build_audio(load_json(args.storyboard), load_json(args.characters), args.output_dir, mode=args.mode, asset_root=args.asset_root or project_root(), tts_adapter=adapter))
    elif command == "timeline":
        result = build_timeline(load_json(args.storyboard), load_json(args.videos), load_json(args.audio))
        srt = args.output.with_suffix(".srt")
        if srt.exists():
            raise FileExistsError(f"字幕输出已存在: {srt}")
        write_json(args.output, result, overwrite=False)
        with srt.open("x", encoding="utf-8") as handle:
            handle.write(timeline_srt(result))
        _emit({"timeline": str(args.output.resolve()), "subtitles": str(srt.resolve()), "frames": result["duration_frames"]})
    elif command == "render":
        render_timeline(args.timeline, args.output)
        quality = qc_video(args.output, load_json(args.timeline))
        _emit(quality)
        return 0 if quality["passed"] else 1
    elif command == "quality":
        quality = qc_video(args.video, load_json(args.timeline) if args.timeline else None)
        _emit(quality)
        return 0 if quality["passed"] else 1
    elif command == "normalize":
        _emit(normalize_media(args.source, args.destination))
    elif command == "analyze":
        from .analysis import analyze_video
        _emit(analyze_video(args.video, detect_silence=args.silence, detect_scenes=args.scenes))
    elif command == "packaging":
        from .packaging import generate_packaging
        _emit(generate_packaging(args.output, args.title, backend=args.backend, project_dir=args.project_dir, duration_seconds=args.seconds))
    elif command in ("run", "demo"):
        options = {"render": args.render, "max_jobs": args.max_jobs}
        if command == "demo":
            source = project_root() / "examples/technical-demo"
            script, characters = source / "script.json", source / "characters.json"
        else:
            script, characters = args.script, args.characters
            if args.mode == "live" and args.project_workspace is None:
                raise ValueError("Live需要--project-workspace以共享整部剧预算")
            options.update(mode=args.mode, provider=args.provider, audio_mode=args.audio_mode, asset_root=args.asset_root,
                           storage_root=args.storage_root, project_workspace=args.project_workspace, model_config=_provider_config(args),
                           approval_file=args.approval, budgets=load_json(args.budgets) if args.budgets else None, output=args.output)
        result = run_pipeline(script, characters, args.run_dir, **options)
        _emit(result)
        return 2 if result["status"] in ("paused", "waiting_video") else 1 if result["status"] in ("failed", "quality_failed") else 0
    elif command == "export-metadata":
        record = load_json(args.run_dir / "run.json")
        if not record.get("technical_test") and not args.confirm_public:
            raise PermissionError("生产元数据可能包含未公开信息；需要明确确认可公开，工具不会自动上传")
        videos = load_json(args.run_dir / "video-result.json") if (args.run_dir / "video-result.json").exists() else {}
        result = {key: record.get(key) for key in ("schema", "episode_id", "status", "technical_test", "inputs")}
        result["stages"] = {stage: value["status"] for stage, value in record.get("tasks", {}).items()}
        result["artifacts"] = [{"shot_id": job["shot_id"], "status": job["status"], "model_id": job.get("request", {}).get("model_id"),
                                "sha256": (job.get("artifact") or {}).get("sha256"), "storage_key": (job.get("artifact") or {}).get("key")} for job in videos.get("jobs", [])]
        write_json(args.output, result, overwrite=False)
        _emit({"exported": str(args.output.resolve()), "notice": "仅本地导出；提交前仍需人工确认，没有自动Git推送"})
    elif command == "doctor":
        tools = {}
        for name in ("node", "npm", "ffmpeg", "ffprobe", "chromium", "google-chrome", "piper"):
            path = shutil.which(name)
            tools[name] = {"available": path is not None, "path": path}
        _emit({"python": sys.version.split()[0], "tools": tools, "api_keys_inspected": False, "default_mode": "mock"})
    elif command == "check":
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("需要npm")
        return subprocess.run([npm, "run", "check"], cwd=project_root()).returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return _execute(args)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        _emit({"status": "blocked" if isinstance(error, PermissionError) else "error", "error": str(error), "type": type(error).__name__})
        return 2
