# 云端执行、状态恢复与素材持久化

Codex Cloud 在一次任务的执行时限内运行制作程序。关闭本地电脑后，已经启动的云端任务可以继续执行到任务结束；它不是永久后台服务，也不会在任务结束后自动轮询模型。本项目已经实现有界执行和本地状态恢复；跨任务唤醒、外部队列和对象存储服务仍需单独部署。

## 可重复安装与技术验收

需要 Node.js 20+（CI 使用 24）、Python 3.10+（CI 使用 3.12）、FFmpeg/FFprobe、本地 Chrome/Chromium 和中文字体。npm 依赖使用已提交的 `package-lock.json` 安装；Python 核心生产模块仅依赖标准库。设置 `CHROME_EXECUTABLE` 可以指定浏览器；`PYTHON_EXECUTABLE` 可以指定项目 npm 命令使用的 Python。渲染 CLI 还会将当前解释器的路径传给渲染子进程。

```bash
npm ci
npm run doctor
npm run check
npm run preview
npm run drama -- demo --render
```

`demo` 的输入固定为仓库中可以公开的 `examples/technical-demo/`，视频与声音均为本地占位素材。它不调用付费生成服务，不代表 Seedance 或真实中文配音已经验收。Chromium 需要执行环境允许本地浏览器进程；缺少浏览器、FFmpeg 或字体时应先修复环境，不能跳过相关验收后宣称渲染成功。

## 每次执行完成什么

`VideoEngine.run(storyboard, max_jobs=N)` 是一次有界推进。它对选中的镜头提交尚未提交的任务、查询已有任务，并在任务就绪时下载、解码检查、计算哈希及保存素材。`queued`/`running` 状态会持久化并返回，程序不在内存中永久等待；可安全重试的错误受 `max_retries` 限制。单次 HTTP 请求也有超时。`max_jobs` 限制本轮处理数量，不是永久 worker 数量或完成时间承诺。

同一个运行目录再次执行，会读取制作记录和视频任务数据库，复用已有 provider task ID、预算预留及通过哈希验证的素材。字幕、时间线和输出也有哈希记录，已验证的成片可以复用。输入剧本、角色、模式或片头尾参数改变时，生产流程要求新运行目录，防止旧素材与新审批混用。

首次视频提交前，管线将 SQLite 的持久 UUID 写入 `run.json`；独立 `generate` 入口将其写入 `engine-context.json`。恢复先只读核对 UUID，再允许创建引擎。数据库丢失、同一路径被空库替换或恢复了另一份账本时会阻断，不会自动新建数据库后重复提交。即使程序在模型接受任务后、`video-result.json` 落盘前中断，身份检查仍然有效。旧 Live 记录缺少 UUID 时需要人工核对迁移，不能自动视为安全恢复。

UUID 证明账本身份，不能证明备份最新。必须恢复包含最后一次提交意图/provider task ID 的完整最新账本；相同 UUID 的旧快照可能缺少已被服务商接受的任务。备份过旧或提交状态不明时，先到服务商对账再恢复，不能声称任意历史快照都能保证不重复收费。独立外部提交日志、远端版本核验和跨存储事务尚未实现。

默认技术样例记录位于：

| 路径 | 内容 |
| --- | --- |
| `runs/technical-demo/run.json` | 输入哈希、阶段任务、状态、输出与人工审片要求 |
| `runs/technical-demo/events.jsonl` | 每次推进的阶段事件 |
| `runs/technical-demo/engine/state/video-jobs.sqlite3` | 镜头请求、provider task ID、重试次数、预算预留、任务事件和租约 |
| `runs/technical-demo/video-plan.json`、`video-result.json` | 计划及本轮生成结果 |
| `runs/technical-demo/audio-result.json`、`timeline.json`、`subtitles.srt` | 音轨、含片头偏移的字幕与可追溯时间线 |
| `runs/technical-demo/quality.json` | 解码、规格、时长、音轨、安全区域及人工复核项 |

默认素材保存在运行目录下的 `engine/artifacts/video/`。`storage_root` 可以将视频素材保存到用户指定的本地目录或已挂载的持久卷；音频、最终 MP4、数据库与日志也必须纳入持久化范围，不能只保存视频素材。

## 可靠恢复所需的持久化

`runs/`、`storage/`、数据库和大型媒体被 Git 忽略。忽略文件不会自动备份文件，云端临时磁盘也不等于持久存储。关闭本地电脑不会替代云端数据备份。

已实现的 `LocalStorage` 提供不可覆盖写入、文件大小及 SHA-256 验证。`ArtifactStorage` 是可替换接口；S3、OSS 等远程后端尚未实现，也没有自动上传用户素材。可以先挂载受控的持久目录，把 `run_dir` 和 `storage_root` 放在该卷上。不要让多个机器通过普通同步盘并发写同一份 SQLite。

恢复时应同时保留：固定版本代码和依赖锁、原始剧本/角色/参考资料、`run.json`、事件日志、视频数据库、音频与视频素材、模型配置和有效审批记录。密钥通过工作机的秘密管理服务注入，不写入上述可提交文件。制作记录可能包含未公开台词、提示词、文件路径及参考素材信息，也不应自动提交到公开仓库。

