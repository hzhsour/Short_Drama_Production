# Seedance 官方 API 核实与接入边界

核实日期：2026-10-16。只读取公开文档，没有获取密钥、充值、上传素材或调用生成接口。部分官方文档直接打开只返回 JavaScript 页面，本次同时核对官方页面的搜索索引正文；这属于文档核实，不是账户可用性或真实出片测试。下列 URL 固定到官方文档页面，价格和配额仍会变化。

## 结论与注册配置

当前官方已公布 **Seedance 2.5 开发者 API**；不能根据过往“尚未开放”的信息继续断言不存在，也不能使用第三方网站自定义模型 ID。[火山创建接口](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)、[BytePlus 创建接口](https://docs.byteplus.com/de/docs/modelark/create-video-generation-task-api)均已列明开放状态。

| 服务 | 官方版本 ID | 已核实服务区域 | 注册项 |
| --- | --- | --- | --- |
| 火山方舟 Doubao Seedance 2.5 | `doubao-seedance-2-5-260628` | `cn-beijing` | `volcengine-seedance-2.5` |
| 火山方舟 Doubao Seedance 2.0，备选 | `doubao-seedance-2-0-260128` | `cn-beijing` | `volcengine-seedance-2.0` |
| BytePlus Dreamina Seedance 2.5 | `dreamina-seedance-2-5-260628` | `ap-southeast-1` | `byteplus-seedance-2.5` |

ID 证据：[火山 2.5 教程](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh)、[2.0 教程](https://docs.volcengine.com/docs/ark/seedance-2-0?lang=en)、[BytePlus 模型清单](https://docs.byteplus.com/en/docs/modelark/model-list?redirect=1)。区域表示服务部署点，不表示所有国家的账号均可购买；支持客户国家、当前账号实名/企业资格及开通结果为 `unknown`。

`config/providers.json` 默认 `mock`。泛称 `seedance-2.5` 保留 `unverified` 占位，ID 和地址为空；已核实条目使用 `official_documentation_verified`，所有条目 `live_enabled=false`，避免把文档证据等同实测。API adapter 的实现及合同测试状态以代码和项目验收报告为准。

## 2.5 逐项核实

| 核实项 | 官方证据及实际边界 |
| --- | --- |
| 正式 API | 异步创建、查询并下载结果，使用 `/contents/generations/tasks`；不是网页自动化接口。[创建](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh) |
| 认证 | `Authorization: Bearer`，密钥通过 `ARK_API_KEY` 注入。[鉴权](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en) |
| 开通 | 火山公开条件列余额大于 200 元、专属节省计划或有余量资源包等途径；未替用户开通。[开通说明](https://docs.volcengine.com/docs/ark/seedance-2-0-model-resource-pack-rules?lang=zh) |
| 文生/图生 | 文本、首帧、首尾帧及多模态参考均列入正式能力；尚未真实验证生成效果。[模型清单](https://docs.volcengine.com/docs/ark/model-list?lang=zh) |
| 多参考 | 最大 30 图、10 视频、10 音频；参考视频与音频分别受总时长限制。[2.5 教程](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh) |
| 角色一致性 | 可指定参考人/物/场景及外观、声音；不是跨镜头身份绝对保证，也没有核实通用“锁脸开关”。应保留人物档案及人工验收。[官方提示词指南](https://docs.volcengine.com/docs/ark/seedance-2-5-prompt-guide?lang=zh) |
| 时长 | 常规生成 4–30 秒；编辑任务应跟随输入时长，不能统一强制 duration。[模型清单](https://docs.volcengine.com/docs/ark/model-list?lang=zh)、[通用教程](https://docs.volcengine.com/docs/ark/video-generation-tutorial?lang=en) |
| 延长/编辑 | 正式列有延长和编辑；仍需单独实现任务判定和输入约束。本文未声称项目已完整实现这两类请求。[2.5 教程](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh) |
| 联合音频 | 支持 `generate_audio`；有声结果为单声道，不保证对白时长完全匹配后期时间线。[创建参数](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh) |
| 9:16 | 文生/参考可指定；2.5 首帧、首尾帧、编辑、延长仅接受 `adaptive`，须准备竖屏输入。[通用教程](https://docs.volcengine.com/docs/ark/video-generation-tutorial?lang=en) |
| 分辨率/帧率 | 480p、720p、1080p；原生 24 FPS。最终项目输出 30 FPS 需要后期转换。[模型清单](https://docs.volcengine.com/docs/ark/model-list?lang=zh) |
| 编码/容器 | 正式列 MP4、MOV；MOV 列 H.264/yuv444p/PCM。MP4 具体 profile 和音频编码须对下载素材 ffprobe 验证，不能只看扩展名。[创建参数](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh) |
| 价格/计费 | 见下方价格快照；有输入视频时存在最低 token 用量，不能直接按生成秒数乘固定单价。[定价](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1) |
| 速率 | 企业最高 600 RPM/10 并发；个人最高 180 RPM/3 并发。公布上限受平台负载影响。[模型清单](https://docs.volcengine.com/docs/ark/model-list?lang=zh) |
| 查询配额 | 单任务查询最高 20 QPS、列表 1 QPS；应指数退避并持久化任务 ID。[2.5 限流说明](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=en) |
| 内容审核 | 不支持直接上传含真人人脸的参考图/视频。已授权肖像、信任模型产物、预置虚拟人像有另行规则；不得自行绕过。[肖像素材指南](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=en) |

BytePlus 提供独立账号、区域、价格和开通条件，创建文档列余额大于 USD 30 等途径；不能把火山密钥、人民币价格或国内账号资格直接迁移。[BytePlus 创建文档](https://docs.byteplus.com/de/docs/modelark/create-video-generation-task-api)

## 最小可核实的接口合同

火山数据面基础地址为 `https://ark.cn-beijing.volces.com/api/v3`，不是管控面的 `volcengineapi.com`。BytePlus 对应基础地址为 `https://ark.ap-southeast.bytepluses.com/api/v3`。[火山鉴权](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en)、[BytePlus 快速入门](https://docs.byteplus.com/es/docs/modelark/quick-start)

创建 `POST /contents/generations/tasks` 使用 `model`、`content` 和受模型约束的输出参数；响应 `id` 应立即保存。查询 `GET /contents/generations/tasks/{id}` 读取 `status`、`error`、`content.video_url` 和 `usage.completion_tokens`。排队、运行、成功、失败、取消和过期都需要处理；网络中断不能直接等同服务端没有创建任务。[创建](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)、[查询](https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh)

`duration` 为整数秒。少于 4 秒或包含小数的分镜不能原样提交，须明确向上取整并至少生成 4 秒、据生成时长计预算，再在后期裁切。`duration=-1` 为自动选择，可能影响预算；当前不应自动用于常规生产。查询返回的整数时长可能向下取整，真实素材长度须以 ffprobe 为准。[时长参数](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)

多参考图的内容项为 `{"type":"image_url","image_url":{"url":"https://..."},"role":"reference_image"}`；首尾帧分别用 `first_frame` 和 `last_frame`，不可混淆。2.5 的 `1080p` 与 `9:16` 对应 1080×1920，但首尾帧路径应使用竖屏参考图加 `adaptive`。[参考角色参数](https://docs.volcengine.com/docs/ark/seedance-2-5-prompt-guide?lang=en)、[输出像素表](https://docs.volcengine.com/docs/ark/video-generation-tutorial?lang=en)

查询记录保留 7 天，结果链接 24 小时有效，2.5 下载次数最高 100；恢复系统须及时下载、校验并记录自己的存储位置，远端 URL 不能作为永久素材库。[查询及保留规则](https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh)

## 人民币价格快照与预算边界

以下为 2026-10-16 核实的火山方舟在线推理刊例价，单位 **元/百万输出 token**，不是元/秒。它不包含 TTS、存储、带宽、工具调用或人工费用。BytePlus 按量价格未完整核实，注册项保持 `unknown`，不由人民币价格换算。

| 模型 | 分辨率 | 无输入视频 | 有输入视频 |
| --- | --- | ---: | ---: |
| 2.5 | 480p/720p | 70 | 42 |
| 2.5 | 1080p | 77 | 46 |
| 2.0 | 480p/720p | 46 | 28 |
| 2.0 | 1080p | 51 | 31 |

官方给出 token 近似公式 `(输入视频秒数 + 输出秒数) × 输出宽 × 输出高 × 输出帧率 / 1024`，实际以 `usage.completion_tokens` 与账单为准。有输入视频须再应用官方最低用量表；本次未导入完整最低表，预算器应将此类费用视为未知并阻止 Live。Draft 和正式任务分别计费，重试与候选重拍也需另计。[官方定价及估算规则](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1)

据该公式推算，**无输入视频、常规生成、1080×1920、24 FPS** 时，2.5 每 5 秒约 18.71 元；120 秒合计约 449.06 元、10 集约 4,490.64 元。2.0 对应约 12.39、297.43、2,974.32 元。这是单轮全部成功、不额外生成和不额外加长镜头的纸面下限示例，不是生产报价。2.0 fast/mini 曾有截至 2026-10-07 的活动价格，当前日期已过，未把旧折扣纳入预算。

开通余额或资源包购买金额不是单镜头成本。价格快照不应自动批准调用：真实生产前应重新核价，以具体任务清单和可承受的重试/重拍余量形成批准预算。

## 当前可用与待办

- **已核实文档**：2.5 官方版本、异步接口、主要参数、2.0 备选、火山价格快照与保存时限。
- **本次未执行**：付费请求、账户开通、密钥校验、结果素材上传/下载及真实画面、音频和一致性验收。
- **尚未知**：当前账户客户地区资格、实名/企业具体要求、可用额度、账户实际配额、BytePlus 全量按量价格、含参考视频的全部最低 token 档位。
- **Live 启用前**：选择具体服务区域和版本，按密钥管理方案注入凭证，确认素材授权与服务审核规则，补齐报价，取得用户对该服务、任务、预算的明确批准，再执行小样并记录费用与质量。文档注册状态不能跳过这些条件。
