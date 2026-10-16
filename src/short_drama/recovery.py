"""Explicit offline rebinding of an already restored production run.

This is neither backup nor remote recovery: the caller must stop workers and
restore the latest consistent SQLite snapshot and every media file first. No
provider submit, poll, download or media generation is performed here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from typing import Any

from .io import file_hash, load_json, write_json
from .pipeline import run_lock
from .state import StateStore
from .storage import LocalStorage
from .timeline import timeline_srt
from .video_engine import VideoEngine


_PATH_KEYS = {"path", "srt_path", "state_path", "engine_workspace", "reference_root",
              "storage_root", "source", "output", "filename", "asset_root"}
_RECORDS = ("video-plan.json", "video-result.json", "audio-result.json", "timeline.json",
            "quality.json", "continuity.json", "storyboard.json", "verification.json")


def _json_hash(document: Any) -> str:
    content = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _absolute(value: Any) -> bool:
    return isinstance(value, str) and Path(value).is_absolute()


def _previous_root(record: dict, explicit: Path | None) -> Path:
    inferred = {Path(task["path"]).parent for name, task in record.get("tasks", {}).items()
                if name in {"storyboard", "timeline"} and _absolute(task.get("path"))}
    if explicit is not None:
        root = Path(explicit).absolute()
        if inferred and inferred != {root}:
            raise ValueError("previous_run_root 与原制作检查点不一致")
        return root
    if len(inferred) != 1:
        raise ValueError("不能唯一确定原 run 根目录，请显式指定 previous_run_root")
    return inferred.pop()


class _Mapper:
    def __init__(self, roots: list[tuple[Path, Path]]):
        unique: dict[Path, Path] = {}
        for old, new in roots:
            old, new = Path(old).absolute(), Path(new).resolve()
            if old in unique and unique[old] != new:
                raise ValueError("同一原根目录不能映射到不同恢复目录")
            unique[old] = new
        self.roots = sorted(unique.items(), key=lambda item: len(item[0].parts), reverse=True)

    def path(self, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            return value
        # Work from the saved lexical path; old roots need not exist anymore.
        if ".." in path.parts:
            raise ValueError("恢复记录包含不安全路径")
        for old, new in self.roots:
            if path.is_relative_to(old):
                mapped = new / path.relative_to(old)
                if not mapped.resolve().is_relative_to(new):
                    raise ValueError("恢复路径通过符号链接越出已批准根目录")
                return str(mapped.resolve())
        raise ValueError(f"存在根目录映射以外的绝对路径，拒绝隐式迁移: {value}")

    def document(self, value: Any, key: str | None = None) -> Any:
        if isinstance(value, list):
            return [self.document(item, key) for item in value]
        if isinstance(value, dict):
            return {(self.path(name) if key == "checksums" and _absolute(name) else name):
                    self.document(item, name) for name, item in value.items()}
        if key in _PATH_KEYS and _absolute(value):
            return self.path(value)
        return value


def restore_run(run_dir: Path, new_engine_workspace: Path, new_storage_root: Path, *,
                new_asset_root: Path, previous_run_root: Path | None = None) -> dict:
    """Validate and rebind copied run metadata; preserve task IDs and media.

    All destination roots must already exist. ``run_dir`` contains the
    restored run.json; the engine root contains the original UUID-bearing ledger.
    The old run root is inferred from saved checkpoints or provided explicitly.
    Keep another backup before this metadata migration: individual JSON files are
    atomically written, but SQLite plus multiple files are not one transaction.
    Workers sharing this project ledger must be stopped by the operator.
    """
    destinations = [Path(item) for item in (run_dir, new_engine_workspace, new_storage_root, new_asset_root)]
    if any(path.is_symlink() or not path.is_dir() for path in destinations):
        raise ValueError("恢复根目录必须已经存在且不能是符号链接；本命令不创建或复制备份")
    root, engine_root, storage_root, asset_root = [path.resolve() for path in destinations]
    with run_lock(root):
        journal_path = root / ".restore-plan.json"
        journal = load_json(journal_path) if journal_path.is_file() else None
        targets = {"run_dir": str(root), "engine_workspace": str(engine_root),
                   "storage_root": str(storage_root), "asset_root": str(asset_root)}
        pending = journal if journal and journal.get("status") == "validated" else None
        if pending and pending.get("targets") != targets:
            raise ValueError("有未完成恢复计划；必须先按其原目标目录完成恢复")
        if pending:
            for name, old in pending["original_documents"].items():
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name or not (root / relative).resolve().is_relative_to(root):
                    raise ValueError("恢复计划含不安全元数据路径")
                current = load_json(root / name)
                if current != old and current != pending["mapped_documents"][name]:
                    raise ValueError("未完成恢复期间元数据被其他任务修改；停止并人工核对")
        record = deepcopy(pending["original_documents"]["run.json"]) if pending else load_json(root / "run.json")
        context = record.get("execution_context", {})
        ledger_id = context.get("ledger_id")
        database = engine_root / "state/video-jobs.sqlite3"
        if not ledger_id or StateStore.read_ledger_id(database) != ledger_id:
            raise ValueError("恢复账本UUID不匹配或丢失，禁止创建新账本继续已有任务")
        if not all(_absolute(context.get(name)) for name in ("engine_workspace", "storage_root", "reference_root")):
            raise ValueError("原运行缺少明确的执行根目录，需人工核对后迁移")
        old_root = _previous_root(record, previous_run_root)
        mapper = _Mapper([(old_root, root), (Path(context["engine_workspace"]), engine_root),
                          (Path(context["storage_root"]), storage_root),
                          (Path(context["reference_root"]), asset_root)])
        documents = deepcopy(pending["original_documents"]) if pending else {name: load_json(root / name) for name in _RECORDS if (root / name).is_file()}
        documents["run.json"] = record
        # Inner manifests are useful provenance, not disposable caches. Move their
        # track/SRT and inspection paths along with the top-level audio result.
        for manifest in (() if pending else root.glob("audio-v*/audio-manifest.json")):
            if manifest.is_symlink():
                raise ValueError("音频 manifest 不能是符号链接")
            documents[str(manifest.relative_to(root))] = load_json(manifest)
        hashes: dict[str, str] = {}

        def verify(old_path: str, digest: str, *, size: int | None = None) -> None:
            target = Path(mapper.path(old_path))
            actual = file_hash(target) if target.is_file() else None
            if pending and target.is_relative_to(root):
                name = str(target.relative_to(root))
                if name in pending["original_hashes"]:
                    # A prior attempt may already have written the target JSON.
                    # Its exact old/target content was checked above. Media is
                    # never virtualized and always checked from restored bytes.
                    actual = pending["original_hashes"][name]
            if not target.is_file() or not isinstance(digest, str) or actual != digest:
                raise ValueError(f"恢复文件缺失或SHA-256不匹配: {target}")
            if size is not None and target.stat().st_size != size:
                raise ValueError(f"恢复文件大小不匹配: {target}")
            if old_path in hashes and hashes[old_path] != digest:
                raise ValueError("同一恢复文件存在矛盾哈希")
            hashes[old_path] = digest

        def verify_document(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    verify_document(item)
            elif isinstance(value, dict):
                if _absolute(value.get("path")) and value.get("sha256"):
                    verify(value["path"], value["sha256"], size=value.get("size_bytes"))
                if _absolute(value.get("source")) and value.get("source_sha256"):
                    verify(value["source"], value["source_sha256"])
                for path, digest in value.get("checksums", {}).items():
                    verify(path, digest)
                for item in value.values():
                    verify_document(item)

        for document in documents.values():
            verify_document(document)
        if "timeline.json" in documents:
            subtitle_path = root / "subtitles.srt"
            if not subtitle_path.is_file() or subtitle_path.read_text(encoding="utf-8") != timeline_srt(documents["timeline.json"]):
                raise ValueError("恢复后的最终SRT缺失或与时间线不一致")
            verify(str(old_root / "subtitles.srt"), file_hash(subtitle_path))
        tasks = record.get("tasks", {})
        audio_path = root / "audio-result.json"
        if tasks.get("audio", {}).get("manifest_sha256"):
            verify(str(old_root / "audio-result.json"), tasks["audio"]["manifest_sha256"])
        source_hashes = tasks.get("audio", {}).get("source_hashes", {})
        for relative, digest in source_hashes.items():
            if relative != "asset_root":
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("源音频哈希包含不安全相对路径")
                verify(str(Path(context["reference_root"]) / path), digest)
        old_timeline_hash = (pending["original_hashes"]["timeline.json"] if pending else file_hash(root / "timeline.json")) if "timeline.json" in documents else None
        prior_render = tasks.get("render", {})
        if prior_render.get("timeline_sha256") and prior_render["timeline_sha256"] != old_timeline_hash:
            raise ValueError("成片对应的原时间线哈希不匹配，拒绝标记为可复用")

        # Identity checks precede constructing VideoEngine, which may migrate a
        # legacy DB. An absent/empty/wrong ledger can never be silently created.
        engine = VideoEngine(engine_root, storage_root=storage_root, reference_root=asset_root)
        actual_jobs = engine.state.list_jobs()
        jobs = deepcopy(pending["original_jobs"]) if pending else actual_jobs
        by_key = {job["job_key"]: job for job in actual_jobs}
        previous_jobs = documents.get("video-result.json", {}).get("jobs", [])
        for old in previous_jobs:
            restored = by_key.get(old["job_key"])
            identity_keys = ("request_hash", "provider_job_id", "attempts")
            if restored is None or any(restored.get(key) != old.get(key) for key in identity_keys):
                raise ValueError("恢复账本未保留原任务身份/提交次数；先与服务商对账")
        if pending:
            for old in jobs:
                current = by_key.get(old["job_key"])
                if current is None or any(current.get(key) != old.get(key) for key in ("request_hash", "provider_job_id", "attempts", "status")):
                    raise ValueError("未完成恢复期间共享任务账本已变化；停止并人工核对")
        # Verify all episodes in a shared ledger before any mutation. The storage
        # rebind is project-wide; no other episode is silently omitted.
        restored_storage = LocalStorage(storage_root)
        for job in jobs:
            if job.get("artifact"):
                restored_storage.rebind(job["artifact"])
            for reference in job.get("request", {}).get("reference_images", []):
                if reference.get("path") and reference.get("sha256"):
                    verify(reference["path"], reference["sha256"])

        mapped = {name: mapper.document(deepcopy(document)) for name, document in documents.items()}
        mapped_jobs = {job["job_key"]: mapper.document(deepcopy(job)) for job in jobs}
        # Validate every path conversion before touching the ledger. Historical
        # JSONL entries remain intact; append one explicit recovery event instead.
        new_record = mapped["run.json"]
        new_record["execution_context"] = {**context, "engine_workspace": str(engine_root),
                                           "storage_root": str(storage_root),
                                           "reference_root": str(asset_root), "ledger_id": ledger_id}
        if "video-result.json" in mapped:
            result = mapped["video-result.json"]
            result["state_path"] = str(database)
            keys = {job["job_key"] for job in previous_jobs}
            result["jobs"] = [job for job in mapped_jobs.values() if job["job_key"] in keys]
        # Persist dependencies first, then recompute the hashes in their consuming
        # checkpoints. Media hashes do not change; only metadata paths do.
        if "audio-result.json" in mapped:
            new_record["tasks"]["audio"]["manifest_sha256"] = _json_hash(mapped["audio-result.json"])
        if "timeline.json" in mapped:
            new_hash = _json_hash(mapped["timeline.json"])
            if "timeline" in new_record["tasks"]:
                new_record["tasks"]["timeline"]["sha256"] = new_hash
            if prior_render.get("timeline_sha256"):
                new_record["tasks"]["render"]["timeline_sha256"] = new_hash
        recovered_at = datetime.now(timezone.utc).isoformat()
        new_record["recovery"] = {"at": recovered_at, "previous_run_root": str(old_root),
                                  "verified_files": len(hashes), "offline": True,
                                  "latest_snapshot_confirmed_by_operator_required": True}
        if pending:
            # Preserve the target timestamp and exact serialized target plan.
            mapped = pending["mapped_documents"]
            new_record = mapped["run.json"]
            mapped_jobs = {job["job_key"]: job for job in pending["mapped_jobs"]}
        else:
            journal = {"schema": "short-drama.restore-plan/v1", "status": "validated", "targets": targets,
                       "original_documents": documents, "original_jobs": jobs,
                       "original_hashes": {name: file_hash(root / name) for name in documents},
                       "mapped_documents": mapped, "mapped_jobs": list(mapped_jobs.values())}
            write_json(journal_path, journal)
        rebound = engine.rebind_storage(storage_root)
        for job in rebound:
            mapped_job = mapped_jobs[job["job_key"]]
            if mapped_job != job:
                engine.state.save(deepcopy(mapped_job))
        for name, document in mapped.items():
            if name != "run.json":
                write_json(root / name, document)
        write_json(root / "run.json", new_record)
        with (root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": recovered_at, "stage": "restore_run", "status": "succeeded",
                                     "previous_run_root": str(old_root), "ledger_id": ledger_id,
                                     "network_called": False}, ensure_ascii=False) + "\n")
        journal["status"] = "completed"
        write_json(journal_path, journal)
        return {"run_dir": str(root), "ledger_id": ledger_id, "rebound_jobs": len(rebound),
                "verified_files": len(hashes), "network_called": False,
                "backup_created": False, "status": new_record["status"]}
