# 原声、配音与静音模式

剧本／分镜顶层使用 `sound_mode`，整集保持同一模式。Live 必须显式填写；旧 Mock 输入缺省兼容为 `dub`，时间线会记录兼容警告。没有按镜头混用模式的隐藏规则。

| 值 | Ark `generate_audio` | 源视频播放 | 外部对白、BGM、SFX | 字幕 |
|---|---|---|---|---|
| `model` | `true` | 保留原音轨 | 不生成、不播放 | 保留 |
| `dub` | `false` | 明确静音 | 使用本地录音／已配置离线配音；Mock 使用测试音 | 保留 |
| `silent` | `false` | 明确静音 | 不生成、不播放 | 保留 |

最终 MP4 在 `silent` 模式可保留数字静音 AAC，便于交付规格一致。`model` 模式请求生成音轨，不代表服务商一定正确生成中文台词、口型或音效；这些仍需真实小样和人工审听。

## 一致性检查

- `script_to_storyboard` 保留模式；生成请求哈希包括模式及 `generate_audio`，切换模式不能误用旧任务。
- 视频产物记录 `sound_mode`；时间线为每镜保存 `sound_mode` 和 FFprobe 实测的 `has_source_audio`。模型原声模式必须实际有音轨，不能静默退回无声。
- `build_audio` 在 `model`、`silent` 模式仅生成字幕，不读取外部录音，也不调用已配置的离线 TTS；其清单 `notice` 明确说明处理方式。
- 非 `dub` 时间线如果出现外部音轨，直接拒绝，避免原声和配音同时播放。素材模式、音频清单模式或整集模式冲突也拒绝。
- Remotion 仅在 `model` 模式取消源视频 `muted`。渲染前再次检查哈希、时长和实际源音轨，防止手工编辑 JSON 隐藏问题。

如需改变模式，请先修改结构化剧本并创建新运行目录。真实生成仍须按新的请求哈希单独批准；程序不会自行批准。

## 本地专项验收

```bash
python3 -m unittest discover -s tests -p 'test_sound_modes.py' -v
python3 tools/verify_sound_modes.py --run-dir runs/prelive-audio
```

第二条命令要求空目录和现有 Chromium、Remotion、FFmpeg／FFprobe，实际渲染三个小型技术片，不访问生成或 TTS API：

1. FFmpeg 自行生成带 440 Hz AAC 的 1 秒色卡视频，以及 880 Hz PCM 外部配音测试音。
2. 三种模式分别经过音频清单、时间线、Remotion、FFmpeg 交付整理与质检。
3. 标准库 FFT 检查 `model` 仅保留 440 Hz、`dub` 仅保留 880 Hz，另一频带 RMS 不超过目标的 1%；`silent` RMS 小于 `0.00001`。
4. 每种模式保存素材哈希、音轨元数据、输出哈希、频率分析和质检结果到 `runs/prelive-audio/verification.json`。

技术测试音验证播放与混音逻辑，不验证真实对白质量。上述目录被 Git 忽略；这不构成备份。
