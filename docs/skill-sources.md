# Skills 来源、版本与安装范围

审查日期：2026-10-16（用户所在 Australia/Sydney 日期）。所有下列仓库均通过保留环境 HTTPS 代理及 TLS 校验的实际 Git clone 验证，固定的是本次取得的默认分支提交。没有执行远程安装脚本，没有请求付费服务，也没有上传制作素材。完整源码审查与工具边界见 [第三方审查](integrations/third-party-audit.md)。

## 已有项目 Skills

保留原有六个项目原创 Skills：`chinese-short-drama-script`、`character-consistency`、`storyboard-breakdown`、`ai-video-production`、`remotion-production`、`ffmpeg-postproduction`。原始初始化版本来自本仓库 PR #1；本轮随实际引擎、数据格式和 CLI 更新它们。它们是项目操作规范，不能声称是第三方官方 Skill，也不授予付费操作权限。

## 七个指定第三方仓库

| 来源 | 固定完整提交 | 最近提交时间（原时区） | 许可 | 安装与用途 |
| --- | --- | --- | --- | --- |
| [ZenStory](https://github.com/zenstory-ai/drama-skills) | `dafe80ee390ec8be5a7ec8dd156a84d511f8e7dd` | 2026-10-15T02:53:13-07:00 | MIT | 不安装整体套件；五 Markdown 权威源和本项目 JSON 权威源冲突，独立状态及付费 adapters 重叠；参考创作/连续性设计 |
| [Dramake](https://github.com/xixihhhh/ai-short-drama-skill) | `38345d39b27eb877978422bff28b5057e783164f` | 2026-08-30T06:12:24+08:00 | MIT，Skill 0.6.0 | 不安装；CSV/状态链与现有系统重复，脚本不随 Skill 子目录一起发布；参考成本及恢复设计 |
| [short-drama](https://github.com/0xsline/short-drama) | `8979a428c31a865421d661bdb606e24314b683a0` | 2026-04-18T02:26:39+08:00 | MIT | 不安装；SKILL 缺 YAML name/description，50–100 集等固定规则不适配当前可配置系统 |
| [create-storyboard](https://github.com/TateZhouSiu/create-storyboard-skill) | `4b8662e2fee51b37488c77952bbfa302bfeaf36c` | 2026-05-29T16:11:25+08:00 | MIT | **已安装安全适配版**到 `.agents/skills/create-storyboard/`；补充导演分镜、交接与剪辑边界文档，Python 标准库离线运行 |
| [Remotion 官方 Skills](https://github.com/remotion-dev/skills) | `1441a11e95db35443bd76bb318386c0d3ca00053` | 2026-10-16T10:09:16+02:00 | 此固定仓库未提供 LICENSE，package 无 license 字段 | **未复制、未安装**。版本 4.0.536，保留官方入口与固定版本记录；继续用本项目原创 Remotion Skill 引用官方文档 |
| [screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | `51115f18d160aa8b2ac5813e4432b6f0b425358f` | 2026-10-02T21:34:42-04:00 | 原创部分 MIT；NOTICE 排除书籍/译本引文 | 不复制整套；26 个 Skills 有标准格式，但部分 reference 引文不由 MIT 授权，长剧理论与项目剧本流程重叠，按来源阅读 |
| [character-consistency](https://github.com/divolleggett/character-consistency-skill) | `f77c2734afbda6f2cac539ff408f8682d5061b59` | 2026-08-03T16:25:40+08:00 | MIT | 不安装；与现有同名冲突，唯一脚本直连 AtlasCloud 两次收费调用，缺少项目预算/幂等/审批控制 |

## 已安装 create-storyboard 的变更和复核

原许可证、版权和归属保存在 [LICENSE](../.agents/skills/create-storyboard/LICENSE)、[UPSTREAM.md](../.agents/skills/create-storyboard/UPSTREAM.md) 与 [upstream.json](../.agents/skills/create-storyboard/upstream.json)。`upstream.json` 同时记录上游与安装文件的 SHA-256，便于复核修改。

修复 slug 路径穿越、已存在目录混合写入和覆盖风险；拒绝符号链接包目录，移除 `--force`，以独占创建写入文件。项目 Skill 明确沿用中文、现有 JSON schema/ID、9:16 画幅、原始素材保护和费用门控，不切换当前代理模型。模板中的供应商及 15 秒假设不等于已核实 API 能力。

已实际运行五个离线安全测试，覆盖31份骨架创建、画幅、路径穿越、禁止覆盖和符号链接。该 Skill 不含分镜板图像渲染器，不把 Markdown 模板创建当成图像、剧情视频或 AI 配音交付。

```bash
python3 .agents/skills/create-storyboard/scripts/create_storyboard_package.py ep001-director \
  --root production/episodes/EP001 --title "第一集导演设计" --duration "120s" --aspect "9:16"
python3 -m unittest discover -s .agents/skills/create-storyboard/scripts -p 'test_*.py' -v
```

## 官方 Remotion Skills 的安装记录

官方文档的安装入口为 `npx skills add remotion-dev/skills`（[说明](https://www.remotion.dev/docs/ai/skills)）。该命令会解析可变版本的外部安装器与上游默认分支，本次没有执行。固定提交的源码可以只读 clone 审查：

```bash
git clone https://github.com/remotion-dev/skills /tmp/remotion-skills-review
git -C /tmp/remotion-skills-review checkout --detach 1441a11e95db35443bd76bb318386c0d3ca00053
```

此提交及所取历史没有 LICENSE 文件，`package.json` 也没有 license 字段，不能把 GitHub 公开访问或 README 的安装命令视为明确的源码再分发许可。获得明确许可后，再审查并复制需要的 Skill 与其相对引用文件，记录许可证；不要直接跟随 main 自动更新。本条只说明第三方 Skill 文本的再分发状态，Remotion 软件包本身的使用条款应查阅 [Remotion 许可说明](https://www.remotion.dev/license)。

## 视频工具

| 工具 | 固定源码提交 / 版本 | 许可 | 本次边界 |
| --- | --- | --- | --- |
| [HyperFrames](https://github.com/heygen-com/hyperframes) | `4e6fcdb3a9f310a9c483622d6a4ca5354a63fb22` / CLI 0.8.164 | Apache-2.0，2026 HeyGen | 已隔离安装固定 CLI，与本地 GSAP 生成独立片头；1080×1920/30 FPS 实际 check/render 通过。没有安装其宽泛路由 Skill，不替换 Remotion |
| [video-use](https://github.com/browser-use/video-use) | `43cfc566833548093455c9d4a46bd69913b7e552` / 0.1.0 | MIT，2026 Browser Use | 审查实际 helper；不装默认 ElevenLabs 转录/EDL 剪辑流，本项目使用本地素材分析和自己的时间线 |

上游版本、费用、API 权限和素材政策会变化。后续升级必须先审查 SHA 与许可，运行本地测试，并通过项目 Live 授权和预算流程；Skill 安装不会自动授权计费或上传素材。

本轮 HyperFrames 的真实安装、浏览器权限限制、输出 SHA 和检查记录见 [独立视觉包装](integrations/visual-packaging.md) 与 [verification.json](../integrations/hyperframes/verification.json)。本地配音候选 Piper 的引擎及逐声线许可核实见 [音频工具](integrations/audio-tools.md)。
