---
name: chinese-short-drama-script
description: 为中文竖屏短剧开发系列设定、分集大纲、场景节拍、剧本和结尾钩子；当用户要写作、改写或诊断短剧故事时使用。
---

# 中文短剧剧本创作

## 工作步骤

1. 先读项目圣经、人物资料、已有剧本和用户约束。未知的受众、集数、单集时长、平台和结尾方向标成待确认。
2. 把核心设定压缩成主角、目标、阻力、代价和独特承诺。确认每场都推进目标、关系或信息。
3. 先写分集大纲：开场钩子、目标、阻力、升级、中点变化、选择及代价、结果、场尾钩子。
4. 按场景格式写可拍摄的动作和对白。对白要体现人物关系与潜台词；用动作、反应、道具和声音表达情绪，不把心理说明冒充画面。
5. 检查因果链、角色动机、节奏、设定冲突和本集结尾承诺。改编已有内容时保留用户明确要求的事实。

## 交付

在 `production/episodes/EP###/` 保存剧本和大纲。沿用 `docs/templates/` 的格式，标出版本、状态和待确认项。未经用户提供，不凭空确定真实人物、品牌、历史事实或故事结局。

## v0.2 项目入口与结构化交接

- 在仓库根目录使用 `npm run drama -- <命令>`；Node 包装器负责选择 Python。先运行 `npm run doctor` 检查本机依赖，该命令不获取密钥或请求模型 API。
- `init-series`、`init-episode` 只建立待填写草稿与任务表，创作判断仍由当前 Codex 会话与用户完成。`convert-script` 只把已经写明的 `scenes/shots` JSON 确定性转换为 Storyboard JSON，不会调用文本 LLM，也不会从自由文本自动推断镜头或补全故事。
- 对照 `docs/templates/script.schema.json`、`characters.schema.json` 与 `storyboard.schema.json` 填写结构化资料。每个镜头保留 Episode/Scene/Shot/Character ID、帧数、动作、对白时段、声音需求和参考资料；不要把 Markdown 大纲当成可直接执行的 JSON。

```bash
npm run drama -- init-series urban-mystery --title "都市悬疑草案" --genre "都市悬疑" --episodes 10 --minutes 2
npm run drama -- init-episode production/series/urban-mystery EP001
npm run drama -- validate --characters examples/technical-demo/characters.json --script examples/technical-demo/script.json
npm run drama -- convert-script examples/technical-demo/script.json --characters examples/technical-demo/characters.json --output runs/ep001-script-review/storyboard.json
```

示例转换输出须选不存在的新路径；不覆盖用户剧本或已有分镜。转换后用 `validate --characters <人物JSON> --storyboard <分镜JSON>` 核对声明，再交给 `storyboard-breakdown`、`character-consistency` 与 `ai-video-production`。自动连续性检查只核对已声明的设定与引用，故事因果、情感成立和真实生成画面的身份一致性仍须人工审阅。

需要验证完整技术链时，使用 `npm run demo` 或 `npm run e2e`，其输入为公开虚构示例，输出带技术测试标识。不能把占位素材和测试音调当作真正的 AI 剧情成片；生产任务先完成故事与人物确认，再进入具体服务的费用授权流程。
