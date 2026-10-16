# 本地配音工具核实与接入边界

核查日：2026-10-16（Australia/Sydney 日期）。本轮只读取官方文档、发行源码和模型说明，没有下载声音权重、安装 Piper、调用 TTS 服务或付费 API。Piper 的本地适配接口与本项目 Mock/录音导入流程分开记录，假 CLI 测试不能写成真实中文 TTS 已出声。

## 选择与能力状态

本项目采用可替换 Audio Adapter：默认 Mock 音调验证对白 ID、时间轴、字幕和混音；可导入已有授权录音，经本地 FFmpeg 做规范化；另提供可选 Piper 本地 CLI 接口，只有工具、模型、相邻配置与声线权利记录齐备后运行。不同角色的真实声音由本地 `voice_models` 和可选 `speaker_ids` 映射决定，`profile.pitch_hz` 只控制 Mock 音调，没有实现 Piper 的真实基频控制。

- **已实现并有本地实测：** 对白与镜头 ID 绑定、导入录音的 FFmpeg 处理、WAV 时长检查、SRT 时间码与 Remotion 音轨交接；具体项目测试结果见验收报告。
- **已实现但仅假 CLI / Mock 测试：** Piper 进程参数、stdin 输入、输出文件检查、模型配置预检与错误处理。没有实际 Piper 声音模型推理结果。
- **待配置/核权：** 实际 Piper 软件包、中文声音 `.onnx`/`.onnx.json`、每个角色的声线选择及许可证记录、真人听审。
- **暂不启用：** Piper pinyin/g2pW 隐式下载路线、未经授权的云 TTS、声线克隆或 ElevenLabs API。

## Piper 官方安装与版本

官方实现为 [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)，当前 main 核查提交 `40ecf92760e0e13a3f9916497d0a1ad5b8075eee`，提交时间 `2026-10-15T06:59:18-05:00`。为复现建议依据正式 tag `v1.8.0`，提交 `639388b6317fc4731e91d53da42aea68fd4166ff`，提交时间 `2026-09-04T11:40:50-05:00`。下列参数、依赖和代码行为均核对该 tag。

官方 [README](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/README.md) 与 [CLI 文档](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/docs/CLI.md) 给出 `pip install piper-tts`。后续安装时应使用独立虚拟环境，固定实际可取得的发行包及依赖哈希；若索引提供相应版本，可按 `python3 -m pip install 'piper-tts==1.8.0'` 固定。此命令本次没有执行，PyPI 页面返回 Client Challenge，不能据 HTTP 200 声称已验证 wheel 可用或跨平台安装成功。

[setup.py](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/setup.py) 声明 Python >=3.9、`onnxruntime>=1,<2`、`pathvalidate>=3,<4`；包内包含 espeak-ng bridge/数据。源码构建还需 CMake/scikit-build 等本机工具，不假定所有平台都有可用 wheel。CPU CLI 不要求开启 HTTP 服务、训练依赖或 GPU；普通 `espeak` 模型也不需要仅因语言是中文就安装 `[zh]`。

当前实现的引擎许可是 **GPL-3.0-or-later**，见 [COPYING](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/COPYING) 和 setup.py；不能沿用旧 rhasspy/piper 的 MIT 描述。本项目通过独立本地进程适配，没有复制 Piper 实现到仓库。若以后重新分发引擎、容器或声音包，需保留各自许可证、对应源码/归属要求及模型权利记录；不能从引擎许可推出声线许可。

## 精确 CLI 与离线条件

官方 v1.8.0 [真实 parser](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/src/piper/__main__.py) 接受：

| 用途 | 参数与限制 |
| --- | --- |
| 模型路径 | `-m` / `--model` |
| 输出 WAV | `-f` / `--output-file` / `--output_file` 完全等价 |
| 输入文本文件 | `-i` / `--input-file` / `--input_file`；也可逐行 stdin |
| 说话人整数 | `-s` / `--speaker`，没有 `--speaker-id` |
| 语速长度比例 | `--length-scale` / `--length_scale`；不是基频控制 |
| 句间静音 | `--sentence-silence` / `--sentence_silence` |
| 本地目录检索 | `--data-dir` / `--data_dir`；不等于自动下载许可 |

调用形状为 `python3 -m piper --model /absolute/voice.onnx --output-file /new/output.wav --speaker 0`，对白通过 UTF-8 stdin 输入。包装器使用 argv 列表，严格白名单参数，指定绝对路径和新输出；不透传任意 flags。上游采用 `parse_known_args`，未知参数可能被当作待说文本；未指定输出时可能播放音频或写 `output.wav`，已有 WAV 会被 `wb` 覆盖，因此必须由项目包装器隔离新文件。