当前引擎的参考图请求身份使用相对参考路径 `relative_path`、文件 SHA-256 和参考类型等语义字段；机器本地的绝对路径不参与该身份哈希。因此，在新参考根目录下保留相同的相对布局与文件内容，可以保留请求身份和对应审批的请求哈希。持久化请求和时间线仍可能含原机器的绝对路径，跨机器恢复需要显式重绑定，不能只复制一个数据库后直接使用空状态重新运行。

已经实现 `VideoEngine.rebind_storage()` 和离线 CLI：

```bash
npm run drama -- rebind-storage /mnt/restored/project-engine /mnt/restored/video --run-dir /mnt/restored/runs/EP001 --asset-root /mnt/restored/references
```

两个位置参数依次是已恢复的引擎目录 `ENGINE_ROOT`（其中应有 `state/video-jobs.sqlite3`）和已恢复的视频存储目录 `NEW_STORAGE`。`--run-dir` 指向已恢复的分集运行目录；它让命令同时核对原任务身份并更新该集的引擎、存储及参考根目录记录。`--asset-root` 指向新的参考资料根目录。省略 `--run-dir` 时只重绑定引擎素材，不迁移分集运行记录。

恢复按以下顺序执行：

1. 停止相关 worker，先备份原 SQLite、运行记录和素材；需要在线备份 SQLite 时，使用 backup API 生成一致快照。恢复操作之前，也保留一份恢复后的数据库副本。
2. 将原引擎数据库和完整运行记录恢复到目标目录，按原素材 `key` 的相对布局恢复视频；恢复参考资料、音频、成片和其他检查点。
3. 执行上述显式重绑定命令。它逐项核对已恢复视频的 `key`、文件大小和 SHA-256；使用 `--run-dir` 时还核对原 `job_key`、请求哈希与 provider task ID。缺少原账本、素材缺失、内容变化或任务身份不符时拒绝迁移。
4. 用相同输入恢复制作，后续命令中的 `--project-workspace`、`--storage-root`、`--asset-root` 必须与重绑定后的上下文一致。参考文件在运行时再次按相对路径和哈希验证；音频、字幕与时间线按有效检查点复用或重建。

重绑定是本地元数据操作，不复制或上传文件，不提交、轮询、下载或重新生成任何 provider 任务，也不要求为此配置 API Key。原 provider task ID、请求哈希和预算账本保留，不能通过改路径重新提交已收费任务。URI 对象存储、自动远程素材下载和外部存储账号接入仍未实现。

`succeeded` 但素材丢失或被修改的任务不会被静默视为有效；存在 provider task ID 时可以在正常恢复流程中尝试重新下载。`submission_unknown` 表示提交结果不确定，必须先在服务商处核对，不能重置状态后自动再次付费提交。

## 长任务的外部调度设计（尚未部署）

如果模型需要等待数分钟、数小时或超过 Codex 当前任务时限，应由外部 cron、队列消费者或另一次受控的 GitHub Actions 调用再次唤醒有界 worker。手机提交任务可以作为未来的入口；本项目尚未部署手机入口、Webhook、持续运行服务或计划任务。

建议的调度过程：

1. 持久队列保存 `run_id`、`episode_id`、`job_key`、输入版本、下次轮询时间和尝试次数；持久数据库保留请求哈希、provider task ID、预算预留和审批范围。
2. worker 领取有到期时间的租约，恢复匹配版本的代码及受控存储，执行一次有限数量的 `VideoEngine.run()`。
3. `running`/`submitted` 任务保存检查点、按服务商频率限制安排下一次唤醒，然后退出；不要用长期 `sleep` 占住一个云端任务。
4. 成功后核对素材哈希并推进音频、时间线、渲染和质检；永久失败或重试耗尽时进入人工处理队列。
5. Live 提交前重新核对密钥、官方接口、具体模型、审批有效期、请求哈希和预算。未批准、价格未知、地区不可用或提交结果不确定时停止付费提交。

现有 SQLite 租约用于同一状态库的本地协作，不构成已经部署的分布式队列。跨实例并发、长操作的租约续约、可靠通知、对象存储下载到本地 stage、调度平台身份验证和灾难恢复，需要在真正接入外部平台时实现并验收。仓库没有创建 cron、定时 Actions、队列资源或外部账号。

## GitHub Actions 的范围

`.github/workflows/technical-production.yml` 只提供手动 `workflow_dispatch` 技术验收：安装依赖，运行 `check`、旧预览和公开 fixture 的 Mock 端到端渲染。它没有定时触发、Live 参数、生产素材路径输入、密钥注入或自动提交权限。任务仅有 `contents: read`，运行上限 20 分钟。

工作流会检查结果仍对应公开 fixture 的输入哈希、Mock 模式和成功质检，然后只复制指定的测试成片、字幕和报告到上传目录。artifact 保留 7 天；它是短期验收产物，不是私人生产素材的长期存储方案。真实剧集的输入、媒体、凭证和任意 `runs/` 目录不在该工作流的上传范围。

该工作流状态为：**已配置，未远端实测**。本地代码与实际本地 Chromium/FFmpeg 渲染的通过结果不能替代 GitHub runner 的首次验收。首次手动执行后，需要检查 runner 的浏览器、字体、运行时间和 artifact，再记录远端结果。它也不会自动继续尚未完成的真实生成任务。
