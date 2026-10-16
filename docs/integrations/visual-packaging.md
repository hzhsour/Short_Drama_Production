# 独立视觉包装与本地素材分析

Remotion 持有主时间线。包装模块只生成可入库的独立 MP4 片头/标题素材，分析模块只返回检测结果；两者不修改原始媒体，不接管镜头剪辑，不调用生成模型、TTS 或托管渲染 API。

## 已实现的 Python 接口

```python
from pathlib import Path
from short_drama.packaging import generate_packaging
from short_drama.analysis import analyze_video

title = generate_packaging(
    Path("renders/new-title.mp4"),
    "午夜来信 · 第一集",
    backend="ffmpeg",  # 默认，已有 FFmpeg 即可
    duration_seconds=2,
    width=1080,
    height=1920,
    fps=30,
)
report = analyze_video(
    Path(title["path"]),
    detect_silence=True,
    detect_scenes=True,
)
```

从仓库根目录运行时先设置 `PYTHONPATH=src`，或由项目 CLI 导入。返回数据包括绝对路径、SHA-256、ffprobe 流与容器信息、请求规格及后端来源。输出必须为不存在的本地 `.mp4`，拒绝 URL、网络共享、软链接及现有文件；暂存成功后原子创建目标，避免覆盖并发产生的输出。

FFmpeg 默认实现中文标题、背景色、淡入淡出，导出 H.264/yuv420p/AAC 静音音轨；标题通过 `textfile` 且关闭表达式展开，避免将文字当成 FFmpeg 语法。可用时长 0.5–30 秒，向上对齐输出帧。模块检查尺寸、帧率、时长和 H.264 编码后才发布结果。标题过长无法进入安全区时明确报错。

这是片头包装，不是生成剧情人物或真实 AI 剧情镜头。配音、BGM、片头在正片中的位置由 Remotion 时间线明确决定。

## 可选 HyperFrames 后端

已审查官方仓库 [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes/tree/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22) 的 CLI、模板、渲染、遥测和更新逻辑。版本 `hyperframes@0.8.164`，Apache-2.0；Node >=22，使用 FFmpeg/ffprobe、Chromium、sharp/esbuild。GSAP 固定为 `3.14.2`，以独立 npm 依赖使用；其分发条款由该包自身许可证约束。没有把官方整套 Skill 的自动更新、远程素材和云渲染行为加入项目默认流程。

依赖放在 `integrations/hyperframes/`，与根 Remotion 依赖隔离。`package-lock.json` 固定完整依赖与完整性校验；`.npmrc` 默认关闭生命周期脚本。安装不运行远程脚本：

```bash
npm ci --prefix integrations/hyperframes --ignore-scripts --no-audit --no-fund
```

Chromium、FFmpeg 和中文字体须预装。Linux 可使用 `fonts-noto-cjk` 与 `fontconfig`；其他系统可设置 `SHORT_DRAMA_CJK_FONT` 指向本地已授权 TTF/TTC/OTF/WOFF/WOFF2。接口拒绝自动下载浏览器。第三方依赖安装需环境允许访问 npm，继续使用云环境既有代理/TLS。

```python
title = generate_packaging(
    Path("renders/new-hyperframes-title.mp4"),
    "午夜来信 · 技术测试",
    backend="hyperframes",
    project_dir=Path("integrations/hyperframes"),
    duration_seconds=1,
)
```

`project_dir` 只指定隔离依赖所在位置；接口不执行用户传入的任意 HTML 项目。它基于项目自有 `title.html` 建立临时 composition，将固定版本 GSAP 与本地中文字体复制进去，所有脚本/字体均本地加载。标题按 HTML 文本转义，不进入脚本字符串。字体仅临时复制，不提交 Git。

只运行已审查的 `hyperframes check <temporary-dir>` 与 `hyperframes render <temporary-dir> --fps 30 --format mp4 --quality draft --output <new-file>`。每次都设置：

