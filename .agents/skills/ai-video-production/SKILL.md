---
name: ai-video-production
description: 为已批准的分镜准备模型无关的视频生成提示、镜头素材清单、连续性与审核记录；当用户要筹备或执行 AI 视频制作时使用。
---

# AI 视频制作

## 先明确执行边界

- 先核对用户是否明确批准了具体服务、账号、素材上传与计费操作。未明确授权时，只产出模型无关提示词、镜头清单和本地文件结构；不调用 API、不登录、不上传文件、不购买额度。
- 不把 API Key 写进仓库、提示词或日志。服务配置与剧情分镜分离；仅记录用户确认且可核实的提供商、模型和参数。
- 检查参考图、人物肖像、音乐和场景素材的使用权；不确定时标成待确认。

## 镜头准备与质检

1. 从结构化分镜读取镜头 ID、时长、角色基线、动作、画幅和声音要求。
2. 静帧提示与运动提示分开；每镜聚焦一个主动作和可描述的相机运动。固定角色描述遵循 `character-consistency`。
3. 先选关键镜头做低成本预览，再核对面部、手部、道具、物理运动、字幕安全区、闪烁和首尾帧衔接。
4. 将输出按镜头 ID 命名；随附提示版本、生成工具/模型（仅填写已确认信息）、来源、审核状态及问题。
5. 不合格素材返工或标记拒收，不覆盖原始输出；分镜变更需同步时间线。

## v0.2 视频引擎与命令

统一入口为仓库根目录的 `npm run drama -- <命令>`。先校验已有分镜，再规划、执行一轮任务并读取状态：

```bash
npm run drama -- validate --characters examples/technical-demo/characters.json --storyboard runs/technical-demo/storyboard.json
npm run drama -- plan runs/technical-demo/storyboard.json --run-dir runs/video-review --episodes 10
npm run drama -- generate runs/technical-demo/storyboard.json --run-dir runs/video-review --max-jobs 1
npm run drama -- status --run-dir runs/video-review
```

上述视频命令默认 `--mode mock --provider mock`，使用本地技术素材且不调用生成 API。`plan --episodes 10` 是按当前同一集清单投影十集成本，不代表已经逐集规划完成；价格未知时输出 `null`，不得编造费率。独立执行这些命令前先准备其输入分镜；完整示例可先用 `npm run demo` 建立。

`--max-jobs 1` 刻意只处理一个任务；尚有未完成镜头时 `generate` 返回退出码 2 与状态 JSON，后续用同一分镜、同一 `--run-dir` 继续执行，或去掉上限处理其余镜头。不要把有界暂停误判为已完成整集，也不要为清除该状态重新创建收费任务。

只读核对官方模型任务和报价快照可用 `plan ... --mode live --provider volcengine-seedance-2.5`；此处的 `live` 仅选择规划配置，`plan` 不提交请求、不上传参考素材，也不产生用户批准。正式能力与账号限制以 `config/providers.json` 和 `docs/integrations/seedance-api-audit.md` 为准，未验证占位项不得视为可用模型。

### Live 提交门控

- 默认所有官方模型 `live_enabled=false`。真实 `generate` / `run` 须同时具有已核实的精确模型、当前账号开通状态、环境注入的 `ARK_API_KEY`、有效实时价格、外部人工批准文件以及单镜头/单集/全剧预算。
- 批准通过 `--approval` 提供，预算通过 `--budgets` 提供；Live 必须指定整部剧共用的 `--project-workspace`，跨集使用同一 SQLite 账本，避免每集重置总预算。不得由代理自行签发批准、把文档价格快照改成实时核价，或在缺少明确用户授权时启用服务。
- 批准绑定精确请求哈希、模型、币种与有效期；价格配置变化会改变请求身份。每次真实提交前重新检查授权与价格期限。未知价格、超预算或权限不足均暂停，不以 Mock 验证替代真实服务验收。
- 重复执行同一请求复用账本和已校验素材；轮询/下载恢复保留原 provider task ID。`submitting` 中断或提交结果不明时进入 `submission_unknown`，先人工查服务端账单与任务，禁止删账本或换运行目录绕过保护重新收费。失败和重试次数持久化，达到上限后停止。
- 参考图必须能关联本地文件哈希；当前 Ark 适配不自动托管本地图片，公网参考 URL 也须先有素材授权。下载只接受已批准的 HTTPS CDN 边界并检查大小、时间、解码与规格，原文件不覆盖。

`generate` 运行一轮有界任务，未完成时返回状态并退出；不是永久后台服务。恢复时保留 `run.json`、SQLite、请求与素材元数据，继续用同一参数运行。外部存储目前通过本地/挂载路径和 `--storage-root` 接入，迁移先恢复账本，再按 `rebind-storage` 核对 key/SHA；没有自动上传 S3 的实现。详见 `docs/cloud-runtime.md`。

需要从结构化剧本连到成片时用 `run <剧本JSON> --characters <人物JSON> --run-dir <运行目录> --render`；未显式批准的任务保持 Mock。所有报告区分“本地技术测试”“假服务测试”“文档核实”“授权后真实生成”，最终画面的人物、表演和剧情仍需人工审片。
