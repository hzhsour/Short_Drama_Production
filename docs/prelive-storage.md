# Live 前的持久化与异地恢复验收

## 当前实际实现

项目将任务、provider task ID、请求哈希、预算预留和账本 UUID 写入 SQLite；音视频、字幕、时间线、制作检查点和事件日志写入本地目录。`LocalStorage` 校验素材 key、大小和 SHA-256。已经实现显式离线 `restore-run`，可将**已经复制或从一致快照恢复**的完整制作资料重绑定到不同目录。

这不等于已经完成生产备份。Git 忽略只防止资料进入仓库；云端临时盘不能保证跨任务保留；`ArtifactStorage` 接口不提供已经部署的 S3/OSS 备份。项目没有配置用户的持久卷、对象存储账号、自动备份、备份版本保留、异地复制或跨 Codex 任务自动唤醒。

## Live 制作前用户必须配置

| 条件 | 必须保存或确认的内容 |
| --- | --- |
| 受控持久目录 | `run_dir`、全部剧集共享 `project_workspace`、`storage_root`、参考图与源录音根目录；确认环境结束和重建后仍存在 |
| 完整备份范围 | 最新 SQLite、`run.json`、事件日志、全部音视频原件与产物、内外层音频 manifest、SRT、时间线、质检与计划/结果记录 |
| 一致性与新鲜度 | 先停止全部共享账本 worker；用 SQLite backup API 或等效一致快照，不在写入中只拷贝 `.sqlite3` 主文件；恢复最后一次提交意图及 provider task ID |
| 版本与恢复点 | 自行确定备份频率、版本保留、异地副本和允许丢失的数据范围；保留固定代码与依赖版本，并在启用 Live 前实际演练恢复 |
| 访问与密钥 | 目录权限、存储账号、加密和访问审计由用户配置；API Key 从秘密管理注入，不提交 Git，不写进素材和备份清单 |
| 并发边界 | 恢复时停止所有使用同一项目账本的 worker；普通同步盘不适合多机并发写同一 SQLite；本地租约不等于分布式队列 |

UUID 只能证明账本身份，不能证明快照最新。同 UUID 的旧快照仍可能缺失已经收费的提交。备份时间不明、`submission_unknown` 或服务商任务与本地记录矛盾时，先到服务商对账，不能清空账本或重提任务“试试看”。预算和审批继续由用户决定；恢复命令不创建付费授权。

## 显式离线重绑定

先自行恢复文件；目录必须已经存在，原参考资料的相对布局和文件内容必须保留。引擎目录中必须有原始 `state/video-jobs.sqlite3`。

```bash
npm run drama -- restore-run /mnt/restored/runs/EP001 /mnt/restored/shared-engine /mnt/restored/video --asset-root /mnt/restored/reference-media
```

如旧检查点无法唯一确定原运行根目录，可加 `--previous-run-root /old/machine/runs/EP001`。该参数必须与已有检查点一致，不能任意替换媒体路径。

该操作执行以下步骤：

1. 核对原账本 UUID、任务 key、请求哈希、provider task ID 和提交/查询/下载次数。
2. 按已明确的运行、引擎、视频和参考根目录映射路径；校验共享账本中全部剧集的视频以及当前集音轨、源音频、SRT、时间线和最终成片的已有 SHA-256。缺失、变化或越界时拒绝迁移。
3. 保存私有的 `.restore-plan.json` 迁移清单，再重绑定视频存储和当前制作的路径。同步音频 manifest、音轨校验表、时间线、质检记录、成片路径及依赖元数据的哈希；媒体字节、任务 ID、请求哈希和预算不变。
4. 保留历史事件，新增离线恢复事件。已经完成且通过哈希验证的成片可以继续复用，不重新渲染。未完成任务后续仍使用原 provider task ID。

该命令不复制、不上传、不调用 submit/poll/download、不自动重生成，也不确认备份最新。恢复前另留一份原备份。多个 JSON 与 SQLite 的更新不是一个跨文件事务；中断后按相同目标目录重跑，程序只接受文件仍等于已校验的原版本或目标版本，继续同一迁移。若其他 worker 在期间修改了数据则阻断，需人工核对。

`.restore-plan.json` 含原始制作元数据，应与运行目录一同保持私有。完成后不要把它提交公开仓库。只迁移视频的旧 `rebind-storage` 命令仍保留；完整迁移应使用 `restore-run`。

## 可复现的公开 Mock 验收

```bash
npm run e2e
node tools/python.mjs tools/verify_recovery.py --source-run runs/technical-demo --destination runs/recovery-acceptance
```

验收工具只接受仓库当前公开 fixture 的输入哈希和 Mock 视频/音频模式。它在本地创建一致账本快照及完整制作副本，先构造自包含的原目录，再恢复到另一组目录，并重命名原目录使旧绝对路径失效。随后通过实际管线与 FFmpeg 质检，检查任务 ID、次数、素材哈希、音频、时间线、账本 UUID 和成片复用。测试明确禁止 provider 调用以及重新渲染；这验证恢复能力，不部署生产备份服务。

新增单元测试另外覆盖音轨损坏、时间线被改、账本丢失、任务 ID 错误，以及跨文件迁移中断后继续。仅元数据测试中的输出占位字节不冒充可播放 MP4；实际媒体恢复由上述端到端工具完成。每次执行结果记录在验收目标的 `verification.json`，最终报告应引用本轮实际结果。
