"""Produce independent local title assets; never own the episode timeline."""

from __future__ import annotations

import html
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from .media import probe_media


HYPERFRAMES_VERSION = "0.8.164"
GSAP_VERSION = "3.14.2"


def _run_local(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    if not shutil.which(args[0]):
        raise RuntimeError(f"缺少本地依赖: {args[0]}")
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=os.name != "nt")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError(f"本地包装操作超时 ({timeout}s)") from error
    if process.returncode:
        message = (stdout + "\n" + stderr).strip()
        raise RuntimeError(f"本地包装工具失败: {message[-5000:]}")
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _output_path(output: str | Path) -> Path:
    raw = str(output)
    if not raw.strip() or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:[\\/]", raw):
        raise ValueError("包装输出只允许本地路径")
    if raw.startswith(("//", "\\\\")):
        raise ValueError("包装输出禁止网络共享路径")
    requested = Path(raw).expanduser()
    if requested.is_symlink() or requested.exists():
        raise FileExistsError(f"禁止覆盖现有输出: {requested}")
    target = requested.resolve()
    if target.suffix.lower() != ".mp4":
        raise ValueError("包装输出必须是 .mp4")
    return target


def _hyperframes_env() -> dict[str, str]:
    # A local renderer does not need API credentials or proxy credentials.
    allowed = {"PATH", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({
        "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_SKIP_SKILLS": "1",
        "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1", "CI": "1",
    })
    browser = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "chrome") if shutil.which(name)), None)
    if not browser:
        raise RuntimeError("HyperFrames 需要预装 Chromium/Chrome；此接口不自动下载浏览器")
    env["HYPERFRAMES_BROWSER_PATH"] = browser
    env["PRODUCER_HEADLESS_SHELL_PATH"] = browser
    return env


def _cjk_font() -> Path:
    configured = os.environ.get("SHORT_DRAMA_CJK_FONT")
    if configured:
        from .timeline import local_media_path

        return local_media_path(configured)
    if shutil.which("fc-match"):
        candidate = Path(_run_local(["fc-match", "-f", "%{file}", "Noto Sans CJK SC"]).stdout.strip())
        if candidate.is_file():
            return candidate
    raise RuntimeError("缺少本地中文字体；设置 SHORT_DRAMA_CJK_FONT 为已授权的字体文件")


def _render_hyperframes(
    destination: Path, title: str, project_dir: str | Path | None, *, duration: float, width: int, height: int, fps: int,
) -> dict[str, Any]:
    import json

    integration = Path(project_dir).resolve() if project_dir else Path(__file__).resolve().parents[2] / "integrations" / "hyperframes"
    cli = integration / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    gsap = integration / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    template = Path(__file__).resolve().parents[2] / "integrations" / "hyperframes" / "title.html"
    for path in (cli, gsap, template):
        if not path.is_file():
            raise RuntimeError(f"缺少隔离 HyperFrames 依赖或模板: {path}；先按文档 npm ci --ignore-scripts")
    for name, expected in (("hyperframes", HYPERFRAMES_VERSION), ("gsap", GSAP_VERSION)):
        installed = json.loads((integration / "node_modules" / name / "package.json").read_text(encoding="utf-8"))
        if installed.get("version") != expected:
            raise RuntimeError(f"{name} 版本不符，要求固定 {expected}")
    font = _cjk_font()
    if font.suffix.lower() not in {".ttf", ".ttc", ".otf", ".woff", ".woff2"}:
        raise ValueError("中文字体须为本地 TTF/TTC/OTF/WOFF/WOFF2 文件")
    font_name = "title-font" + font.suffix.lower()
    replacements = {
        "__TITLE__": html.escape(title), "__WIDTH__": str(width), "__HEIGHT__": str(height),
        "__DURATION__": str(duration), "__FPS__": str(fps), "__FONT_SIZE__": str(max(18, round(width * 0.055))),
        "__FADE_OUT__": str(max(0.3, duration - 0.2)), "__FONT_URL__": font_name,
    }
    source = template.read_text(encoding="utf-8")
    # Escape the title last, so user text resembling a token stays literal.
    for token, value in replacements.items():
        if token != "__TITLE__":
            source = source.replace(token, value)
    source = source.replace("__TITLE__", replacements["__TITLE__"])
    env = _hyperframes_env()
    with tempfile.TemporaryDirectory(prefix="shortdrama-hyperframes-") as temporary:
        composition = Path(temporary)
        (composition / "index.html").write_text(source, encoding="utf-8")
        shutil.copyfile(gsap, composition / "gsap.min.js")
        shutil.copyfile(font, composition / font_name)
        # The project contains only our reviewed HTML and a pinned local GSAP.
        check = _run_local(["node", str(cli), "check", str(composition)], env=env)
        render = _run_local(["node", str(cli), "render", str(composition), "--fps", str(fps), "--format", "mp4", "--quality", "draft", "--output", str(destination)], env=env, timeout=300)
    warnings = lambda value: "\n".join(line for line in value.splitlines() if "⚠" in line or re.search(r"\bwarning\b", line, flags=re.IGNORECASE))[-3000:]
    return {"hyperframes": HYPERFRAMES_VERSION, "gsap": GSAP_VERSION, "check_passed": True, "check_warnings": warnings(check.stderr), "render_warnings": warnings(render.stderr)}


