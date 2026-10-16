# 中文 CLI 使用说明

在项目根目录执行 `npm run drama -- <命令>`。也可运行 `python3 tools/drama.py <命令>`；Windows 使用对应 Python 启动器。`--help` 给出准确参数。

| 命令 | 功能 |
| --- | --- |
| `init-series SLUG --title 标题` | 新建系列圣经、人物与制作草稿，不覆盖已有系列 |
| `init-episode SERIES_DIR EP001` | 新建分集草稿和任务表 |
| `validate` | 检查项目；`--characters`/`--script`/`--storyboard` 检查指定数据 |
| `convert-script SCRIPT --characters FILE --output NEW.json` | 结构化剧本转分镜，目标必须不存在 |
| `plan BOARD --run-dir DIR` | 只在本地建立镜头计划与估算；`--episodes N` 投影相同分集的全剧成本 |
| `generate BOARD --run-dir DIR --max-jobs N` | 有界推进视频引擎，默认 Mock |
| `status --run-dir DIR` | 读取检查点和镜头状态，检查已完成素材哈希 |
| `audio BOARD --characters FILE --output-dir DIR` | 测试音/本地录音、字幕、音频时长和响度报告 |
| `timeline BOARD --videos RESULT --audio RESULT --output FILE` | 生成主时间线及带片头偏移的 SRT |
| `render TIMELINE NEW.mp4` | Remotion 渲染，不覆盖输出 |
| `normalize SOURCE NEW.mp4` | FFmpeg 统一 H.264、1080×1920、30 FPS 与 AAC 48 kHz |
| `quality VIDEO --timeline TIMELINE` | 解码、规格、时长、音轨和时间线质检 |
| `analyze VIDEO --silence --scenes` | 本地静音及像素变化切点候选，不做 ASR |
| `packaging NEW.mp4 --title 标题 --backend ffmpeg` | 独立包装资产；可选 `hyperframes` 需先安装其隔离依赖 |
| `run SCRIPT --characters FILE --run-dir DIR --render` | 完整有界制作流程；默认视频和音频均 Mock |
| `demo --render` | 运行固定公开中文技术样例 |
| `rebind-storage ENGINE_ROOT NEW_STORAGE --run-dir RUN` | 验证已恢复账本与素材，离线更新路径 |
| `restore-run RUN ENGINE_ROOT NEW_STORAGE --asset-root ASSETS` | 完整迁移已复制的账本、音视频、字幕、时间线和制作状态；不创建备份 |
| `export-metadata RUN --output NEW.json` | 导出白名单文本摘要，不自动上传或提交 Git |
| `doctor` / `check` | 检查本地工具 / 执行 test、validate、typecheck |

## 技术样例与恢复

```bash
npm run drama -- demo --max-jobs 1
npm run drama -- status --run-dir runs/technical-demo
npm run drama -- demo --render
```

退出码：`0` 成功，`1` 校验或质检失败，`2` 输入/工具错误、审批暂停或尚有等待任务。`--max-jobs` 只控制本轮镜头数，等待任务需要下一次调用继续。

可选 `--wait-seconds 60 --max-polls 10 --poll-interval 2 --poll-backoff 1.5 --poll-max-interval 10` 在当前任务内有界等待；不能与非零 `--max-jobs` 组合。超时保持等待状态和原 provider task ID，不自动重提。详见 [等待规则及时间边界](bounded-waiting.md)。

原声、配音、静音在剧本/分镜顶层以 `sound_mode=model|dub|silent` 明确选择，不能用 `--audio-mode mock/local` 代替声音路由决定。Live 必须显式声明；详见 [音频模式](audio-modes.md)。

`run` 默认只推进至时间线，`--render` 才输出成片。每集使用独立 `--run-dir`；Live 整部剧共享 `--project-workspace`。运行记录绑定剧本、人物、参数和执行上下文，不能更换空账本继续同一运行。恢复到不同挂载点时，先还原同一 SQLite 和全部素材，再执行：

```bash
npm run drama -- rebind-storage /private/project-engine /private/video-store --run-dir /private/runs/EP001 --asset-root /private/references
```

迁移按任务 key、大小与 SHA-256 校验，不复制文件、不请求 API。SQLite 迁移需停 worker 或使用 backup API 做一致快照；不要并发同步数据库。更详细的限制见 [云端持久化](cloud-runtime.md)。

## 本地音频

local 录音在每条对白中填写 `audio_path`，BGM/SFX 填写 `path`，均相对 `--asset-root`。输入录音过长会失败，短音频规范化并补齐，不会覆盖原始录音。

```bash
npm run drama -- audio BOARD.json --characters CHARACTERS.json --mode local --asset-root /private/audio --output-dir /private/rendered-audio
```

可选 `--piper-models /private/voice-map.json --piper-executable piper` 接入已安装的本地 Piper。映射是声音配置 ID 到本地 ONNX 路径的 JSON 对象，旁边必须存在 `.onnx.json`。仅允许不触发自动下载的已审查配置。当前 `run --audio-mode local` 使用录音；Piper 参数只在 `audio` 命令开放，后续可用 `timeline` 和 `render` 手动连接。

## 本地估算与外部数据

官方模型计划无需 API Key，也不会提交真实任务：

```bash
npm run drama -- plan BOARD.json --mode live --provider volcengine-seedance-2.5 --run-dir runs/estimate --episodes 10
```

价格未知时输出 `null`；文档快照只是估算。Live 必须遵循 [开通与审批流程](live-activation.md)。非技术制作的元数据导出要求 `--confirm-public`，该参数仅确认本次导出内容可公开，不能授权后续上传或付费调用。
