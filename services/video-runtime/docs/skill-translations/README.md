# English Skill Reading Copies

English | [中文](README.zh.md)

Reference translations of the Chinese and mixed-language `SKILL.md` entry documents in the product's configured Skill roots. These copies are for developers, not executable Skills. Original files, metadata, resource bundles, permissions, and Workflow behavior remain unchanged.

## Reading conventions

- Each copy translates the complete entry document, including descriptions, instructions, comments, and examples; existing English passages are retained. Linked supporting resources remain at their original locations and are not separately translated here.
- Translated trigger phrases, sample dialogue, search queries, and standard response text explain the originals; they do not introduce new runtime aliases or change required output languages. For example, the English copy of `language-zh` still requires Simplified Chinese output.
- Chinese machine tokens use literal Unicode escapes in this documentation: image = `\u56fe\u7247`, video = `\u89c6\u9891`, audio = `\u97f3\u9891`. Thus `@\u56fe\u72471` denotes the original numbered image token. Decode escapes to the original characters when interpreting such examples; do not send literal backslash sequences as replacement syntax. English prompt examples are explanatory, not translations that may be substituted where the source requires Chinese.
- Each copy records its source SHA-256. When the original changes, update the translation and hash together. Original constraints, including legacy or contradictory clauses, are translated rather than silently corrected; the source remains authoritative.
- Original copyright and license obligations continue to apply. A reading copy does not grant any additional rights to a Skill or its supporting materials.

## Runtime isolation

This directory is outside the roots returned by [configured_skill_roots](../../app/video_runtime/skills.py). Copies are not named `SKILL.md`, contain only a fenced metadata excerpt, and are not referenced by active Skill instructions, front-end code, backend code, or plugin manifests. [SkillCatalog](../../app/chat/v2/skill_catalog.py) discovers `SKILL.md` and exposes resources from each Skill's own directory; these documentation copies enter neither path. Do not copy them into Skill bundles or configure this documentation directory as a Skill root.

## Translation index

| Skill | Translation | Runtime source |
|---|---|---|
| audio-transcription-director | [English](en/audio-transcription-director.md) | [Original](../../prompts/media/audio-transcription-director/SKILL.md) |
| cinematic | [English](en/cinematic.md) | [Original](../../skills/external/cinematic/SKILL.md) |
| cuti-scenario-product-workflow | [English](en/cuti-scenario-product-workflow.md) | [Original](../../skills/external/cuti-scenario-product-workflow/SKILL.md) |
| cuti-story-card-test | [English](en/cuti-story-card-test.md) | [Original](../../skills/external/cuti-story-card-test/SKILL.md) |
| h3 | [English](en/h3.md) | [Original](../../skills/external/h3/SKILL.md) |
| hyperframes-captions | [English](en/hyperframes-captions.md) | [Original](../../skills/builtin/sound/hyperframes-captions/SKILL.md) |
| image-consistency-director | [English](en/image-consistency-director.md) | [Original](../../kit/skills/stages/image_consistency/image-consistency-director/SKILL.md) |
| language-zh | [English](en/language-zh.md) | [Original](../../skills/external/language-zh/SKILL.md) |
| mv | [English](en/mv.md) | [Original](../../skills/external/mv/SKILL.md) |
| product-voiceover-narration | [English](en/product-voiceover-narration.md) | [Original](../../skills/external/product-voiceover-narration/SKILL.md) |
| seedance2 | [English](en/seedance2.md) | [Original](../../skills/external/seedance2/SKILL.md) |
| short-drama-workflow | [English](en/short-drama-workflow.md) | [Original](../../skills/external/short-drama-workflow/SKILL.md) |
| suno-song | [English](en/suno-song.md) | [Original](../../skills/external/suno-song/SKILL.md) |
| video-consistency-director | [English](en/video-consistency-director.md) | [Original](../../kit/skills/stages/video_consistency/video-consistency-director/SKILL.md) |
| video-research | [English](en/video-research.md) | [Original](../../skills/builtin/research/video-research/SKILL.md) |