每个声音需要模型和同版本配置两件文件，例如 `voice.onnx` 与 `voice.onnx.json`。v1.8.0 与本次 main 虽解析 `--config`，却没有把它传给 `PiperVoice.load`，不能依赖它指定另一个配置；接口要求模型旁的同名 JSON。Python API 可显式传 `config_path=`，这不是本次 CLI 适配所采用的调用方式。

[配置源码](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/src/piper/config.py) 对缺省 `phoneme_type` 使用 `espeak`。初期只开放该类型以及经审查的中文 `espeak.voice`（如 `cmn`）；多说话人映射必须落在模型实际 `num_speakers`/`speaker_id_map` 有效范围内。单说话人模型始终只有一个声音，不可用多个任意 speaker ID 宣称已生成多角色独立声线。

`phoneme_type=pinyin` 的中文路线需要额外 g2pW/transformers 等依赖。[phonemize_chinese.py](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/src/piper/phonemize_chinese.py) 会在资源缺失时联网下载并解包 g2pW；[g2pw_onnx.py](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/src/piper/g2pw_onnx.py) 还可能下载 tokenizer，且会执行辅助资源 `config.py`。本项目暂时拒绝该类型和未知类型，附加 HF/Transformers 离线变量；仅设置离线变量不足以阻止上游自己的 urllib 下载，程序预检仍是必要条件。`python3 -m piper.download_voices` 也不是离线探测命令，即便仅列声音会联网，不纳入测试或 doctor。

## 官方中文声音与各自许可

官方 [VOICES 文档](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/docs/VOICES.md) 指向 [rhasspy/piper-voices 中文目录](https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN)，并要求逐个检查 `MODEL_CARD`。执行器直接访问 Hugging Face 受网络策略限制；本次通过可用的官方网页读取工具实际打开以下目录、说明卡与部分 JSON，没有借此下载音频或权重。

| 官方候选名 | 卡片中的采样率/说话人 | 卡片许可与来源 | 本项目决定 |
| --- | --- | --- | --- |
| `zh_CN-huayan-medium` | 22,050Hz，1人 | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/zh/zh_CN/huayan/medium/MODEL_CARD)：HuaYan_TTS 数据许可 **Unknown**；由 lessac medium 微调。[JSON](https://huggingface.co/rhasspy/piper-voices/blob/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json) 是 `espeak`、`cmn` | 技术上符合初期接口类型；没有权利批准，不自动下载或用于商业成片 |
| `zh_CN-huayan-x_low` | 16,000Hz，1人 | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/zh/zh_CN/huayan/x_low/MODEL_CARD)：HuaYan_TTS 数据许可 **Unknown**。旧配置未写 phoneme_type、espeak.voice 为 cmn | 同样保持 unreviewed；不能因为可免费下载就视为授权 |
| `zh_CN-xiao_ya-medium` | 22,050Hz，1人 | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/1f265c6bbb3612a8581fc384c91b23fe0b5a0297/zh/zh_CN/xiao_ya/medium/MODEL_CARD)：BZNSYP 数据注明 **Non-commercial use**；要求 Python Piper 1.4+ 与 g2pW | 不作为商业短剧默认声音；当前 pinyin 路线也被离线预检阻断 |
| `zh_CN-chaowen-medium` | 22,050Hz，1人 | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/10eb5c756ae21b759c8344d54aef86f9399ae92d/zh/zh_CN/chaowen/medium/MODEL_CARD)：voice-datasets 数据 **CC0**，同时注明由 Xiao Ya 微调；[提交配置](https://huggingface.co/rhasspy/piper-voices/commit/10eb5c756ae21b759c8344d54aef86f9399ae92d) 为 pinyin | CC0 描述的是本次数据，不能直接消除上游模型非商业来源链疑问；需核实模型权利，当前 pinyin 也不启用 |

Hugging Face 顶层“MIT”标签不覆盖每个模型的数据、说话人、衍生训练与用途限制。上述“Unknown/非商业/来源链待核”是从官方卡片得到的制作决策依据，不能据此伪造许可已确认。未来采用任一模型时，持久化模型与配置的 SHA-256、来源 revision、MODEL_CARD、数据与声线授权说明；未经核实不要把权重加入公开 Git 或容器分发。

如需立即制作真实中文对白，当前稳定路径是用户提供已有授权录音，或先选定具备明确用途授权、已在本地准备齐全的中文 `espeak` 声音模型再做实际发音与情绪试听。项目默认测试声是技术占位，不是真人配音或商业可发布的 TTS 成果。
