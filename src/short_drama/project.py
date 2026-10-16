"""Create production workspaces without replacing existing creative material."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


def _write_new(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def initialize_series(
    root: Path,
    slug: str,
    *,
    title: str,
    genre: str = "待确认",
    episodes: int = 10,
    minutes: float = 2,
    fps: int = 30,
) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
        raise ValueError("系列目录名必须是1至63位小写字母、数字或连字符")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("剧名不能为空")
    if isinstance(episodes, bool) or not isinstance(episodes, int) or not 1 <= episodes <= 999:
        raise ValueError("集数必须在1至999之间")
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("每集分钟数必须是有限正数")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise ValueError("FPS必须在1至120之间")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / slug
    target.mkdir(exist_ok=False)
    (target / "episodes").mkdir()
    _write_new(target / "series.json", {
        "schema_version": "short-drama.series/v1",
        "title": title,
        "genre": genre,
        "episodes": episodes,
        "target_duration_seconds": minutes * 60,
        "fps": fps,
        "width": 1080,
        "height": 1920,
        "aspect_ratio": "9:16",
        "status": "draft",
        "creative_review": "required",
        "generation_mode": "mock",
    })
    _write_new(target / "characters.json", {"characters": []})
    (target / "series-bible.md").write_text(
        f"# {title}\n\n类型：{genre}\n\n世界观、人物目标、关系、季结构和结局方向：待创作确认。\n",
        encoding="utf-8",
    )
    return target


def initialize_episode(series_dir: Path, episode_id: str) -> Path:
    if not re.fullmatch(r"EP\d{3}", episode_id):
        raise ValueError("剧集编号格式应为EP001")
    series_dir = Path(series_dir).resolve()
    config = json.loads((series_dir / "series.json").read_text(encoding="utf-8"))
    target = series_dir / "episodes" / episode_id
    if (series_dir / "episodes").is_symlink() or not target.parent.resolve().is_relative_to(series_dir):
        raise ValueError("分集目录不得通过符号链接越出系列目录")
    target.parent.mkdir(exist_ok=True)
    target.mkdir(exist_ok=False)
    common = {
        "episode_id": episode_id,
        "aspect_ratio": config["aspect_ratio"],
        "fps": config["fps"],
        "width": config["width"],
        "height": config["height"],
    }
    _write_new(target / "script.json", {**common, "title": f"{config['title']} · {episode_id}", "scenes": []})
    _write_new(target / "storyboard.json", {**common, "shots": []})
    _write_new(target / "tasks.json", {
        "episode_id": episode_id,
        "status": "draft",
        "tasks": [
            {"stage": stage, "status": "pending"}
            for stage in ("creative_review", "storyboard", "video", "audio", "timeline", "render", "quality_review")
        ],
    })
    (target / "script.md").write_text(f"# {episode_id}\n\n草稿待创作。结构化镜头与对白写入同目录 script.json。\n", encoding="utf-8")
    return target
