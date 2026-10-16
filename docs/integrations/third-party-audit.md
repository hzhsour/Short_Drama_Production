# 第三方 Skills 与视频工具源码审查

审查日：2026-10-16。以下 4 个公开仓库均通过 GitHub HTTPS 实际 clone 成功；记录的是本次取得的默认分支 `main` HEAD，不把 README 活跃度、模型宣传或下载量视为质量证明。只做静态阅读、文件清单、Python AST 导入/调用检查与 SHA-256 记录，未运行第三方安装器、生成程序或服务商调用，未改远端。

源文件证据在 `/tmp/short-drama-thirdparty-audit/<owner>__<repo>/`；版本、LICENSE、SKILL、Python/ shell 源码的 SHA-256 与 Python 导入清单记录在 `/tmp/short-drama-audit/narrative-audit-evidence.json`。这些临时路径用于本轮复核；正式文档应保留下面的固定提交链接与版本号。

| 仓库 | 本次固定完整 SHA | HEAD 最近提交时间（提交者原时区） | 许可证 | 结论 |
| --- | --- | --- | --- | --- |
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | `dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd` | `2026-10-15T02:53:13-07:00` | MIT，2026 drama-skills contributors | 本轮不整体安装；作为创作与连续性参考 |
| [xixihhhh/ai-short-drama-skill](https://github.com/xixihhhh/ai-short-drama-skill) | `38345d39b27eb877978422bff28b5057e783164f` | `2026-08-30T06:12:24+08:00` | MIT，2026 Dramake contributors | 本轮不安装；保留预算、任务恢复等参考价值 |
| [0xsline/short-drama](https://github.com/0xsline/short-drama) | `8979a428c31a865421d661bdb606e24314b683a0` | `2026-04-18T02:26:39+08:00` | MIT，2025 0xsline | 不直接安装；SKILL 缺必需 frontmatter，范围重复 |
| [TateZhouSiu/create-storyboard-skill](https://github.com/TateZhouSiu/create-storyboard-skill) | `4b8662e2fee51b37488c77952bbfa302bfeaf36c` | `2026-05-29T16:11:25+08:00` | MIT，2026 Tate Zhou | 推荐项目级 vendoring，经路径/覆盖防护修复后采用 |

## zenstory-ai/drama-skills

**源码与兼容性。** 仓库有 11 个公开 `skills/*/SKILL.md`，均有 `name`、`description`、`license: MIT`，并提供 `agents/openai.yaml`，基础发现结构兼容 Codex。已阅读核心路由、生产、剪辑 SKILL，逐个提取 11 个 frontmatter，读取 `asset_check.py` 的真实记录校验与跨记录绑定逻辑，并读取 `production_tool.py`、`provider_adapters.py`、`edit_tool.py`、`dashboard_server.py`、`project_tool.py` 的关键执行和写入路径。没有通过 README 宣称推断脚本安全。

**依赖。** Python 脚本使用标准库，脚本声明 Python 3.9+。FFmpeg/ffprobe 是后期的外部二进制依赖；Remotion 字幕叠层还要求独立 Node/Remotion 工作区，工具不会自动安装缺包。`edit_tool.py` 2180–2237 明确处理 Remotion 许可与依赖，并用 `npx remotion render` 子进程渲染。未复核各供应商模型与参数是否仍对当前账号开放，不应把源代码中的型号视为可用性承诺。

**真实副作用与计费边界。** `provider_adapters.py` 32–35 定义 OpenAI、火山引擎 Ark/Seedance、MiniMax HTTPS API 地址；889–938 读取外部 base URL 和环境凭据，构建带 Bearer token 的 HTTP 请求；1268 以后有真实提交/轮询路径；1194 以后会下载服务商返回的 HTTPS URL 并写入临时输出。它可以发送提示词与本地参考媒体，可能产生费用。`production_tool.py` 1329–1357 从项目外配置读取任意 argv 形式的 adapter 命令，1459–1470 使用 `subprocess.run` 启动它，未使用 shell。配置命令仍是代码执行权限边界，应由项目自己的审批与命令白名单控制。其 `confirm_job` 与当前文件指纹绑定、确认消费等防护实际存在，不能据此把工具视为自动获准付费。

Dashboard 会监听本机端口，支持文档写入、脱离终端的长期子进程、打开浏览器和停止进程；源码限制 IPv4 loopback，并有 Host/Origin/token 校验。`project_tool.py` 提供初始化、状态、发布、接受、导出与目录替换，包含真实 mkdir/write/replace/rmtree 操作。不存在“只安装文档就永远没有副作用”的假设。

**价值、重复与不安装原因。** 人物 identity/造型变体分离、状态连续性、原著可追溯、交付检查有参考价值。当前版本核心 `skills/short-drama/SKILL.md` 明确采用每集五份 Markdown 作为创作真相，并反对建立并行结构化真相；本项目 AGENTS.md 要求结构化分镜 JSON，整体套用会产生源数据权威冲突。它还引入独立项目 manifest、状态与确认机制，和本项目已有生产状态重复。故本轮不整体启用，不把其真实生产 adapter 混入默认离线流程；可在有独立适配设计时按单个纯创作 Skill 审查。

主要不可变源码证据：

- [核心工作流与五文档路由](https://github.com/zenstory-ai/drama-skills/blob/dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd/skills/short-drama/SKILL.md)
- [生产确认、adapter argv 与子进程](https://github.com/zenstory-ai/drama-skills/blob/dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd/skills/short-drama-produce/scripts/production_tool.py)
- [真实 HTTP 服务商适配器](https://github.com/zenstory-ai/drama-skills/blob/dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd/skills/short-drama-produce/scripts/provider_adapters.py)
- [FFmpeg 与 Remotion 后期代码](https://github.com/zenstory-ai/drama-skills/blob/dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd/skills/short-drama-edit/scripts/edit_tool.py)

## xixihhhh/ai-short-drama-skill（Dramake）

**源码与兼容性。** `skills/dramake/SKILL.md` 有标准 `name: dramake`、378 字符的 `description`、MIT 及 metadata（版本 0.6.0），可作为 Codex 项目 Skill 被发现。已阅读 SKILL、授权与任务恢复 reference、五个 `scripts/` 源文件；对三个 Python 文件完成 AST 导入与潜在副作用调用检查。`dist/dramake.skill` 是 ZIP，检查得 76 个条目，未执行其中内容。

**依赖与实际行为。** Python 工具仅用 argparse/csv/math/decimal/re/unicodedata/pathlib 等标准库。`validate_plan.py` 读取 CSV、检查跨表 ID、父子状态、任务幂等键、画幅/时长/声线、候选接受区间等，只打印问题，不提交网络请求；`estimate_cost.py` 读取成本 CSV、计算请求量与金额，不调用计费 API；`check_bilingual.py` 只读本仓库文档和版本信息。两个 shell 脚本需要 Bash、FFmpeg/ffprobe，尾帧脚本还需 awk，会写用户指定图片文件。命令参数有引号，未发现 curl-pipe-shell、eval、隐藏下载或自动调用服务商的代码。FFmpeg 接受 URL 作为输入，因此项目包装仍应限制为本地媒体路径。

**付费边界。** SKILL 讨论 Wan、Seedance、MiniMax 等模型，但没有实现这些服务的 SDK/API。其文档区分 plan-only、single-test、approved-batch、autopilot-with-cap，并要求请求指纹、价格核实与有限重试；这是指导规则，不是程序级硬预算闸门。不得因安装 Skill 自动认为用户已授权生成。

**价值、重复与不安装原因。** 较好的补充是按实际可接受秒数计算成本、unknown 任务先恢复后重提、参考职责与禁止迁移属性、冷观众剧情检查。其全流程角色/分镜/连续性规则和本项目已有 Skills 大量重合，且又引入一套 `project-state.md` 与多张 CSV 生产表；默认模型偏好不应替代本项目可配置的服务路由。更关键的是可执行工具位于仓库顶层 `scripts/`，不在 `skills/dramake/` 内，单独复制 Skill 文件夹会遗漏这些工具。故本轮不整体安装，不运行未固定版本的通用技能安装器；按需引用预算与恢复实践即可。

主要不可变源码证据：

- [Dramake SKILL](https://github.com/xixihhhh/ai-short-drama-skill/blob/38345d39b27eb877978422bff28b5057e783164f/skills/dramake/SKILL.md)
- [实际清单校验脚本](https://github.com/xixihhhh/ai-short-drama-skill/blob/38345d39b27eb877978422bff28b5057e783164f/scripts/validate_plan.py)
- [实际预算计算脚本](https://github.com/xixihhhh/ai-short-drama-skill/blob/38345d39b27eb877978422bff28b5057e783164f/scripts/estimate_cost.py)
- [实际 FFmpeg 尾帧脚本](https://github.com/xixihhhh/ai-short-drama-skill/blob/38345d39b27eb877978422bff28b5057e783164f/scripts/extract_tail_frame.sh)

## 0xsline/short-drama

**源码与兼容性。** 根 `SKILL.md` 开头直接是 Markdown 标题，没有 YAML frontmatter，也没有标准 name/description，不能按规范直接安装为 Codex Skill。仓库仅有 Markdown 参考资料、README、LICENSE 和 .gitignore，没有可执行脚本、依赖清单或自动化运行器。已阅读实际 SKILL、`references/compliance-checklist.md` 与 `references/paywall-design.md`，并检查完整受跟踪文件清单。

**依赖与副作用。** 仅作文本指导时没有软件包依赖或内置 API。SKILL 指导 agent 写 `.drama-state.json`、创作方案、角色、分集、审核及导出 Markdown，这些是运行 Skill 后预期的本地文件副作用。导出段建议外部 Markdown 转 Word 网站，但没有自动上传代码；如需要文档转换，应使用项目本地路线。没有真实视频生成或付费 API 代码。

**价值、重复与不安装原因。** 13 类题材、分集钩子、反派层级与付费卡点可作传统微短剧编剧参考，但整体写死 50–100 集、每集至少 800 字、3–5 场及多处逐步确认，和本项目可配置的短时长 AI 生产流程不相符。已有中文剧本 Skill 覆盖核心价值，补 frontmatter 后仍会引入平行状态文件和硬编码创作规则，故不安装。其“合规”文件是作者的创作建议，不是经核实的最新平台规则或法律结论。

主要不可变源码证据：

- [缺 frontmatter 的实际 SKILL](https://github.com/0xsline/short-drama/blob/8979a428c31a865421d661bdb606e24314b683a0/SKILL.md)
- [作者合规自检文档](https://github.com/0xsline/short-drama/blob/8979a428c31a865421d661bdb606e24314b683a0/references/compliance-checklist.md)

## TateZhouSiu/create-storyboard-skill

**源码与兼容性。** `skills/create-storyboard/SKILL.md` 有标准 name/description，并带 `agents/openai.yaml`。`pyproject.toml` 明确 Python >=3.10、`dependencies = []`。已阅读完整 SKILL、runtime reference、LICENSE、pyproject，以及唯一脚本 `create_storyboard_package.py` 的真实模板、所有 import、`write_file` 与完整 main。脚本只导入 argparse 和 pathlib，不含网络、包安装、subprocess 或服务商 API。

**实际行为。** 脚本在 `<root>/storyboard_projects/<slug>/` 声明 16 项目录路径，写 31 个 Markdown 骨架，包括人物/场景/风格/连续性 bible、镜头表、clip 计划、参考组合、交接矩阵、剪辑边界矩阵、双语提示词和图像清单。它不会生成图片、分镜板、视频或真实生成提示词内容；很多字段仍为“待补充”/pending。SKILL 要求确定性板式，但仓库未提供分镜板图像渲染器，不能把模板创建成功报告为图像交付。

**需要修复的本地文件风险。** `write_file` 10–14 只用 `exists()` 判断是否跳过，在 force=True 时 `write_text()` 可覆盖既有文件。main 的 612 行定义 `--force`，617 行直接将未校验的 `args.slug` 拼入路径，绝对路径或 `../` 可逃逸预期目录；已有目录链中的符号链接也可将写入带到其他位置。默认跳过单个旧文件还可能形成新旧模板混合。该风险无需外部 API，即使只离线执行也存在。

**采用建议。** 作为项目级 vendoring 安装是四者中最合适的补充：它聚焦“相邻生成段如何交接、哪些帧可剪、分镜板由确定性工具排版”，比重复安装第二套完整短剧工作流更容易接入。安装时保留 MIT 和作者声明、固定完整 SHA、记录本地变更；从项目 Skill 实际路径运行，不采用文档硬编码的 `~/.codex/skills/`。建议做以下本地修复后采用：

1. slug 限制为简单 ASCII 名称（例如 `^[a-z0-9][a-z0-9-]{0,63}$`），拒绝绝对路径、斜线和 `..`。
2. 规范化并验证项目目录位于指定的 `storyboard_projects/` 下；拒绝目标路径链中的符号链接。
3. 取消覆盖模式；对任何已存在的项目目录或输出预先失败，避免覆盖、静默跳过和半新半旧输出。文件使用排他创建。
4. 在 Skill 首部加入本项目优先规则：中文、现有剧本/人物/分镜 schema 和 ID 为权威，scaffold 为可选辅助目录；clip 时长上限由已配置 provider 能力决定，不能把 SceneDance 的 15 秒硬写成所有供应商限制。
5. 移除对 agent 模型与 reasoning effort 的全局指派，保持当前会话配置；画像生成和视频生成仅输出计划，实际外部调用仍需项目审批，安装本身不触发计费。
6. 新目录模板仍标为 planning，不凭脚本成功宣称人物一致性、分镜图、AI 媒体或成片已制作完成。

主要不可变源码证据：

- [实际 SKILL](https://github.com/TateZhouSiu/create-storyboard-skill/blob/4b8662e2fee51b37488c77952bbfa302bfeaf36c/skills/create-storyboard/SKILL.md)
- [实际目录/模板写入脚本](https://github.com/TateZhouSiu/create-storyboard-skill/blob/4b8662e2fee51b37488c77952bbfa302bfeaf36c/skills/create-storyboard/scripts/create_storyboard_package.py)
- [依赖与 Python 版本](https://github.com/TateZhouSiu/create-storyboard-skill/blob/4b8662e2fee51b37488c77952bbfa302bfeaf36c/pyproject.toml)
- [MIT 许可证](https://github.com/TateZhouSiu/create-storyboard-skill/blob/4b8662e2fee51b37488c77952bbfa302bfeaf36c/LICENSE)

本项目随后按上述边界安装 Tate 的安全适配版：新增项目约束、修复路径与覆盖、保留 MIT 及固定版本来源；五项离线安全回归测试实际通过。详细修改见 `.agents/skills/create-storyboard/UPSTREAM.md`，可核对上游与本地 SHA-256。静态审查不等于对上游未来提交的安全保证。

## remotion-dev/skills（官方）

**版本与可访问性。** 实际 clone 成功。固定 SHA `1441a11e95db35443bd76bb318386c0d3ca00053`，最近提交 `2026-10-16T10:09:16+02:00`；`package.json` 的 Skills 版本为 `4.0.536`。README 明确支持 Codex、Claude Code 等 Agent Skills 客户端。12 个 `skills/*/SKILL.md` 均有标准 frontmatter，内含最佳实践路由、React 组合、字幕、渲染、多媒体等入口。

**许可核实。** 本固定仓库根目录、所有受跟踪文件及取得的历史中没有 LICENSE/LICENSE.md/LICENSE.txt；`package.json` 无 `license` 字段。仓库公开、官方提供安装命令，不能代替明确的再分发许可。故本轮不把其文本源码复制进公开项目，也未执行通用安装器。保留固定版本、官方链接与安装入口说明；继续使用本项目原创 `remotion-production`。Remotion 库的使用许可需按其官方条款独立确认，不能将 Skills 的许可缺失推导成软件库没有许可。

**代码与安装审查。** 已阅读 `scripts/sync-agent-skills.ts`、`sync-embedded-skills.ts`、`prepare-embedded-skills.ts`。它们创建 `.agents/.claude` 符号链接、重写 Markdown 相对链接和将嵌入 SKILL 改名为 REFERENCE，属于上游发布维护脚本，不能在本项目不加区分执行。`package.json` 只有 `dev: remotion studio`，无安装生命周期脚本，但其 monorepo `catalog:` 开发依赖不适合作为生产工程依赖清单直接复用。真正运行渲染仍由现有 Remotion、React、浏览器和本地 FFmpeg 处理；地图/API示例与 SaaS/Lambda 内容不在本次离线授权范围。

**重复与价值。** 官方 Skills 能显著补充媒体时长、混合音轨、字幕安全区域与确定性渲染指导。最佳实践路由还引入“先 Studio、只有明确要求才 render”的交互约束；用户本次明确要求端到端输出 MP4，因此不产生新的确认要求。此次只按官方文档完善既有时间线，没有重新搭建 Remotion 项目或安装重复工程。

不可变来源：

- [官方 README 与安装入口](https://github.com/remotion-dev/skills/blob/1441a11e95db35443bd76bb318386c0d3ca00053/README.md)
- [package.json](https://github.com/remotion-dev/skills/blob/1441a11e95db35443bd76bb318386c0d3ca00053/package.json)
- [最佳实践路由](https://github.com/remotion-dev/skills/blob/1441a11e95db35443bd76bb318386c0d3ca00053/skills/remotion-best-practices/SKILL.md)
- [维护脚本](https://github.com/remotion-dev/skills/blob/1441a11e95db35443bd76bb318386c0d3ca00053/scripts/prepare-embedded-skills.ts)
- [官方 Skill 文档](https://www.remotion.dev/docs/ai/skills)；[软件许可](https://www.remotion.dev/license)。

## jtydhr88/screenwriting-skills

**版本、许可与格式。** 实际 clone 成功，固定 SHA `51115f18d160aa8b2ac5813e4432b6f0b425358f`，最近提交 `2026-10-02T21:34:42-04:00`。根 LICENSE 为 MIT，版权 2026 Terry Jia；NOTICE 明确指出 MIT 仅覆盖原创架构、工作流、检查单和工具，不涵盖书籍、出版剧本、现代译本的引文。26 个 Skills 位于 `plugins/screenwriting/skills/`，可以采用项目级格式安装，但不能把所有 references 当作 MIT 原创一并复制。

**源码与实际检查。** 已阅读 `sw-workflow/SKILL.md`、`sw-chinese-series-practice/SKILL.md`、`sw-series-engine-bible/SKILL.md`、LICENSE/NOTICE 和 `tools/check-skills.py`。校验脚本仅使用 Python 标准库读取 frontmatter/相对链接，检查 name、描述长度及路径是否存在；无包安装、网络请求或子进程。对该只读脚本实际执行 `python3 tools/check-skills.py --strict`：26 Skills，0 errors、0 warnings。主内容是文本指导，无内置图片/视频/TTS API。

**价值与不安装理由。** 国产剧文档链、剧集引擎、bible、人物网和场景价值转折对创作有参考价值。大部分方法侧重长片/长剧，页数与播出体系不能直接套进两分钟竖屏短剧；部分政策事实来自 2014–2016 书目，原文也要求核对现行文件。整体复制还会带入出版引文的额外权利问题、平行 story-bible 和多级路由。保留来源作为按需阅读材料，本次不安装整包、不再分发其 reference 引文，不替代项目中文剧本 Skill。

不可变来源：

- [许可](https://github.com/jtydhr88/screenwriting-skills/blob/51115f18d160aa8b2ac5813e4432b6f0b425358f/LICENSE)、[引文权利 NOTICE](https://github.com/jtydhr88/screenwriting-skills/blob/51115f18d160aa8b2ac5813e4432b6f0b425358f/NOTICE)
- [国产剧 Skill](https://github.com/jtydhr88/screenwriting-skills/blob/51115f18d160aa8b2ac5813e4432b6f0b425358f/plugins/screenwriting/skills/sw-chinese-series-practice/SKILL.md)
- [真实校验脚本](https://github.com/jtydhr88/screenwriting-skills/blob/51115f18d160aa8b2ac5813e4432b6f0b425358f/tools/check-skills.py)

## divolleggett/character-consistency-skill

**版本、许可与格式。** 实际 clone 成功，固定 SHA `f77c2734afbda6f2cac539ff408f8682d5061b59`，最近提交 `2026-08-03T16:25:40+08:00`，MIT。根 SKILL 具有 `name: character-consistency`/description，Codex 格式可发现，但名字和本项目已有 Skill 完全相同，不应覆盖现有目录。

**真实代码与费用。** 已完整阅读 `scripts/consistency.py`，仅用 argparse/json/os/time/urllib 等 Python 标准库。无 pip 依赖、无远程安装器；然而一运行脚本就先 `POST https://api.atlascloud.ai/api/v1/model/generateImage`，接着 `generateVideo`，使用 `ATLASCLOUD_API_KEY`/`ATLAS_API_KEY`。模型字符串为上游 AtlasCloud 自己的 `bytedance/seedream-v5.0-pro/text-to-image` 和 `bytedance/seedance-2.0/reference-to-video`，不能把它们写成火山引擎官方 model ID。脚本执行远端轮询并下载返回 URL，固定写入 `storyboard.jpg`/`consistency.mp4`，可能覆盖同名输出。

**采用决定。** 上游 SKILL 文档要求未授权时先确认花费，但脚本没有程序级批准、预算、幂等账本和重复提交保护；一次运行连续触发两次真实生成。其“几美分”口述价格没有经过官方核价，本项目不用作费用依据。整张多格故事板可能帮助视觉锚定，仍不能保证身份不漂移；该输入方式也不能默认适合每个官方模型。故不安装、不执行脚本，继续用已扩展的人物档案、镜头引用与人工审核机制。

不可变来源：

- [MIT 许可](https://github.com/divolleggett/character-consistency-skill/blob/f77c2734afbda6f2cac539ff408f8682d5061b59/LICENSE)
- [SKILL](https://github.com/divolleggett/character-consistency-skill/blob/f77c2734afbda6f2cac539ff408f8682d5061b59/SKILL.md)
- [真实收费、轮询与下载代码](https://github.com/divolleggett/character-consistency-skill/blob/f77c2734afbda6f2cac539ff408f8682d5061b59/scripts/consistency.py)

## heygen-com/hyperframes

**版本、许可、官方能力。** 实际 clone 成功，固定 SHA `4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22`，最近提交 `2026-10-16T10:54:31Z`。根 LICENSE 为 Apache-2.0，2026 HeyGen, Inc.。源码 CLI 包 `@hyperframes/cli` 版本 `0.8.164`；官方发布流程把它改名为 npm `hyperframes`。README、CLI 与发布代码相互印证，不是根据同名 npm 包猜测来源。

它将 HTML/CSS、媒体和可 seek 动画逐帧渲染为视频。原生能力包括动态标题、叠层、运动图形、转场、片头/片尾与预告包装；支持本地 MP4、透明 WebM/ProRes MOV、PNG 序列等。它本身不是已授权的剧情镜头生成模型。Remotion 同样可做包装，因此仅在 HTML 动画有实际优势时选择它；最终剧情时间线仍由 Remotion 统一管理。

**依赖与安装代码。** 阅读了 `packages/cli/package.json`、`src/commands/init.ts`、`render.ts`、`transcribe.ts`、`tts.ts`、`telemetry/policy.ts`、最小 blank 模板及 `.github/workflows/publish.yml`。CLI 要求 Node >=22、FFmpeg/ffprobe、Chrome/Chromium；依赖 puppeteer-core/@puppeteer/browsers、sharp、esbuild 等，需考虑浏览器与原生二进制。CLI 包无 install/postinstall/preinstall，monorepo 根 `prepare` 会安装 lefthook Git hooks，不能把源码工作区全量安装当作轻量 CLI 安装。依赖安装宜固定版本和锁文件并显式禁用生命周期脚本，原生依赖需要独立验证。

`init` 会写项目、保持官方 Skills 更新、可能从网络取模板，也可转码不受浏览器支持的素材。默认 blank 模板引用固定 GSAP CDN；可换成本地固定资源以便离线复现。安装 Skill 路由还可能按需下载更多工作流，默认触发素材获取与确认循环；本次不安装其宽泛 router，不让其接管所有“制作视频”请求。项目直接创建受控独立 HTML 包装项目，使用已审查 CLI 的 check/render。

**网络与外部服务。** `HYPERFRAMES_NO_TELEMETRY=1` 或 `DO_NOT_TRACK=1` 在真实 policy 代码中关闭遥测；`CI=1` 适合无人值守调用，`HYPERFRAMES_SKIP_SKILLS=1` 防止 init 的 Skills 检查。关闭遥测并不等于禁止所有网络：浏览器安装、CDN、registry/素材仍须另行约束。支持 HeyGen 云渲染、AWS/GCP，以及 media-use 的生成服务，这些不是本地 render 的必要前提；本项目不调用 cloud/lambda/cloudrun/publish、不获取云端素材、不上传私人素材。

本地 `transcribe` 实际支持 Whisper/Parakeet，可下载运行时和权重；`tts` 调用本地 Kokoro-82M。它们存在于上游不等于已在本项目配置、验证中文或可商用声线；本次不依赖它们，也没有通过 HyperFrames 调用 ElevenLabs。

**独立包装协议与边界。** 将包装作为独立资产请求：`asset_id`、`role`（intro/outro/overlay）、`title`、`duration_frames`、`width/height/fps`、已授权本地输入与输出根目录；冻结输入与版本 SHA。Adapter 输出本地文件、编码、帧数、尺寸、SHA-256 和来源元数据，不修改剧集主时间线。Remotion 只引用审核通过的包装资产，并决定放入位置、字幕层级及混音。源文件和现有输出不能被覆盖；透明素材不能先压成不支持 alpha 的 H.264。由本项目 FFmpeg fallback 可离线生成普通片头，以便未装 HyperFrames 时仍能跑通核心链。

已核对的官方 CLI 形状（下列是适配协议示意，实际命令由项目已固定安装的 CLI 绝对路径组成；不要用可变的 npx 自动下载替代）：

```text
hyperframes check <isolated-project-directory>
hyperframes render <isolated-project-directory> --fps 30 --format mp4 --quality draft --output <new-output-file>
hyperframes render <isolated-project-directory> --fps 30 --format webm --quality draft --output <new-overlay-file>
```

`check` 已包含 lint；新版以 check 为正式入口，validate/inspect/layout 是兼容别名。根 HTML 明确 `data-composition-id`、`data-start`、`data-duration`、`data-width`、`data-height` 与 `data-fps`，CSS/viewport 同步 1080×1920；在 `window.__timelines` 注册可 seek 时间线。渲染结果经 ffprobe 和解码验证后才入库。

**本轮实际集成结果。** 在 `integrations/hyperframes/` 以锁文件隔离安装 `hyperframes@0.8.164` 与 `gsap@3.14.2`，安装时禁用生命周期脚本；使用项目自有模板、本地 GSAP 与临时复制的中文字体，没有运行时 CDN。真实 check/render 已生成 320×568 与 1080×1920、30 FPS、1 秒 MP4，均通过完整 FFmpeg 解码；另有 FFmpeg fallback 1080×1920/AAC 片头。输出 SHA 及结果见 [verification.json](../../integrations/hyperframes/verification.json)，执行方法见 [独立包装文档](visual-packaging.md)。普通 sandbox 曾因 loopback 浏览器服务权限失败，授予本轮命令所需权限后成功；只读 home 引起上游 history 未记录警告，项目保留警告并自行保存资产元数据。没有把此包装测试写成剧情视频生成成功。

不可变来源：

- [Apache-2.0 LICENSE](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/LICENSE)
- [CLI 版本与依赖](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/packages/cli/package.json)
- [真实 init](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/packages/cli/src/commands/init.ts)、[render](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/packages/cli/src/commands/render.ts)、[遥测关闭](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/packages/cli/src/telemetry/policy.ts)
- [最小 HTML 模板](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/packages/cli/src/templates/blank/index.html)
- [npm 改名发布证据](https://github.com/heygen-com/hyperframes/blob/4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22/.github/workflows/publish.yml)

## browser-use/video-use

**版本与许可。** 实际 clone 成功，固定 SHA `43cfc566833548093455c9d4a46bd69913b7e552`，最近提交 `2026-10-08T15:16:59-07:00`，MIT，版权 2026 Browser Use。项目版本 `0.1.0`，Python >=3.10；根 SKILL frontmatter 可用且安装文档列出 Codex。但默认形态是会话式剪辑 Skill 和 helpers，不是可替换的统一视频生成 API。

**真实依赖、源码与安装。** 阅读了 pyproject、install.md、SKILL 及 `helpers/transcribe.py`/`transcribe_batch.py`/`timeline_view.py`/`pack_transcripts.py`/`render.py`/`grade.py` 的实际执行路径。依赖 requests、librosa、matplotlib、Pillow、numpy，以及 FFmpeg/ffprobe；Manim/LaTeX、yt-dlp、HyperFrames、Remotion 是按用例安装的可选项。`skills/manim-video/scripts/setup.sh` 只检查本机命令和 import，不会自动安装包。`install.md` 会引导 pip/uv、系统包管理器、用户级 Skill 软链接、保存 ElevenLabs 密钥到 .env；本项目不执行这条安装流程，也不按原文让用户在聊天里粘贴密钥。

`transcribe.py` 将本地视频提取为 16kHz PCM WAV，真实 `POST https://api.elevenlabs.io/v1/speech-to-text`，`model_id=scribe_v1`，请求 word-level timestamps、diarization 与 audio events，上传文件并可能计费。批量脚本默认四个并发 worker。缓存按文件名与音轨索引命中，不是对源文件内容做哈希，因此上游“存在就缓存”的行为不能直接当作本项目的幂等/内容变更保护。

| 用户需求 | 官方源码实际支持情况 | 项目采用边界 |
| --- | --- | --- |
| 素材属性与可视分析 | FFprobe 元数据、区间 filmstrip、波形 | 本地 FFmpeg/ffprobe 实现属性和检测报告；不声称视觉剧情理解 |
| AI 辅助剪辑 | Agent 根据转录内容人工推理，输出 EDL；render.py 按 EDL 裁剪、concat、叠层、调色和字幕 | 仅作为未来建议来源；EDL 不直接修改主时间线 |
| 镜头识别/整理 | 有帧采样和 transcript inventory；未发现独立可靠的语义镜头分割器/人物识别模型 | 不能报告已实现自动语义镜头识别；本地场景变化阈值也只给候选点 |
| 语音转录 | 默认 ElevenLabs Scribe 真实 API，非离线 ASR | 默认禁用；可后续接本地 Whisper/whisper.cpp，需另装已授权权重并验证中文 |
| 静音处理 | 从转录时间戳推断 >=400ms 等空隙，AI 决定保留/删除；没有独立自动静音删减入口 | 本地 FFmpeg silencedetect 提供候选区间，不自动删剧情停顿 |
| 字幕辅助 | Scribe word timestamps 分组和主时间线 SRT 偏移，render.py 可 burn in | 本项目使用已锁定对白/字幕时间轴；无转录也可 Mock 测试 |
| 成片优化 | FFmpeg grade、音频短淡入淡出、loudnorm，仍需审阅 | 以项目局部资产建议和 QC 报告接入；Remotion 负责主片 |

**安全与主时间线决定。** helpers 使用 argv 子进程而不是 shell 字符串，但 `render.py/grade.py` 多处 FFmpeg `-y` 会覆盖目标，且 EDL 可指向外部路径/URL，不能不加本地路径及输出隔离规则直接运行。上游总流程还要求策略确认、默认字幕/声音服务，和本项目批量自动编排不完全相容。故不安装完整 Skill/依赖、不调用 Scribe、不运行其最终 render；本项目提供独立本地分析，记录源 SHA-256、时间码、候选区间和人审状态。未来若连接真实 ASR，须通过统一费用/授权门并保留字级时间戳，任何剪辑建议必须经分镜约束转换成 Remotion 的唯一主时间线。

不可变来源：

- [MIT LICENSE](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/LICENSE)、[依赖](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/pyproject.toml)
- [安装过程](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/install.md)
- [真实 Scribe 付费上传](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/helpers/transcribe.py)
- [区间 filmstrip 与波形](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/helpers/timeline_view.py)
- [EDL 主片渲染与覆盖行为](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/helpers/render.py)

## 审查后的执行约束

项目级可分发安装仅新增一个明确 MIT 且离线可用的 create-storyboard 安全适配版，保留原六个 Skills。HyperFrames 和 video-use 的整套 Skills 未启用；它们的角色以本项目可插拔包装/分析协议表达。未运行来源不明的远程安装器、没有使用付费 API、没有上传私人素材。所有“真实模型能力”“中文声线质量”“自动人物一致性”仍必须在授权后的具体模型与素材上验证，不能从本次 Mock 验收推断。
