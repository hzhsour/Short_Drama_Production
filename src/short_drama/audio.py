"""Local/Mock audio production. No paid services or network requests are made.

Mock dialogue is an audible test tone, never presented as Chinese speech. An
offline Chinese TTS implementation can be registered through LocalTTSAdapter;
no model weights are downloaded and no external TTS adapter is enabled here.
"""

from __future__ import annotations

from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave
from typing import Protocol

from .continuity import character_index
from .validation import safe_relative_path, validate_storyboard


class LocalTTSAdapter(Protocol):
    """Registration contract for a preinstalled offline zh-CN speech engine.

    Implementations must not access a network or paid service. The engine and
    licensed voice weights must already be installed by the operator.
    """
    is_local: bool

    def synthesize(self, text: str, voice: dict, output_path: Path) -> Path:
        ...


class PiperLocalTTSAdapter:
    """Invoke an explicitly installed Piper CLI and preinstalled local voice.

    voice_models maps the character voice.profile_id to an existing .onnx file.
    The adjacent .onnx.json config must also exist. This adapter never invokes
    installers, voice download commands, a server, or an external API. Operators
    must verify the Piper program and each voice model's separate license.
    """
    is_local = True

    def __init__(self, voice_models: dict[str, Path], executable: str = "piper", timeout: int = 120,
                 speaker_ids: dict[str, int] | None = None):
        if not isinstance(voice_models, dict) or not voice_models:
            raise ValueError("Piper 需要 profile_id 到本地 ONNX 权重的配置")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("Piper timeout 必须是正整数")
        self.voice_models = {key: Path(value).resolve() for key, value in voice_models.items()}
        if any(not isinstance(key, str) or not key.strip() for key in self.voice_models):
            raise ValueError("Piper profile_id 必须是非空字符串")
        self.executable = executable
        self.timeout = timeout
        self.speaker_ids = speaker_ids or {}
        if not isinstance(self.speaker_ids, dict) or any(
                not isinstance(key, str) or key not in self.voice_models or not isinstance(value, int)
                or isinstance(value, bool) or value < 0 for key, value in self.speaker_ids.items()):
            raise ValueError("Piper speaker_ids 必须把已配置 profile 映射到非负整数")

    def synthesize(self, text: str, voice: dict, output_path: Path) -> Path:
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise ValueError("Piper 台词必须是非空文本")
        if not isinstance(voice, dict) or voice.get("language") != "zh-CN":
            raise ValueError("Piper 本地适配器当前需要 zh-CN 声音设定")
        profile_id = voice.get("profile_id")
        if not isinstance(profile_id, str) or profile_id not in self.voice_models:
            raise ValueError("Piper 未为此 voice profile 配置本地中文模型")
        model = self.voice_models[profile_id]
        if model.suffix != ".onnx" or not model.is_file() or not Path(str(model) + ".json").is_file():
            raise FileNotFoundError("Piper 需要已安装的 .onnx 及相邻 .onnx.json；不会自动下载权重")
        try:
            config = json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Piper 相邻模型配置不是可读取的 JSON") from error
        # Piper's g2pW Mandarin phonemizer may download additional weights on
        # first use. Only the known bundled eSpeak path is allowed offline.
        if not isinstance(config, dict) or config.get("phoneme_type", "espeak") != "espeak":
            raise ValueError("离线 Piper 当前仅支持 espeak phoneme_type；g2pW/未知类型可能自动下载权重，已阻断")
        espeak = config.get("espeak")
        if not isinstance(espeak, dict) or espeak.get("voice") not in ("cmn", "zh", "zh-cn", "zh-CN"):
            raise ValueError("Piper 需要已核实的中文 eSpeak 模型配置")
        speakers = config.get("num_speakers")
        if not isinstance(speakers, int) or isinstance(speakers, bool) or speakers < 1:
            raise ValueError("Piper 模型配置必须声明正整数 num_speakers")
        speaker = self.speaker_ids.get(profile_id, 0)
        if not isinstance(speaker, int) or isinstance(speaker, bool) or not 0 <= speaker < speakers:
            raise ValueError("Piper speaker 超出模型 num_speakers 范围；单声线模型仅允许0")
        executable = shutil.which(self.executable)
        if executable is None:
            raise RuntimeError("Piper CLI 未安装或不在 PATH；请安装并配置其可执行文件")
        output_path = Path(output_path).resolve()
        if output_path.exists():
            raise FileExistsError(f"拒绝覆盖 Piper 输出: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="piper-local-", dir=output_path.parent) as temporary:
            temporary_wav = Path(temporary) / "speech.wav"
            command = [executable, "--model", str(model), "--output_file", str(temporary_wav)]
            if profile_id in self.speaker_ids:
                command.extend(["--speaker", str(self.speaker_ids[profile_id])])
            environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            try:
                result = subprocess.run(command, input=text.strip() + "\n", capture_output=True, text=True,
                                        timeout=self.timeout, check=False, env=environment)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("本地 Piper 合成超时，未调用外部服务") from error
            if result.returncode != 0:
                raise RuntimeError(f"本地 Piper 合成失败 (exit {result.returncode}): {result.stderr[-1000:]}")
            if not temporary_wav.is_file():
                raise RuntimeError("Piper 返回成功但没有产生 WAV 文件")
            with wave.open(str(temporary_wav), "rb") as wav:
                if wav.getnframes() <= 0:
                    raise RuntimeError("Piper 输出了空音频")
            _exclusive_bytes(output_path, temporary_wav.read_bytes())
        return output_path


def _exclusive_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return
        raise FileExistsError(f"拒绝覆盖已有音频产物: {path}")
    with path.open("xb") as stream:
        stream.write(content)


def _mock_wav(path: Path, frames: int, fps: int, frequency: float, kind: str, sample_rate: int) -> None:
    import io
    samples = array("h")
    count = round(frames * sample_rate / fps)
    amplitude = .12 if kind == "dialogue" else .025
    fade = max(1, min(sample_rate // 50, count // 2))
    for index in range(count):
        envelope = min(1, index / fade, (count - 1 - index) / fade)
        value = math.sin(2 * math.pi * frequency * index / sample_rate)
        if kind == "bgm":
            value = .6 * value + .4 * math.sin(2 * math.pi * frequency * 1.5 * index / sample_rate)
        samples.append(round(32767 * amplitude * envelope * value))
    if sys.byteorder != "little":
        samples.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(samples.tobytes())
    _exclusive_bytes(path, buffer.getvalue())


def frames_to_srt_time(frames: int, fps: int) -> str:
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 0 or not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise ValueError("帧必须为非负整数，fps 必须为正整数")
    milliseconds = (frames * 1000 + fps // 2) // fps
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def subtitles_to_srt(storyboard: dict, subtitles: list[dict]) -> str:
    """Convert shot-relative cues to cumulative episode time; no intro offset."""
    errors = validate_storyboard(storyboard)
    if errors:
        raise ValueError("字幕分镜输入无效: " + "; ".join(errors))
    if not isinstance(subtitles, list):
        raise ValueError("subtitles 必须是数组")
    offsets = {}
    shots_by_id = {}
    elapsed = 0
    for shot in storyboard["shots"]:
        offsets[shot["shot_id"]] = elapsed
        shots_by_id[shot["shot_id"]] = shot
        elapsed += shot["duration_frames"]
    for cue in subtitles:
        if not isinstance(cue, dict) or not all(key in cue for key in ("shot_id", "text", "start_frame", "end_frame")):
            raise ValueError("字幕必须含 shot_id/text/start_frame/end_frame")
        if not isinstance(cue["shot_id"], str) or cue["shot_id"] not in offsets:
            raise ValueError("字幕引用了未知镜头")
        if not isinstance(cue["text"], str):
            raise ValueError("字幕 text 必须是字符串")
        if not isinstance(cue["start_frame"], int) or isinstance(cue["start_frame"], bool) or not isinstance(cue["end_frame"], int) or isinstance(cue["end_frame"], bool) or not 0 <= cue["start_frame"] < cue["end_frame"] <= shots_by_id[cue["shot_id"]]["duration_frames"]:
            raise ValueError("字幕时间范围无效或越出镜头")
    cues = sorted(subtitles, key=lambda cue: offsets[cue["shot_id"]] + cue["start_frame"])
    result = []
    last_end = -1
    for number, cue in enumerate(cues, 1):
        start = offsets[cue["shot_id"]] + cue["start_frame"]
        end = offsets[cue["shot_id"]] + cue["end_frame"]
        if start < last_end:
            raise ValueError("单轨 SRT 字幕时间重叠")
        last_end = end
        text = cue["text"].replace("\r", "").strip()
        if not text or "\n\n" in text or "-->" in text:
            raise ValueError("字幕内容不可为空或包含 SRT 控制字符")
        result.append(f"{number}\n{frames_to_srt_time(start, storyboard['fps'])} --> {frames_to_srt_time(end, storyboard['fps'])}\n{text}\n")
    return "\n".join(result)


def inspect_audio(path: Path, expected_seconds: float | None = None, tolerance: float = .05) -> dict:
    """Inspect decodability, duration and real loudness; FFmpeg adds integrated LUFS."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"音频不存在: {path}")
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    metadata: dict = {"path": str(path.resolve()), "errors": [], "warnings": []}
    if ffprobe:
        process = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels,duration:format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        probe = json.loads(process.stdout)
        if not probe.get("streams"):
            raise ValueError(f"没有可读取音轨: {path}")
        stream = probe["streams"][0]
        metadata.update(duration_seconds=float(stream.get("duration", probe.get("format", {}).get("duration", 0))),
                        sample_rate=int(stream["sample_rate"]), channels=int(stream["channels"]))
    elif path.suffix.lower() != ".wav":
        raise RuntimeError("检查非 WAV 音频需要 FFprobe")
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as stream:
            if stream.getsampwidth() != 2:
                raise ValueError("本地响度分析要求 16-bit PCM WAV，其他格式请安装 FFmpeg")
            raw = stream.readframes(stream.getnframes())
            pcm = array("h")
            pcm.frombytes(raw)
            if sys.byteorder != "little":
                pcm.byteswap()
            metadata.update(duration_seconds=stream.getnframes() / stream.getframerate(),
                            sample_rate=stream.getframerate(), channels=stream.getnchannels())
        peak = max((abs(sample) for sample in pcm), default=0) / 32768
        rms = math.sqrt(sum(sample * sample for sample in pcm) / max(1, len(pcm))) / 32768
        metadata["peak_dbfs"] = round(20 * math.log10(peak), 2) if peak else None
        metadata["rms_dbfs"] = round(20 * math.log10(rms), 2) if rms else None
        if peak >= .999:
            metadata["errors"].append("音频存在削波风险")
        if not rms:
            metadata["warnings"].append("音轨为静音")
    if ffmpeg:
        process = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-v", "info", "-i", str(path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
        if process.returncode:
            metadata["errors"].append("FFmpeg 无法完整解码音频")
        else:
            begin, end = process.stderr.rfind("{"), process.stderr.rfind("}")
            if begin >= 0 and end > begin:
                loudness = json.loads(process.stderr[begin:end + 1])
                raw_i = loudness.get("input_i")
                metadata["integrated_lufs"] = float(raw_i) if raw_i not in (None, "-inf", "inf") else None
                raw_peak = loudness.get("input_tp")
                metadata["true_peak_dbfs"] = float(raw_peak) if raw_peak not in (None, "-inf", "inf") else None
                metadata["loudness_target_lufs"] = -16
                if metadata["integrated_lufs"] is not None and abs(metadata["integrated_lufs"] + 16) > 4:
                    metadata["warnings"].append("单素材响度偏离 -16 LUFS；最终混音后应再次归一化与检查")
    else:
        metadata["warnings"].append("未安装 FFmpeg；未执行完整解码及 LUFS 检查")
    if expected_seconds is not None and abs(metadata["duration_seconds"] - expected_seconds) > tolerance:
        metadata["errors"].append(f"音频时长 {metadata['duration_seconds']:.3f}s 与目标 {expected_seconds:.3f}s 不符")
    return metadata


def _normalise_local(source: Path, target: Path, frames: int, fps: int, sample_rate: int, *, dialogue: bool = True) -> None:
    """Create a new leveled/padded/trimmed PCM file; never alter source recording."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("本地录音/TTS 整理需要 FFmpeg")
    if target.exists():
        raise FileExistsError(f"拒绝覆盖已有音频产物: {target}")
    if not source.is_file() or source.resolve() == target.resolve():
        raise ValueError("本地源音频不存在或与输出路径相同")
    # Inspect before normalization: do not hide a badly overlong line by trimming it.
    inspection = inspect_audio(source)
    if inspection["errors"] or (dialogue and inspection["duration_seconds"] > frames / fps + .05):
        raise ValueError("源配音超过对白时段或无法解码，请缩短台词/调整分镜帧数")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-n", "-i", str(source),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", "-t", f"{frames / fps:.9f}",
                    "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le", str(target)], check=True)


def build_audio(storyboard: dict, characters: dict, output_dir: Path, mode: str = "mock", *,
                asset_root: Path | None = None, tts_adapter: LocalTTSAdapter | None = None,
                sample_rate: int = 48000) -> dict:
    """Build audio manifest and UTF-8 SRT using shot-relative frame positions.

    local mode uses dialogue.audio_path recordings or an explicit offline TTS
    adapter. External paid TTS is deliberately unavailable without a separately
    implemented, audited adapter, official configuration and explicit approval.
    """
    if mode not in ("mock", "local"):
        raise PermissionError("外部/付费 TTS 尚未启用；需要正式适配器、密钥、预算与用户明确批准")
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate not in (24000, 44100, 48000):
        raise ValueError("sample_rate 必须为 24000/44100/48000")
    errors = validate_storyboard(storyboard, characters)
    if errors:
        raise ValueError("音频输入校验失败:\n" + "\n".join(errors))
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_root = Path(asset_root).resolve() if asset_root else None
    profiles = character_index(characters)
    tracks, subtitles, quality = [], [], []
    fps = storyboard["fps"]
    def resolve_source(relative: str) -> Path:
        if asset_root is None or not safe_relative_path(relative):
            raise ValueError("本地音频 path/audio_path 需要安全项目相对路径及 asset_root")
        path = (asset_root / relative).resolve()
        if not path.is_relative_to(asset_root) or not path.is_file():
            raise ValueError("本地音频不存在或越出 asset_root")
        return path
    for shot in storyboard["shots"]:
        shot_id = shot["shot_id"]
        entries = []
        for number, line in enumerate(shot["dialogue"], 1):
            entries.append({**line, "id": f"{shot_id}-dialogue-{number:03}", "kind": "dialogue", "volume": line.get("volume", 1.0)})
            subtitles.append({"shot_id": shot_id, "character_id": line["character_id"], "text": line["text"],
                              "start_frame": line["start_frame"], "end_frame": line["start_frame"] + line["duration_frames"]})
        for number, cue in enumerate(shot["audio"], 1):
            if isinstance(cue, str):
                cue = {"kind": "ambience", "description": cue, "start_frame": 0,
                       "duration_frames": shot["duration_frames"], "volume": .2}
            entries.append({**cue, "id": f"{shot_id}-{cue['kind']}-{number:03}", "volume": cue.get("volume", .2)})
        for entry in entries:
            path = output_dir / f"{entry['id']}.wav"
            voice = profiles[entry["character_id"]]["voice"] if entry["kind"] == "dialogue" else {}
            signature = hashlib.sha256(json.dumps({"entry": entry, "voice": voice, "fps": fps, "rate": sample_rate}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if mode == "mock":
                frequency = float(voice.get("pitch_hz", 110 if entry["kind"] == "bgm" else 320))
                _mock_wav(path, entry["duration_frames"], fps, frequency, entry["kind"], sample_rate)
            else:
                source_path = entry.get("audio_path") if entry["kind"] == "dialogue" else entry.get("path")
                if source_path:
                    source = resolve_source(source_path)
                elif entry["kind"] == "dialogue" and tts_adapter is not None and getattr(tts_adapter, "is_local", False) is True:
                    raw_path = output_dir / f"{entry['id']}.raw.wav"
                    if raw_path.exists():
                        raise FileExistsError(f"拒绝覆盖 TTS 原始音频: {raw_path}")
                    source = Path(tts_adapter.synthesize(entry["text"], voice, raw_path))
                else:
                    raise RuntimeError("未配置离线中文 TTS/本地对白录音或声音素材；Mock 仅提供测试音调")
                _normalise_local(source, path, entry["duration_frames"], fps, sample_rate, dialogue=entry["kind"] == "dialogue")
            inspection = inspect_audio(path, entry["duration_frames"] / fps)
            if inspection["errors"]:
                raise ValueError("音频质检失败: " + "; ".join(inspection["errors"]))
            quality.append({"id": entry["id"], **inspection})
            track = {"id": entry["id"], "shot_id": shot_id, "kind": entry["kind"], "path": str(path),
                     "start_frame": entry["start_frame"], "duration_frames": entry["duration_frames"],
                     "volume": entry["volume"], "mode": mode, "fingerprint": signature}
            if entry["kind"] == "dialogue":
                track.update(character_id=entry["character_id"], voice_profile_id=voice["profile_id"])
            tracks.append(track)
    srt_path = output_dir / f"{storyboard['episode_id']}.srt"
    _exclusive_bytes(srt_path, subtitles_to_srt(storyboard, subtitles).encode("utf-8"))
    result = {"episode_id": storyboard["episode_id"], "mode": mode, "tracks": tracks,
              "subtitles": subtitles, "srt_path": str(srt_path), "sample_rate": sample_rate,
              "quality": quality, "notice": "技术测试音调，不是真人配音或中文 TTS" if mode == "mock" else "本地录音/已配置离线 TTS"}
    _exclusive_bytes(output_dir / "audio-manifest.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return result