```text
HYPERFRAMES_NO_TELEMETRY=1
DO_NOT_TRACK=1
HYPERFRAMES_SKIP_SKILLS=1
HYPERFRAMES_NO_UPDATE_CHECK=1
HYPERFRAMES_NO_AUTO_INSTALL=1
CI=1
```

系统浏览器通过 `HYPERFRAMES_BROWSER_PATH` 和 `PRODUCER_HEADLESS_SHELL_PATH` 明确注入。启动子进程只传必要的系统环境，不传 API Key、令牌或代理凭证。没有运行 `init`、`cloud`、`publish`、`media`、自动 Skill 安装或自动升级。check 未通过就停止，不静默切换后端或跳过检查。

HyperFrames 的本机浏览器服务需要 loopback socket 权限。当前云环境普通 sandbox 曾返回 `browser setup process exited without a result`；授予该命令网络权限后，同一全本地 composition 的 check/render 成功。未改代理、TLS 或外网政策。其 history 默认尝试写入 `/home/agent/.cache/hyperframes`，当前只读环境出现“Check report was not recorded”警告；本接口保留该警告，并由项目自身保存结果 SHA 与制作元数据，不把该警告当成检查通过证据。check 的有效退出状态仍必须为成功。

HyperFrames 片头可能没有音轨；由主时间线接入后统一混音与最终质检。不要把片头独立素材直接当作完整剧集交付。

## 本地分析能力与 video-use 边界

`analyze_video(path, detect_silence=False, detect_scenes=False)` 复用 `probe_media`，允许本地视频、默认仅提取元数据。可选检测完整解码所选流，超时 180 秒后明确失败，不对原素材执行删改：

| 能力 | 实现与边界 |
| --- | --- |
| 媒体元数据 | ffprobe，包含编码、尺寸、帧率、音轨、时长与文件 SHA |
| 静音 | FFmpeg `silencedetect`，-35 dB，最短 0.3 秒；无音轨明确返回 `unavailable_no_audio` |
| 场景变化候选 | FFmpeg 像素变化 `scene > 0.30`，返回候选时间；闪光、运动和渐变可能造成误报/漏报 |
| 转录/ASR | 未实现；返回 `asr=false`，不会把静音检测写成语音识别 |
| 语义镜头/角色识别 | 未实现；不保证人物识别、剧情连续性或身份一致性 |
| 自动剪辑优化 | 未实现；分析结果不会自动删除镜头或重排时间线 |
| video-use | 只保留禁用的可选 provider 元数据，不导入 ElevenLabs，不上传媒体，不运行外部分析 API |

video-use 的官方能力、外部依赖与选择理由见 [第三方审计](third-party-audit.md)。若以后接入，必须明确配置具体分析服务、授权素材及费用；其职责应继续限制在产生供人工/主时间线使用的分析建议。

## 2026-10-16 本地验证

- 包装测试 6 项、分析测试 4 项通过，含实际 FFmpeg 中文标题编码、SHA、原始文件保留、路径/参数限制、缺依赖、HTML 转义、密钥环境隔离及超时错误。
- 合成两秒黑白硬切与有声/静音测试视频，实际检出约 1 秒处的像素切点和开头静音，源文件 SHA 未变化。
- 默认 FFmpeg 已实际生成 `renders/visual-packaging-ffmpeg-20261016.mp4`，1080×1920、30 FPS、1 秒，H.264/AAC。
- HyperFrames 已实际通过 check/render，生成 320×568 与 1080×1920 两个版本，均为 30 FPS、1 秒；1080 版为 `renders/visual-packaging-hyperframes-1080-20261016.mp4`。三个包装资产均通过完整 FFmpeg 解码；SHA 和规格见 `integrations/hyperframes/verification.json`。
- 所有这些素材均为独立包装技术测试；没有调用真实视频生成或付费服务。视频、node_modules、临时字体和缓存均不提交普通 Git。
