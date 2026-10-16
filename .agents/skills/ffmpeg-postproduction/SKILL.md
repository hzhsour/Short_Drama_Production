---
name: ffmpeg-postproduction
description: 使用 FFmpeg/ffprobe 做短剧音画检查、剪辑、字幕、滤镜、转码和交付验证；当用户要本地视频后期或批处理时使用。
---

# FFmpeg 后期

参考 [FFmpeg 官方文档](https://ffmpeg.org/documentation.html)。

## 操作习惯

- 先用 `ffprobe -v error -show_streams -show_format -of json INPUT` 检查编码、帧率、分辨率、时长、音轨、时间基和旋转信息。
- 保留源文件。以镜头 ID 和版本号命名中间结果；输出到新路径，人工确认后才替换交付候选。
- 先做最小可验证命令。滤镜链分步构建，检查时长、首尾帧、字幕字体、音画同步、黑帧、削波和播放兼容性。
- 烧录 ASS/SRT 字幕时明确编码、字体和路径；交付前核对可读性和时码。音频响度目标按目标平台规格确认，不假设所有平台相同。
- 导出后用 `ffprobe` 再读一遍并记录参数、输入/输出文件哈希和异常。批处理要明确输入范围、失败退出码与输出命名。

## 安全

- 不对未知来源的媒体包执行脚本或滤镜文件。不要把用户文件上传到在线转码服务。
- 命令中的文件名应正确引用；先用测试副本，不对原件使用覆盖选项。清理前列出将移除的文件。
- FFmpeg 本地执行不需 API。任何托管渲染、在线增强或付费转码都需另行明确授权。

## v0.2 本地后期与质检入口

在仓库根目录使用统一 CLI，输入必须是已有本地媒体，输出选择不存在的新 `.mp4`。先用 `npm run doctor` 确认 FFmpeg/ffprobe 可用；项目不会在媒体处理时自动安装系统软件或上传源素材。

```bash
npm run drama -- normalize assets/source/EP001-S001.mov renders/EP001-S001-normalized-v1.mp4
npm run drama -- quality runs/technical-demo/EP900-v001.mp4 --timeline runs/technical-demo/timeline.json
npm run drama -- analyze renders/EP001-S001-normalized-v1.mp4 --silence --scenes
```

示例源路径需替换为实际文件，技术演示成片文件名以 `run.json` 的 render 记录为准。`normalize` 兼容本地 FFmpeg 能解码的 H.264/H.265 等输入，缩放加留边保留构图，默认转为 1080×1920、30 FPS、H.264/yuv420p、AAC/48kHz；缺音轨时显式补静音。不覆盖原件或已有输出，恢复/重跑时使用新版本路径。

`quality --timeline` 检查视频/音轨完整解码、H.264/AAC、目标尺寸、帧率、全片时长及音轨时长，并校验时间线覆盖和字幕几何安全区。规范化编码成功不等于质检通过，也不能保证没有视觉瑕疵；字幕字形、黑闪、身份漂移、剧情、口型和响度听感仍须审片。保留失败原因与输入/输出 SHA，不通过删除测试或降低规格掩盖失败。

`analyze` 默认给出本地媒体元数据和哈希；`--silence` 使用 FFmpeg `silencedetect`，`--scenes` 给出像素变化候选时间码。这些候选可能包含剧情停顿、闪光或运动，不自动删镜头或重排主时间线。此模块不做 ASR、语义镜头识别、人物识别、配音或 AI 剪辑优化，不调用 video-use 的 ElevenLabs helpers。需要转录时另行配置已核实的本地 ASR 或明确授权服务，不把已有字幕当作实际转录结果。

完整 `run ... --render` 先用 Remotion 写中间成片，再本地标准化与 `quality`；交付 SRT 必须来自包含片头偏移的最终 timeline。`npm run check` 跑全部自动代码检查，`npm run e2e` 跑 Mock 成片与恢复验证，均不能替代人工观看与真实模型试片。
