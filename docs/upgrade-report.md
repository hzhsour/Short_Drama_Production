# AI 短剧自动化制作系统升级交付报告

验收日期：2026-10-16，版本 0.2.0。已实际导出中文技术测试 MP4；视频和声音使用本地占位素材。**没有调用真实 Seedance、付费 TTS 或托管渲染，也没有开通付费服务。**

全文状态含义：**A＝已实现，并通过实际本地测试；B＝已实现，但仅经过 Mock/接口合约测试；C＝已设计，但尚未实现或部署验收；D＝因 API、权限或费用而暂不可用。** 同一模块按子能力分别标注，不能将 A 的本地技术出片理解为真实生成模型验收。

## 1. 原有功能审查【A】

保留原规则、六个 Skills、创作模板、结构化分镜、Remotion 预览和 FFmpeg 流程，没有覆盖创作资料。旧预览 180 帧、6 秒渲染通过；新增引擎与 `ProductionEpisode`。补齐 `.gitkeep`，避免全新 clone 因缺空目录校验失败。

## 2. 七个第三方 Skills【A：源码审查；按需安装】

七个仓库均实际取得源码，核对维护、格式、许可、依赖及副作用；固定 SHA 和证据见 [来源记录](skill-sources.md)、[源码审查](integrations/third-party-audit.md)。

| 候选 | 许可与安装结果 |
| --- | --- |
| ZenStory Drama Skills | MIT；不安装整体套件。Markdown/JSON 权威源冲突，状态/付费接口重复 |
| Dramake | MIT；不安装。CSV 状态重复，单独 Skill 目录缺脚本 |
| short-drama | MIT；不安装。缺标准 frontmatter，固定长集数规则不适配 |
| create-storyboard | MIT；安装安全适配版，修复路径/覆盖/软链接问题，保留归属；五项测试通过 |
| Remotion 官方 Skills | 未见明确许可文件；未复制，保留官方入口，沿用原创 Skill |
| screenwriting-skills | 原创 MIT，出版引文除外；不整包复制，按来源阅读 |
| character-consistency | MIT；同名冲突且直接调用 AtlasCloud 收费接口，缺预算/审批；不安装 |

原六 Skills 已更新到实际 CLI；未执行未经审查的远程安装脚本。

## 3. HyperFrames 集成【A】

固定 `hyperframes@0.8.164`，Apache-2.0，Node >=22；隔离锁定依赖，使用 `--ignore-scripts` 安装。本地模板/GSAP/中文字体实际通过 check/render，导出 1080×1920、30 FPS、1 秒 H.264。默认 FFmpeg 也实现中文标题、淡变和 AAC 音轨。

仅生成独立资产/SHA，Remotion 控制主时间线。关闭遥测和自动更新；需要浏览器 loopback 权限，只读 home 的 history 警告已记录。见 [包装文档](integrations/visual-packaging.md)、[实测记录](../integrations/hyperframes/verification.json)。

## 4. video-use 集成决定【A：审查与本地替代；C：外部接入】

审查固定版源码后未安装其 ElevenLabs 转录/EDL 剪辑流。项目实际实现 ffprobe 元数据、FFmpeg 静音和像素变化切点检测；只输出建议数据，不改写素材或时间线。未实现 ASR、语义镜头识别、角色识别或自动剪辑优化；video-use 仅保留禁用 provider，没有上传素材或导入 ElevenLabs。

## 5. Remotion 升级【A】

保留旧 composition，新增数据驱动主时间线：多镜头、图片/视频混合、按帧字幕、角色音轨、BGM、环境音/SFX、淡变/硬切、片头尾。输出 9:16、1080×1920、默认 30 FPS，经 FFmpeg 统一 H.264 MP4/AAC 48 kHz。字幕含片头偏移、安全区域与来源镜头；中文可读性仍需人工观看。

## 6. Seedance 2.5 官方核实【A：文档；D：真实调用】

截至核实日，官方已公开 2.5 开发者 API：火山 `doubao-seedance-2-5-260628`，BytePlus `dreamina-seedance-2-5-260628`。核实异步创建/查询、Bearer 认证、开通、区域、文/图生、多参考、音视频、4–30 秒、延长编辑、9:16、分辨率、编码、定价、配额和审核限制，见 [逐项官方证据](integrations/seedance-api-audit.md)。

原生 24 FPS；首尾帧/编辑/延长有 `adaptive` 限制，不能给所有任务机械指定宽高比。真人人脸参考须走官方合规授权方案。服务区域不等于账号客户国家资格；本账号权限和配额未知。文档公开不表示已充值、授权或出片。

## 7. Adapter、备选与费用门控【A+B+D】

【A】分镜任务经恢复、下载/本地生成、解码、SHA 入库；SQLite 保存请求、provider ID、预算预留、有限重试及事件。未知提交暂停，防止重复付费。

【B】火山 2.5/备选 `doubao-seedance-2-0-260128` 的提交/轮询/下载仅模拟 HTTP 测试。预算、报价有效期、请求/创意哈希审批、共享账本有门控。【D】Live 全关；BytePlus/泛称 2.5 不可执行。短于 4 秒须按生成时长预算再裁切。

## 8. 角色一致性与分镜【A】

扩充角色 ID、年龄、面部/发型/身形、服装、表情、固定道具、多视角参考、场景造型、关系与历史镜头。结构化剧本可确定性转换分镜；严格检查引用、时长和人物资料。连续性规则核对服装/道具变化、时间、空间、出入画与关系变更理由。自动规则检查的是元数据，无法保证生成画面不变脸或剧情表演正确。

## 9. 配音、字幕与音频【A+B+D】

【A】角色声音、对白/镜头 ID 关联录音和测试音；生成 SRT，检查时长、解码、采样率、响度/峰值并接入混音。测试音不是中文配音。

