# 第三方来源与本地修改

- 来源：https://github.com/TateZhouSiu/create-storyboard-skill
- 上游路径：`skills/create-storyboard/`
- 固定提交：`4b8662e2fee51b37488c77952bbfa302bfeaf36c`
- 最近提交时间：2026-05-29T16:11:25+08:00。
- 审查与安装日期：2026-10-16。
- 许可证：MIT；原版权归 Tate Zhou，完整许可保存在 [LICENSE](LICENSE)。
- 安装形态：项目级源码副本，没有运行上游安装器，无 npm/pip 依赖，无网络调用。

本地修改：`SKILL.md` 增加项目规则、中文竖屏默认、JSON 交付优先、费用门控和未验证供应商限制说明；移除切换代理模型的指示与全局安装路径。`scripts/create_storyboard_package.py` 验证 slug、拒绝符号链接包目录和已存在的输出，采用独占创建，不提供 `--force`，默认画幅为 9:16，并给模板标明待填写状态。`agents/openai.yaml` 使用中文界面描述。增加离线安全测试；各参考文档增加本地适配声明。

本 Skill 只生成 31 份待填写 Markdown 文档及目录，不生成分镜图、关键帧、剧情视频、配音或正式 Storyboard JSON。上游供应商名称、时长上限及模型推荐不等于当前官方 API 事实。参考文档中的相关内容应由项目规则和已核实的适配器能力覆盖。

安全验证：

```bash
python3 -m unittest discover -s .agents/skills/create-storyboard/scripts -p 'test_*.py' -v
```

升级时先审查新 SHA、许可证和文件差异，再重新应用安全修改并测试；不得自动跟随 `main` 或执行远程安装脚本。
