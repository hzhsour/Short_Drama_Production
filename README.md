# 中文 AI 短剧制作系统

以 Codex Skills 组织故事创作，以 Python 制作引擎管理镜头任务、审批和恢复，以 Remotion 管理主时间线，以 FFmpeg 整理交付规格。复用第一阶段的项目结构、六个自定义 Skills 与竖屏预览，升级版本为 **0.2.0**。

**默认 Mock：不调用付费 API。** 已实际完成中文结构化剧本 → 分镜 → 本地占位镜头 → 角色测试音/字幕 → Remotion → FFmpeg → 1080×1920 MP4。测试片明确标记为技术测试，不能代表真实 Seedance 生成或中文配音已验收。

## 快速开始

需要 Node.js 20+、Python 3.10+、FFmpeg/FFprobe、本机 Chrome/Chromium 和中文字体。npm 依赖固定在锁文件；核心 Python 模块只用标准库。浏览器可通过 `CHROME_EXECUTABLE` 指定，Python 可通过 `PYTHON_EXECUTABLE` 指定。

```bash
npm ci
npm run doctor
npm run check          # test + validate + typecheck
npm run preview        # 保留的第一阶段 Remotion 预览
npm run e2e            # 完整技术出片，并验证重复运行不会重复提交/改写成片
```

成片默认位于 `runs/technical-demo/EP900-v001.mp4`，制作记录、字幕、时间线和质检报告在同一运行目录。需要本地浏览器进程权限；所有测试素材均由本地工具生成，不需要生成服务密钥。已有输出经过哈希验证后复用，输入改变时需要新的运行目录。

## 统一操作入口

```bash
npm run drama -- init-series my-series --title "都市谜案" --genre "都市悬疑" --episodes 10 --minutes 2
npm run drama -- init-episode production/series/my-series EP001
npm run drama -- validate
npm run drama -- demo --max-jobs 1   # 有界推进，未完成时退出码为 2
npm run drama -- demo --render       # 从检查点恢复
npm run drama -- status --run-dir runs/technical-demo
```

创意写作由 Codex 按 Skills 完成，`convert-script` 负责已结构化剧本的确定性转换，不内置另一个文本模型或自然语言自动编剧服务。草稿允许保留空分镜，执行生成前要求完整的镜头和角色关联。

## 能力及验收边界

| 模块 | 当前结果 |
| --- | --- |
| 人物、剧本、分镜 | 严格校验、元数据连续性检查、结构化转换；无法自动保证生成画面不变脸 |
| 视频引擎 | Mock 实际出素材；SQLite 状态/预算预留/有限重试/重复提交防护/哈希入库 |
| Seedance | 官方资料核实；火山 2.5/2.0 适配器仅经过模拟 HTTP 合约测试，Live 关闭 |
| 音频 | 测试音、本地录音、多声音配置、BGM/SFX、SRT、时长和响度检查；Piper 接口未使用真实模型验收 |
| Remotion/FFmpeg | 多镜头、图片/视频、字幕、混音、片头尾、转场、规格归一化和成片质检实际通过 |
| HyperFrames | 独立可选包装项目，固定版本并实际本地渲染；不控制主时间线 |
| video-use | 审查后未安装；本地 FFmpeg 替代媒体探测、静音及像素切点分析，无 ASR/语义剪辑 |
| 云端 | 有界 worker、恢复和手动技术验收 Actions 已配置；对象存储后端、永久服务、手机入口和外部队列尚未部署 |

## Skills

保留六个自定义项目 Skills，另安装一份经过安全改编的 MIT `create-storyboard` 导演文档工具。其余候选因重复、外部付费调用、安装结构或许可证问题未复制；官方 Remotion Skills 的目标版本未提供明确许可文件，保留来源和版本记录。逐项结果见 [Skills 来源](docs/skill-sources.md) 与 [第三方审查](docs/integrations/third-party-audit.md)。

## 目录

| 目录 | 用途 |
| --- | --- |
| `.agents/skills/` | 项目级 Codex Skills、合法分发的第三方工具及来源记录 |
| `production/`、`docs/templates/` | 原有创作资料与人物/剧本/分镜模板；初始化不会覆盖已有文件 |
| `src/short_drama/` | CLI、制作管线、模型适配器、状态、存储、音频、分析及质检 |
| `src/remotion/` | 保留旧预览，新增数据驱动的 `ProductionEpisode` |
| `config/` | 默认关闭 Live 的模型目录和未批准的预算/审批示例 |
| `examples/technical-demo/` | 可公开的虚构中文验收输入 |
| `integrations/hyperframes/` | 可选视觉包装，依赖与主项目隔离 |
| `runs/`、`storage/`、`renders/` | 被 Git 忽略的状态、素材和输出；需要自行持久备份 |

## 文档

- [项目规则](AGENTS.md) · [生产架构](docs/architecture.md) · [中文 CLI](docs/cli.md)
- [真实生成的开通与审批](docs/live-activation.md) · [Seedance 官方核实](docs/integrations/seedance-api-audit.md)
- [音频工具](docs/integrations/audio-tools.md) · [视觉包装与素材分析](docs/integrations/visual-packaging.md)
- [云端执行与持久化](docs/cloud-runtime.md) · [本次升级验收报告](docs/upgrade-report.md)

GitHub 仅保存可公开的代码、模板和配置。密钥、私人剧本/参考图、审批文件、数据库和大型媒体不得自动上传；`export-metadata` 只导出白名单文本摘要，不会自动提交或上传。首次真实生成必须先确认创意、参考图权限、账户资格、准确报价、请求哈希和预算范围，再由用户明确批准。