【B】Piper 接口仅合同测试，未安装/下载/真实合成。引擎为 GPL-3.0-or-later，声线权利另审。【D】真实声音需预装合法模型及试听；拒绝 pinyin 自动下载。`run --audio-mode local` 使用录音，Piper 仅独立 `audio` 命令开放。见 [音频审查](integrations/audio-tools.md)、[CLI](cli.md)。

## 10. 自动剪辑与 MP4【A】

已实际贯通：中文结构化剧本 → 校验/分镜 → Mock 镜头 → 音频/字幕 → 时间线 → Remotion/FFmpeg → MP4。按镜头追溯、缺失/哈希检查、裁切、字幕与混音；不覆盖原文件。支持不同编码/帧率/采样率整理；检查解码、尺寸、帧率、时长、音轨和时间线空缺。

已产出约 6 秒中文技术测试片，H.264/AAC 48 kHz；仍保留人工一致性、口型、听感和响度警告，不声称专业母带或真实剧情成片。

最终输出：`runs/technical-demo/EP900-v001.mp4`，SHA-256 为 `f937c83f326a1d1a4d9afcc4e2cab3b7caff74c3e9632f6bc6f5c5ce50ed58af`。阶段与质检保存在同目录 `run.json`、`quality.json`；媒体不提交 Git。

## 11. 已执行测试【A】

最终 **105 项项目测试 + 5 项第三方适配测试全部通过**，包括包装/分析、UUID/恢复。`npm run validate`、`npm run typecheck`、旧预览与 Mock E2E 通过；覆盖转换/连续性、适配器错误、审批预算、去重、字幕、媒体读取和渲染。E2E 复跑未重复提交或改写成片；没有删测试或降低标准。独立 `npm ci` 安装 259 包、Python wheel 构建/安装也通过。

补充复现验收：只导出 Git 跟踪文件，在无运行缓存的临时目录连接独立 `npm ci --ignore-scripts` 安装的依赖，重新通过全部 105+5 测试、validate/typecheck 和完整 `npm run e2e`。新生成技术片的 SHA-256 与工作区成片一致，复跑保持原哈希与修改时间。详情见 [验收 JSON](verification/technical-e2e.json)。

## 12. 未实现与受限能力【B+C+D】

【B】视频 API/Piper 仅合同验收。【C】创作由 Codex/Skills 组织，转换器不自带编剧模型；ASR、语义审片、外部队列、对象存储、手机/Webhook 和永久服务未部署。【D】真实视频/声线须权限、报价与批准。Actions 已配置但未远端实测；Windows 整体未验收。

## 13. 尚需凭证与配置【D】

首选火山 Live 需要秘密管理注入 `ARK_API_KEY`，再确认模型开通/客户地区资格、有效报价、私有预算和具体请求审批；没有在仓库保存或读取展示密钥。BytePlus 若以后实现需独立账号与报价。Piper 不需 API Key，但需合法本地模型、配置和可执行程序。没有启用 ElevenLabs、AtlasCloud 或其他付费 TTS，因此当前无需它们的密钥。

## 14. 真实生成费用与来源【A：估算；D：执行】

[火山官方价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1)快照：1080p、无输入视频，2.5 为 77 元/百万输出 token，2.0 为 51 元。按 1080×1920、24 FPS 推算：

| 模型 | 5 秒 | 120 秒 | 10 集×120 秒 |
| --- | ---: | ---: | ---: |
| 2.5 | 18.71 元 | 449.06 元 | 4,490.64 元 |
| 2.0 | 12.39 元 | 297.43 元 | 2,974.32 元 |

仅单轮成功估算，未计短镜头额外时长、重拍/重试、TTS、工具、存储和带宽。含视频输入最低 token 表及 BytePlus 完整价格未知，阻止 Live。开通余额不是镜头价格；调用前重新核价和批准。

## 15. 云端执行与素材持久化【A+C】

【A】有界 worker、每集检查点/事件、SQLite UUID 身份、任务 ID、预算及哈希素材支持恢复；迁移须先恢复原账本与完整素材，再显式 `rebind-storage`，禁止用空账本重提收费任务。已实现本地/挂载卷存储接口。

UUID 只能证明账本身份，**不能证明备份足够新**。恢复旧快照可能缺少后来已收费任务；Live 恢复前须向服务商对账、补齐任务记录，不能仅凭 UUID 相同直接重提。

【C】Codex Cloud 有时限，不能无限后台轮询。外部队列/定时唤醒/对象存储后端仍是部署方案。手动技术 Actions 仅针对公开 Mock fixture，未远端验收，不持续运行 Live。GitHub 保存可公开代码、配置、剧本模板及白名单摘要；数据库、密钥、私人资料、大型媒体留受控持久卷。Git 忽略不等于自动备份。见 [云端恢复方案](cloud-runtime.md)。

## 16. GitHub 提交与 PR【A：已提交待审核】

独立分支 `codex/automated-production-system`，保持 main 稳定；代码、依赖锁、Skills 与中文文档进入 PR，排除密钥、私人素材及大型媒体。等待用户审核，不自行合并。

[本次升级 Pull Request #2](https://github.com/hzhsour/Short_Drama_Production/pull/2)。

## 17. 制作首集真实 AI 短剧的路径【A：准备工具；D：付费执行】

用 `init-series`、`init-episode` 建剧；Codex 完成圣经、人物与 EP001 剧本，确认创意/权利后运行 `validate`、`convert-script`、`plan` 和 Mock 样片，准备授权录音。按 [Live 流程](live-activation.md)配置私有账本、存储、报价、密钥和审批，先明确批准少量镜头，复核扣费/人物表现后扩大整集。命令和恢复见 [CLI](cli.md)。
