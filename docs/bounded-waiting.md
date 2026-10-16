# 可选有界等待

默认仍是单轮推进。可为 `generate`、`run` 或公开 `demo` 选择有限等待，无需部署服务器：

```bash
npm run drama -- demo --run-dir runs/my-new-mock-test --wait-seconds 60 --max-polls 10 --poll-interval 2 --poll-backoff 1.5 --poll-max-interval 10 --render
```

| 参数 | 含义 |
| --- | --- |
| `--wait-seconds` | 等待推进总时限，默认 0（关闭）；开启时大于 0 且最多 3600 秒 |
| `--max-polls` | 整次等待状态请求上限，包括安全重试，默认 20，范围 1–1000 |
| `--poll-interval` | 首次退避秒数，默认 2 |
| `--poll-backoff` | 间隔增长倍率，默认 1.5，范围 1–10 |
| `--poll-max-interval` | 最大间隔，默认 30，最多 60 秒 |

等待时每轮推进一个未完成镜头并保存结果、次数和等待原因；所有新付费提交仍逐任务检查审批、报价及预算。`--max-jobs` 保留原单轮含义，**非零 `--max-jobs` 与有界等待不允许组合**，避免悄悄突破用户指定的镜头数。`--max-jobs 0` 仅创建/读取计划，不提交、查询或等待。

## 截止与恢复

达到总时限或请求数上限只表示本地停止等待，返回 `waiting_video`（CLI 退出码 2），不代表服务商任务失败。SQLite 和检查点保留 provider task ID；再次运行继续查询/下载，不重新提交原生成任务。普通 queued/running 查询会累计次数，但不消耗失败重试预算；因本地截止导致的安全超时同样不计失败。真实 POST 已发出而响应不明仍标记 `submission_unknown`，需先人工服务端对账。

网络连接/下载会尽量缩短到剩余等待时长；截止后不启动后续作业或请求。**这不是强制终止进程的硬墙钟超时**：正在进行的网络读取及本地解码仍受各自超时约束，可能在时限后返回。等待时限不包含随后 Remotion 渲染和后期所需时间，不能把它写成整次制作的最长耗时保证。

`run` 保存 `run.json` 中的 `video_wait` 检查点及事件，独立 `generate` 保存 `video-result.json` 和 `wait-events.jsonl`。等待参数可以在恢复时调整，创意/模式/请求哈希不能混用。

这是当前任务内的有界循环，不是永久后台服务。关闭当前任务后不会自行唤醒；跨 Codex 任务继续执行仍需另行部署调度及可靠存储。

## 公开 Mock 连续推进验收

```bash
python3 -m unittest discover -s tests -p 'test_waiting.py' -v
python3 tools/verify_async.py --run-dir runs/my-new-async-test
```

第二条命令需要新的运行目录、本地 Chromium/FFmpeg：先用 2 次查询停在等待状态，再使用原任务 ID 推进 queued → running → succeeded，下载本地占位镜头并实际剪辑导出。每镜头提交 1 次、查询 3 次、下载 1 次，不调用生成或 TTS API。
