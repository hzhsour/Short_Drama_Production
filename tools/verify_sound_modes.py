#!/usr/bin/env python3
"""Render three local audio modes and verify frequencies with a stdlib FFT.

Creates only public color/sine fixtures. No generation/TTS API or model is used.
Requires existing npm dependencies, Chromium, FFmpeg and FFprobe. Use a fresh
run directory so originals and previous evidence are never silently replaced.
"""

from array import array
import argparse
import cmath
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from short_drama.audio import build_audio
from short_drama.io import file_hash, write_json
from short_drama.media import normalize_media, qc_video
from short_drama.pipeline import render_timeline
from short_drama.timeline import build_timeline


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, timeout=120)


def _fixtures(root: Path) -> tuple[Path, Path]:
    source, speech = root / "source-440hz.mp4", root / "dub-880hz.wav"
    _run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "color=c=0x264060:s=160x284:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest", str(source)])
    _run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1", "-c:a", "pcm_s16le", str(speech)])
    return source, speech


def _fft(values: list[complex]) -> list[complex]:
    """Iterative radix-2 FFT; no NumPy/SciPy dependency."""
    result, count = list(values), len(values)
    reverse = 0
    for index in range(1, count):
        bit = count >> 1
        while reverse & bit:
            reverse ^= bit
            bit >>= 1
        reverse ^= bit
        if index < reverse:
            result[index], result[reverse] = result[reverse], result[index]
    size = 2
    while size <= count:
        phase_step = cmath.exp(-2j * math.pi / size)
        for start in range(0, count, size):
            phase = 1 + 0j
            for offset in range(size // 2):
                first = result[start + offset]
                second = result[start + offset + size // 2] * phase
                result[start + offset] = first + second
                result[start + offset + size // 2] = first - second
                phase *= phase_step
        size *= 2
    return result


def inspect_frequencies(path: Path) -> dict:
    decoded = _run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0", "-ar", "48000", "-ac", "1", "-f", "s16le", "pipe:1"]).stdout
    pcm = array("h")
    pcm.frombytes(decoded)
    if sys.byteorder != "little":
        pcm.byteswap()
    count, rate, offset = 32768, 48000, 4800
    samples = [sample / 32768 for sample in pcm[offset:offset + count]]
    if len(samples) != count:
        raise ValueError("最终音轨不足以执行固定窗 FFT 验收")
    window = [.5 - .5 * math.cos(2 * math.pi * index / (count - 1)) for index in range(count)]
    transform = _fft([complex(sample * weight) for sample, weight in zip(samples, window)])
    scale = count * sum(weight * weight for weight in window)

    def band_rms(frequency: int) -> float:
        power = sum(abs(transform[index]) ** 2 for index in range(1, count // 2) if abs(index * rate / count - frequency) <= 8)
        return math.sqrt(2 * power / scale)

    return {"method": "stdlib radix-2 FFT, Hann window, 32768 samples, +/-8Hz bands", "sample_rate": rate,
            "rms": math.sqrt(sum(sample * sample for sample in samples) / count),
            "band_440hz_rms": band_rms(440), "band_880hz_rms": band_rms(880)}


def verify(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if any(run_dir.iterdir()):
        raise FileExistsError("音频专项验收需要空目录；请指定新的 --run-dir，禁止覆盖证据")
    source, speech = _fixtures(run_dir)
    characters = json.loads((ROOT / "examples/technical-demo/characters.json").read_text(encoding="utf-8"))
    shot = {"shot_id": "EP901-SC01-SH001", "scene_id": "EP901-SC01", "duration_frames": 30,
            "characters": ["CHAR-001"], "location": "本地公开色卡", "action": "音频专项技术验收",
            "framing": "固定色卡", "camera_move": "固定", "image_prompt": "本地技术色卡", "video_prompt": "不调用生成API",
            "continuity_refs": [], "audio": [], "dialogue": [{"character_id": "CHAR-001", "text": "音频技术测试，不是真实配音。", "start_frame": 0, "duration_frames": 30, "audio_path": speech.name}]}
    report = {"schema": "short-drama.sound-mode-verification/v1", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "real_generation_api_called": False, "real_tts_api_called": False, "private_media_used": False,
              "source_sha256": file_hash(source), "dub_source_sha256": file_hash(speech), "results": [], "passed": False}
    for mode in ("model", "dub", "silent"):
        root = run_dir / mode
        root.mkdir()
        board = {"episode_id": "EP901", "aspect_ratio": "9:16", "fps": 30, "width": 160, "height": 284,
                 "technical_test": True, "sound_mode": mode, "shots": [shot]}
        audio = build_audio(board, characters, root / "audio", mode="local", asset_root=run_dir)
        videos = {"episode_id": "EP901", "mode": "mock", "sound_mode": mode, "jobs": [{"shot_id": shot["shot_id"], "status": "succeeded",
                  "artifact": {"path": str(source), "sha256": file_hash(source), "sound_mode": mode, "has_source_audio": True}}]}
        timeline = build_timeline(board, videos, audio, intro_frames=0, outro_frames=0, transition_frames=0)
        timeline_path = root / "timeline.json"
        write_json(root / "storyboard.json", board)
        write_json(root / "video-result.json", videos)
        write_json(timeline_path, timeline)
        rendered, final = root / "remotion.mp4", root / "final.mp4"
        render_timeline(timeline_path, rendered)
        normalize_media(rendered, final, width=160, height=284, fps=30)
        frequencies, quality = inspect_frequencies(final), qc_video(final, timeline)
        desired = frequencies["band_440hz_rms" if mode == "model" else "band_880hz_rms"]
        undesired = frequencies["band_880hz_rms" if mode == "model" else "band_440hz_rms"]
        sound_passed = frequencies["rms"] < .00001 if mode == "silent" else desired > .02 and undesired < desired * .01
        result = {"sound_mode": mode, "passed": sound_passed and quality["passed"], "frequency_check_passed": sound_passed,
                  "frequencies": frequencies, "output": str(final), "output_sha256": file_hash(final), "quality": quality,
                  "external_tracks": len(timeline["tracks"]), "has_source_audio": timeline["shots"][0]["media"]["has_source_audio"]}
        report["results"].append(result)
        write_json(run_dir / "verification.json", report)
        if not result["passed"]:
            raise RuntimeError(f"{mode} 音频模式验收失败，见 {run_dir / 'verification.json'}")
    report["passed"] = all(result["passed"] for result in report["results"])
    write_json(run_dir / "verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本地生成440Hz原声/880Hz配音，实际渲染三种模式并用FFT验收")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "runs/prelive-audio")
    arguments = parser.parse_args()
    result = verify(arguments.run_dir)
    print(json.dumps({"passed": result["passed"], "report": str(arguments.run_dir.resolve() / "verification.json"),
                      "modes": [{"sound_mode": item["sound_mode"], "passed": item["passed"], "frequencies": item["frequencies"]} for item in result["results"]]}, ensure_ascii=False, indent=2))
