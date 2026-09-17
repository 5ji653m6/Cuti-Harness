# Skill 英文阅读副本

[English](README.md) | 中文

本目录是产品已配置 Skill（技能）根目录中，中文和中英混合 `SKILL.md` 入口文档的参考译文，供开发者阅读，不是可执行 Skill。原始文件、元数据、资源包、权限和工作流行为均保持不变。

## 阅读约定

- 每份副本完整翻译入口文档，包括描述、指令、注释和示例；已有英文段落保留。链接的辅助资源仍位于原处，本目录不另外翻译这些资源。
- 翻译后的触发短语、示例对白、搜索词和标准回复只解释原文，不新增运行时别名，也不改变所要求的输出语言。例如，`language-zh` 的英文副本仍要求输出简体中文。
- 文档中的中文机器标记使用字面 Unicode 转义：图片 = `\u56fe\u7247`，视频 = `\u89c6\u9891`，音频 = `\u97f3\u9891`。因此，`@\u56fe\u72471` 表示原始的编号图片标记。理解这些示例时将转义还原为原字符；不要把字面反斜杠序列当作替代语法传入接口。英文提示词示例仅作解释，原文要求中文时不能直接替换使用。
- 每份副本记录源文件 SHA-256。原文更新时，译文和校验值一起更新。原始约束，包括遗留或相互矛盾的条款，只做翻译而不静默修正；仍以原文为准。
- 原始版权和许可证义务继续适用。阅读副本不授予 Skill 或辅助材料的任何额外权利。

## 运行时隔离

本目录位于 [configured_skill_roots](../../app/video_runtime/skills.py) 返回的根目录之外。副本不命名为 `SKILL.md`，元数据仅以围栏代码块呈现，且没有被生效的 Skill 指令、前端代码、后端代码或插件元数据清单引用。[SkillCatalog](../../app/chat/v2/skill_catalog.py) 发现 `SKILL.md`，并从各 Skill 自己的目录暴露资源；这些文档副本不进入其中任何一条路径。不要将其复制进 Skill 包，也不要把本目录配置为 Skill 根目录。

## 翻译索引

| Skill | 译文 | 运行时原文 |
|---|---|---|
| audio-transcription-director | [英文](en/audio-transcription-director.md) | [原文](../../prompts/media/audio-transcription-director/SKILL.md) |
| cinematic | [英文](en/cinematic.md) | [原文](../../skills/external/cinematic/SKILL.md) |
| cuti-scenario-product-workflow | [英文](en/cuti-scenario-product-workflow.md) | [原文](../../skills/external/cuti-scenario-product-workflow/SKILL.md) |
| cuti-story-card-test | [英文](en/cuti-story-card-test.md) | [原文](../../skills/external/cuti-story-card-test/SKILL.md) |
| h3 | [英文](en/h3.md) | [原文](../../skills/external/h3/SKILL.md) |
| hyperframes-captions | [英文](en/hyperframes-captions.md) | [原文](../../skills/builtin/sound/hyperframes-captions/SKILL.md) |
| image-consistency-director | [英文](en/image-consistency-director.md) | [原文](../../kit/skills/stages/image_consistency/image-consistency-director/SKILL.md) |
| language-zh | [英文](en/language-zh.md) | [原文](../../skills/external/language-zh/SKILL.md) |
| mv | [英文](en/mv.md) | [原文](../../skills/external/mv/SKILL.md) |
| product-voiceover-narration | [英文](en/product-voiceover-narration.md) | [原文](../../skills/external/product-voiceover-narration/SKILL.md) |
| seedance2 | [英文](en/seedance2.md) | [原文](../../skills/external/seedance2/SKILL.md) |
| short-drama-workflow | [英文](en/short-drama-workflow.md) | [原文](../../skills/external/short-drama-workflow/SKILL.md) |
| suno-song | [英文](en/suno-song.md) | [原文](../../skills/external/suno-song/SKILL.md) |
| video-consistency-director | [英文](en/video-consistency-director.md) | [原文](../../kit/skills/stages/video_consistency/video-consistency-director/SKILL.md) |
| video-research | [英文](en/video-research.md) | [原文](../../skills/builtin/research/video-research/SKILL.md) |
