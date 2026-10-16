# Skills 来源与使用范围

本仓库将六个流程整理为项目级 Codex Skills，位置为 `.agents/skills/`。首次初始化时检查了已安装的 Codex Skills：当前环境没有 executor 级 Skills，云端已有的 Skills 中也没有短剧剧本、人物连续性、分镜、视频、Remotion 或 FFmpeg 流程。因此将项目需要的工作流按 Codex `SKILL.md` 目录格式直接安装到本仓库，供该仓库内的 Codex 工作加载。

这些 Skills 是针对本项目编写的操作约定，不复制第三方技能文件。Remotion 和 FFmpeg Skill 仅引用其公开官方文档作为工具依据：

- [Remotion 文档](https://www.remotion.dev/docs/)
- [FFmpeg 文档](https://ffmpeg.org/documentation.html)
- [Codex Skills 文档](https://developers.openai.com/codex/skills/)

第三方 AI 视频服务的价格、权限、保留政策和模型能力会变化；Skill 不假设任何服务可用，也不自动调用服务。接入具体提供商前，由项目负责人确认工具、计费方式与素材处理政策。
