# 中文 AI 短剧制作项目

这是一个可复用、可审阅的中文 AI 短剧生产工作区，覆盖剧本、人物连续性、分镜、AI 视频素材、Remotion 合成与 FFmpeg 后期。项目默认以本地文件和可替换工具为核心；没有预设付费 API，也不会在未获明确授权时调用外部生成服务。

## 快速开始

环境要求：Node.js 20+、npm、Python 3.10+；Remotion 预览需要本机安装 Chrome/Chromium，转码需要 FFmpeg。Remotion 渲染在本地执行。浏览器不在常见 PATH 位置时，可设置 `CHROME_EXECUTABLE` 指向浏览器可执行文件。

```bash
npm ci
npm test
npm run validate
npm run typecheck
npm run preview
```

`npm run preview` 会将竖屏 Remotion 预览渲染到 `renders/preview.mp4`。测试只用 Python 标准库，不会发起网络请求或调用生成 API。

## 项目流程

1. 在 `production/series-bible.md` 和 `production/characters/` 固定故事设定、角色身份与视觉特征。
2. 在 `production/episodes/EP001/` 编写分集剧本与结构化分镜 JSON。
3. 按分镜逐镜制作或导入 AI 视频素材，将来源与授权记录在素材旁的说明文件中。
4. 在 `src/remotion/` 组合标题、字幕、镜头和音频；用 Remotion 本地渲染。
5. 用 FFmpeg 做规格检查、音频整理、字幕封装和交付编码；保留原始素材。

## 目录

- `AGENTS.md`：项目级协作、安全和交付约定。
- `.agents/skills/`：六个项目级 Codex Skills；按任务加载，不要求平台级安装。
- `docs/`：工作流、项目章程、模板和分镜格式。
- `production/`：剧集圣经、角色圣经、剧本和分镜。
- `assets/`：参考图、生成素材、音频、字幕和字体；大型媒体不进 Git。
- `src/remotion/`：本地竖屏预览合成。
- `tools/`、`tests/`：项目检查器和标准库测试。

## 常用命令

```bash
npm test                 # Python unittest
npm run validate         # 检查目录、Skills 和分镜数据
npm run typecheck         # 检查 Remotion TypeScript
npm run preview           # 渲染本地预览，需要已安装 npm 依赖
python3 tools/validate_project.py
```

开始创作前先阅读 [项目协作规则](AGENTS.md) 和 [生产工作流](docs/workflow.md)。
