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