def generate_packaging(
    output: str | Path,
    title: str,
    backend: str = "ffmpeg",
    project_dir: str | Path | None = None,
    *,
    duration_seconds: float = 2,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> dict[str, Any]:
    """Render a fresh MP4 asset and return ffprobe data, SHA and provenance.

    HyperFrames is optional and separately installed; ``project_dir`` identifies
    that isolated dependency directory, not an arbitrary executable HTML project.
    Its output may be silent; the Remotion timeline decides placement and audio.
    """
    target = _output_path(output)
    if backend not in {"ffmpeg", "hyperframes"}:
        raise ValueError("包装后端只支持 ffmpeg 或 hyperframes")
    if not isinstance(title, str) or not title.strip() or len(title) > 240 or any(ord(char) < 32 and char != "\n" for char in title):
        raise ValueError("标题必须为 1–240 字符，且不含控制字符")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (float, int)) or not math.isfinite(duration_seconds) or not 0.5 <= duration_seconds <= 30:
        raise ValueError("包装时长须在 0.5–30 秒之间")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height, fps)) or width % 2 or height % 2 or max(width, height) > 4096 or fps > 60:
        raise ValueError("包装尺寸须为正偶数且不大于4096，帧率须为1–60整数")
    duration = math.ceil(duration_seconds * fps) / fps
    font_size = max(18, round(width * 0.055))
    line_width = max(1, int(width * 0.78 / font_size))
    lines = [line[index:index + line_width] for line in title.split("\n") for index in range(0, max(1, len(line)), line_width)]
    if font_size > width * 0.78 or len(lines) * font_size * 1.45 > height * 0.78:
        raise ValueError("标题无法放入包装安全区，请缩短标题或调整尺寸")
    target.parent.mkdir(parents=True, exist_ok=True)
    details: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix=".shortdrama-packaging-", dir=target.parent) as temporary:
        working = Path(temporary)
        candidate = working / "packaging.mp4"
        if backend == "ffmpeg":
            # A text file plus expansion=none prevents drawtext expression injection.
            text_file = working / "title.txt"
            text_file.write_text("\n".join(lines), encoding="utf-8")
            # Copy into a path without platform/filter metacharacters.
            with tempfile.TemporaryDirectory(prefix="shortdrama-title-") as text_temp:
                safe_text = Path(text_temp) / "title.txt"
                shutil.copyfile(text_file, safe_text)
                escaped = str(safe_text).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
                filters = f"drawtext=font='Noto Sans CJK SC':textfile='{escaped}':expansion=none:fontcolor=white:fontsize={font_size}:line_spacing={round(font_size * .35)}:x=(w-text_w)/2:y=(h-text_h)/2,fade=t=in:st=0:d=0.2,fade=t=out:st={duration-.2:.6f}:d=0.2"
                _run_local(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", f"color=c=0x0c1424:s={width}x{height}:r={fps}:d={duration}", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-vf", filters, "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration), "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(candidate)])
        else:
            details = _render_hyperframes(candidate, title, project_dir, duration=duration, width=width, height=height, fps=fps)
        verified = probe_media(candidate)
        videos = [stream for stream in verified["streams"] if stream.get("codec_type") == "video"]
        if not videos:
            raise RuntimeError("包装结果没有视频流")
        video = videos[0]
        if (video.get("width"), video.get("height"), video.get("codec_name")) != (width, height, "h264"):
            raise RuntimeError("包装结果尺寸或 H.264 编码与请求不符")
        if abs(float(Fraction(video.get("avg_frame_rate", "0/1"))) - fps) > .01:
            raise RuntimeError("包装结果帧率与请求不符")
        if abs(float(video.get("duration") or verified["format"].get("duration") or 0) - duration) > max(.1, 2 / fps):
            raise RuntimeError("包装结果时长与请求不符")
        # Same-directory hard-link creation fails atomically if output now exists.
        os.link(candidate, target)
    metadata = probe_media(target)
    metadata.update({
        "artifact_kind": "visual_packaging", "backend": backend, "title": title,
        "main_timeline_control": False, "external_api_called": False,
        "spec": {"duration_seconds": duration, "width": width, "height": height, "fps": fps},
        "backend_details": details,
    })
    return metadata
