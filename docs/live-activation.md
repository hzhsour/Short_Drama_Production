# 第一次真实制作：开通、创意和费用审批

本次没有调用任何真实生成/TTS API，没有配置 API Key，也没有开通任何付费服务。仓库模型目录的 Live 全部关闭。火山 2.5/2.0 适配器已经编写，但只通过模拟 HTTP 合约测试；BytePlus 和泛称 Seedance 2.5 仍是明确的不可执行占位。

## 先完成可审阅的创意

执行前还必须完成 [专项验收中的 Live 配置清单](prelive-acceptance.md)、选择明确的 [sound_mode](audio-modes.md)，并配置 [完整持久化条件](prelive-storage.md)。费用估算、预留、服务商用量和最终账单是不同概念，见 [用量对账规则](usage-accounting.md)。

1. 用 Skills 制作系列圣经、角色档案、EP001 大纲及完整剧本，确认题材、对白、节奏和版权。
2. 保存结构化剧本和人物 JSON，通过 `validate` 和连续性检查，生成分镜。为角色准备授权的多视角参考图。
3. 运行本地 `plan` 和 Mock 样片，检查每镜时长及 24 FPS 模型输出与 30 FPS 后期时间线的对应。
4. 让用户审核具体剧本、人物、参考素材、服务商、模型、镜头任务、价格、重试及预算上限。

当前适配器不自动上传本地图像；图像参考必须使用事先授权、服务商可访问的 URL。本地参考文件仍用于内容哈希。含真人人脸时需另行核实官方肖像方案与授权，不能默认上传。

## 开通条件

- 确认火山方舟账号身份验证、计费开通、目标模型权限、地区资格及账号实际配额。`cn-beijing` 是服务部署地区，不能据此承诺任意国家用户均可开通。
- 在私有运行目录复制 `config/providers.json`，核实官方报价后，针对选定 provider 设置 `live_enabled=true`、`activation_verified_for_this_account=true`。
- 报价设置 `pricing.status=verified_live_quote`，保留准确币种、费率、官方来源，增加未过期的 ISO 8601 `valid_until`。任何价格配置变化都要求重新计算并批准请求哈希。
- 由运行环境的秘密管理机制注入 `ARK_API_KEY`，不要写进仓库、命令行参数、日志、提示词或审批文件。本项目不读取或展示密钥值。
- 将 `config/budgets.example.json` 复制至私有目录，设置 `per_task`、`per_episode` 和 `project` 的实际上限。全部 Live 剧集使用同一项目账本。

## 明确批准的范围

`config/approval.pending.example.json` 是**未批准**模板，不能直接执行 Live。用户明确批准后，由受控流程在私有存储保存审批文件，包含：

- `approved: true`，可追溯的 `approval_id`、准确 `provider`、`model_id`、币种及 `expires_at`。
- `request_hashes` 中列出本次批准的全部完整请求哈希，来自同一报价/创意/参考图版本的计划。
- `limits` 设置单任务、每集、整部剧上限；执行时取配置与批准上限中更严格的值。
- 管线还核对 `creative.approved=true`、`creative.script_sha256` 和 `creative.characters_sha256`，绑定用户确认的创意版本。

工具不会替用户创建批准、默认设置预算或续期。每次新增付费提交前重新核对有效期。已有 provider task ID 可继续查询/下载；审批过期不能重提任务。未知提交保留预算并暂停，需先向服务商核对。

## 批准后的调用示例

以下只是将来审批完备后的命令形状，本次未执行：

```bash
npm run drama -- run /private/EP001/script.json --characters /private/characters.json --run-dir /private/runs/EP001 --mode live --provider volcengine-seedance-2.5 --project-workspace /private/project-engine --storage-root /private/video-store --asset-root /private/references --catalog /private/providers.json --budgets /private/budgets.json --approval /private/approval.json --audio-mode local --render
```

先批准少量镜头做 Live 验收，检查结果、真实扣费、时长、画质及角色一致性，再扩展到整集。配音可以先录制授权本地对白；真实 Piper 中文声音须另行安装、审查权重许可并做实际推理验收。付费 TTS 尚无已启用适配器。

## 价格范围

截至 2026-10-16 的[火山官方价格文档](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1)，2.5 的 1080p 无输入视频生成快照为 77 元/百万输出 token；2.0 为 51 元。估算公式、5 秒/2 分钟/10 集示例及限制见 [官方接口审查](integrations/seedance-api-audit.md)。此为文档估算，不是账号报价，不包括短镜头最少 4 秒产生的额外时长、失败重试、语音、存储和带宽。输入视频价格的最低 token 规则及 BytePlus 实际价格未完整核实，相关 Live 估算应阻止执行。
