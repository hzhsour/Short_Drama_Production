---
name: remotion-production
description: 使用 React 和 Remotion 将短剧镜头、字幕、图形与声音编排为可本地渲染的预览或成片；当用户要创建、修改或渲染 Remotion 工程时使用。
---

# Remotion 短剧合成

参考 [Remotion 官方文档](https://www.remotion.dev/docs/)。

## 项目约定

- 合成从 `src/remotion/` 导出；默认 1080 × 1920、30 fps。真实项目参数以经确认的分镜和交付规格为准。
- 画面和时间由 props/结构化数据驱动。使用帧号表达时间，避免依赖墙钟时间或未加载资源的尺寸。
- 字幕与镜头 ID/时间范围绑定；字体、图片、视频和音频使用项目内路径，保证可追踪。检查移动端字幕安全区和字形回退。
- 长素材使用 `staticFile` 或已确认的静态资源方式；异步媒体在 `delayRender`/`continueRender` 生命周期内可靠加载。
- 音频按分轨组合并监听；控制峰值，检查字幕、口型和对白同步。不要为了速度掩盖缺失资源。

## 渲染与验证

- 先运行 `npm run typecheck`，用短预览核对画面，再用 `npm run preview` 本地渲染。
- 输出写入 `renders/`，不覆盖输入素材。渲染大型项目前确认磁盘空间与目标规格。
- Remotion 是本地工具链；本 Skill 不调用托管渲染或任何付费 API。官方说明见 Remotion 文档与项目 `package.json`。

## v0.2 唯一主时间线与实际入口

复用现有工程及 `ProductionEpisode`，不重复 scaffold Remotion。Python `build_timeline` 将视频/图片镜头、对白、BGM、环境音、音效、字幕及片头片尾转换成 `short-drama.timeline/v1`；`tools/render_episode.mjs` 暂存本地素材并传入 React 合成。缺失素材、哈希变化、源时长不足或时间线断档应停止，不静默循环、补空帧或跳过镜头。

```bash
npm run drama -- timeline runs/technical-demo/storyboard.json --videos runs/technical-demo/video-result.json --audio runs/technical-demo/audio-result.json --output runs/episode-cut-v2.json
npm run drama -- render runs/episode-cut-v2.json renders/episode-cut-v2.mp4
npm run drama -- quality renders/episode-cut-v2.mp4 --timeline runs/episode-cut-v2.json
```

时间线和输出 MP4 使用新路径。输入示例由 `npm run demo` 创建；正式制作替换成对应剧集的已审核资料。`npm run preview` 是原有基础合成预览，`npm run demo` 才执行结构化剧本到 Mock MP4 的完整链；`npm run e2e` 还检查产物与恢复幂等性。`npm run check` 运行代码、格式和类型检查，不能替代渲染/审片。

### 帧号、字幕和音轨

- 分镜与音频清单中的对白/字幕起止帧相对各自镜头；最终 timeline 的 `start_frame/end_frame` 为包含片头的全片绝对帧。当前默认片头、片尾各 30 帧，不能把正文第一句固定在第 0 帧。
- `timeline` 命令输出相邻 `.srt`，完整 `run` 输出 `runs/<任务>/subtitles.srt`；两者由最终 timeline 生成，已包含片头与前序镜头偏移。音频阶段单独输出的 `<Episode>.srt` 不含片头，不能直接交付为最终字幕。
- 过渡在各镜头内部淡入淡出，不用缩短镜头或重叠剪辑改变对白时间。镜头原声默认静音，声音由独立 tracks 明确混合，避免生成视频原声与配音重复。
- Remotion 支持多轨素材及逐条字幕；没有自动口型同步、角色声线克隆或生成画面身份识别。字幕安全区的自动检查是几何约束，最终字形、遮挡、可读性与听感仍需人工查看。

### HyperFrames 包装边界

`npm run drama -- packaging renders/new-intro.mp4 --title "第一集标题" --backend ffmpeg` 创建独立本地包装素材；可选 `--backend hyperframes --project-dir integrations/hyperframes` 使用隔离安装的固定 CLI。HyperFrames 只产出可审核入库的资产，不编辑主时间线，不触发云渲染或远端素材生成。v0.2 主片头/片尾仍由 Remotion 标题卡管理，不能声称包装生成后已自动替换标题卡或接入透明叠层；引用位置和适配要在主时间线中明确实现并校验。能力与实际测试见 `docs/integrations/visual-packaging.md`。
