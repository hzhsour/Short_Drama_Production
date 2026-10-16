---
name: storyboard-breakdown
description: 将剧本拆成可拍摄的场景、镜头、画面和声音计划，并输出本项目可校验的分镜 JSON；当用户要分镜、镜头表或拍摄清单时使用。
---

# 剧本转分镜

## 拆镜规则

- 先建立场景 ID，再按叙事信息、表演反应、动作和剪辑需要拆镜；不为镜头数量牺牲因果和情绪。
- 使用稳定编号 `EP001-SC01-SH001`。每镜给出正整数 `duration_frames`，不要用浮点秒数造成帧边界歧义。
- 明确角色 ID、地点、可见动作、景别、角度/运动、对白、环境声/音乐、静帧提示、运动提示和连续性引用。
- 图像提示描述构图、固定角色识别、地点、光线和风格；视频提示描述单一清晰动作、节奏及镜头运动。避免互相矛盾的动作。
- 维持视线、轴线、动作方向、进出画方向和道具/服装状态。需要反打或转场时写清楚空间关系。

## 输出

以 `docs/templates/storyboard.schema.json` 为字段契约，在对应集目录输出 `storyboard.json`。写完运行 `npm run validate`；修复缺字段、重复 ID、错误帧数与 JSON 语法错误。实际素材路径、模型和审核状态在素材说明中追踪。

## 可运行的数据转换

- 结构化剧本采用 `docs/templates/script.schema.json`：顶层声明 `episode_id/aspect_ratio/fps/scenes`；每场声明 `scene_id/location/shots`，每镜保留完整动作、构图、声音和提示。镜头可继承所在场景的 `scene_id/location`。
- 调用 `short_drama.script.script_to_storyboard(script, characters=None)` 输出标准分镜。此函数确定性转换已写明的 scenes/shots，不调用语言模型，不会把自由文本自动创作成专业分镜。自然语言创作由 Codex 按剧本 Skill 完成并经过创作者确认后再保存为结构化数据。
- 对白对象为 `{character_id,text,start_frame,duration_frames}`；所有帧数相对当前镜头，必须落在镜头范围内。当前单轨字幕管线拒绝重叠对白；需要交叠表演时先设计并实现多轨字幕方案。
- 音效/音乐可使用原有非空说明字符串（只在 Mock 中生成测试提示音），或声明 `{kind:"bgm"|"sfx"|"ambience",path,start_frame,duration_frames,volume}`。本地真实音频须指定已授权素材，不能把 Mock 音调描述成真实声音成品。
- `validate_storyboard(data, characters=None)` 校验类型、稳定 ID、所属剧集/场景、重复项、角色引用、帧边界、对白重叠与路径。空 `shots` 仅供草稿保留，生成和渲染阶段必须拒绝空剧集。
- 每镜关联角色档案与 `continuity_refs`；未准备参考素材时明确计划状态，不伪造已审核参考图。
