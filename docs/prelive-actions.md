# 真实出片前：GitHub Actions 专项检查

检查日期：2026-10-17（澳大利亚悉尼）。本文件记录工作流检查及本轮小范围修正，不代表已触发或通过远端工作流。

## 实际观察

- GitHub 仓库 API 返回 `private: false`、`visibility: public`、默认分支 `main`。当前连接可读取仓库，仓库权限字段包含 `push: true`。这不能单独证明当前工具拥有 Actions 调度权限。
- `main` 中存在 `.github/workflows/technical-production.yml`；本次读取的文件与工作区原工作流一致。
- 查询仓库 Actions runs 时，返回 `total_count: 0`。截至此次查询，没有可报告为远端通过的运行。
- 本次没有 dispatch、rerun、修改 Actions 账户设置或读取账单、密钥。

观察来源：[仓库 API](https://api.github.com/repos/hzhsour/Short_Drama_Production)、[运行记录 API](https://api.github.com/repos/hzhsour/Short_Drama_Production/actions/runs?per_page=5)、[main 工作流源码](https://github.com/hzhsour/Short_Drama_Production/blob/main/.github/workflows/technical-production.yml)。运行数是检查时的快照，随后可能变化。

## 原工作流审查

| 检查项 | 观察 |
|---|---|
| 触发 | 只有 `workflow_dispatch`，没有定时、push 或 PR 自动运行 |
| Runner | 标准 `ubuntu-latest`，不是 larger runner；总时限 20 分钟 |
| 权限 | `contents: read`；没有显式注入 secrets，没有 Live 或用户素材输入 |
| 依赖 | 固定锁文件 `npm ci`；apt 安装 FFmpeg/CJK 字体；选择 runner 已有浏览器；没有安装额外 Skills、TTS 声线或调用生成服务的步骤 |
| 执行内容 | `check`、原有 `preview`、默认 `demo --render`；默认 demo 使用公开 EP900 fixture 和本地 Mock provider/音频 |
| 素材上传 | 仅固定 fixture 成片、原有技术预览、运行/质量/时间线 JSON 与 SRT；不打包整个工作区、生成素材目录或 SQLite 账本 |
| 上传前门禁 | 校验 EP900/technical_test、Mock 模式、公开输入哈希、成片目录与哈希、质检通过 |
| 存储 | 原工作流启用 npm cache，并上传保留 7 天的 artifact |

费用结论：GitHub 官方文档确认，公开仓库的标准 GitHub-hosted runner 执行分钟免费；同时当前文档把 artifact 存储列为与 Packages 共享的额度，把 cache 列为独立额度，并说明超额可能收费。因此不能只凭仓库公开就承诺带缓存和 artifact 的原工作流绝不新增费用。此次没有检查用户账户额度，也没有调整其预算。[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## 本轮工作流修改与执行决定

- 将单次 `demo --render` 改为 `npm run e2e`，使远端执行公开 Mock 成片及已有的恢复幂等验证。
- 上传白名单增加 `script.sound_mode == record.sound_mode == timeline.sound_mode == "dub"` 断言，防止本轮音频模式修正后上传不符合公开测试约定的结果。
- 保留原有标准 runner、只读权限、npm cache 和保留 7 天的公开 artifact；**没有实现可选上传开关**。成功运行现有工作流会执行公开 fixture artifact 上传。
- 本轮不 dispatch：无法确认额外存储费用，且当前工具的 Actions 调度权限尚未验证。本轮没有远端通过结果，也没有修改用户预算或付费设置。

## 手动执行步骤

以下命令是步骤说明，本次未执行。账户所有者须先核实 npm cache、artifact/Packages 存储额度和收费条件，再确认拟运行分支的完整差异、公开 fixture 及 Actions 权限。不要添加生产密钥或私人素材。

1. 打开仓库 **Actions → Public technical production fixture → Run workflow**。
2. 在分支列表中选择 `codex/prelive-acceptance`，测试本轮修正；本轮 PR 合并后才可选择 `main` 来验证这些修改。
3. 确认本次会启用 npm cache 并上传保留 7 天的公开 fixture artifact；现有工作流没有关闭上传的输入选项。
4. 点击 **Run workflow**，打开产生的 run，逐项检查测试、旧预览、公开 Mock 完整链路和恢复验证的结果。仅在该 run 实际 `success` 后报告远端通过；记录 run URL、commit SHA 和执行时间。

CLI 等价入口：

```bash
gh workflow run technical-production.yml \
  --repo hzhsour/Short_Drama_Production \
  --ref codex/prelive-acceptance
gh run list --repo hzhsour/Short_Drama_Production \
  --workflow technical-production.yml --limit 5
gh run watch <RUN_ID> --repo hzhsour/Short_Drama_Production --exit-status
```

GitHub 要求调度者具有写权限，且 `workflow_dispatch` 文件已存在默认分支；可以选择其他分支作为实际运行 ref。当前 main 已有该文件。若工具提示 Actions 权限不足，不能把仓库写权限当作调度成功。[官方手动执行说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

## 部署边界

- 工作流不是存储备份方案，也不是跨 Codex 任务的自动唤醒服务。它没有部署 Live 任务调度、持久卷或对象存储。
