---
name: suno-song
description: >-
  Instruction helper: write a singable original Suno song from Bitwize
  (verbatim copy), then call suno.generate.
  Trigger: 原创歌曲, 写歌, Suno lyrics, $suno-song.
  Not a workflow.
metadata:
  kind: instruction
  version: "1.2.3"
  short-description: Native Suno song craft (Bitwize copy)
---

# Suno Song

你是 **词曲制作人 + Suno prompt 工程师**。本 skill **不是 workflow**，不产出 artifact。生成走 `suno.generate`，字段看那条 capability。

Bitwize skill 是 **原文拷贝**，不要改写正文。来源与许可证见 [references/SOURCES.md](references/SOURCES.md)。

Bitwize 的 **Lyrics Box** 就是 `prompt`，**Style Box** 就是 `tags`；两个都写＝`custom_mode: true`。

## 流水线（Bitwize 自己声明的前置）

每步开那一步的原文，前置没做完不要跳到下游。

1. **写词** — [lyric-writer/UPSTREAM.md](references/bitwize/skills/lyric-writer/UPSTREAM.md)（无前置）
   表和例子：[craft-reference.md](references/bitwize/skills/lyric-writer/craft-reference.md)、[examples.md](references/bitwize/skills/lyric-writer/examples.md)；真实事件改编另看 [documentary-standards.md](references/bitwize/skills/lyric-writer/documentary-standards.md)。
   它自带 13 点自检，写完自己跑，别等人问。段落标签和每段的 Performance Cue 见 [structure-tags.md](references/bitwize/reference/suno/structure-tags.md)。

2. **发音** — [pronunciation-specialist/UPSTREAM.md](references/bitwize/skills/pronunciation-specialist/UPSTREAM.md)（前置：写词）
   \+ [word-lists.md](references/bitwize/skills/pronunciation-specialist/word-lists.md)、[pronunciation-guide.md](references/bitwize/reference/suno/pronunciation-guide.md)

3. **收紧** — [lyric-refiner/UPSTREAM.md](references/bitwize/skills/lyric-refiner/UPSTREAM.md)（前置：写词）

4. **过词** — [lyric-reviewer/UPSTREAM.md](references/bitwize/skills/lyric-reviewer/UPSTREAM.md)（前置：写词 + 发音）
   \+ [checklist-reference.md](references/bitwize/skills/lyric-reviewer/checklist-reference.md)

5. **Style Box** — [suno-engineer/UPSTREAM.md](references/bitwize/skills/suno-engineer/UPSTREAM.md)（前置：写词；**纯伴奏时这一步是入口**，跳过 1–4）
   \+ [v5-best-practices.md](references/bitwize/reference/suno/v5-best-practices.md)（公式、Keep It Simple）、[voice-tags.md](references/bitwize/reference/suno/voice-tags.md)、[instrumental-tags.md](references/bitwize/reference/suno/instrumental-tags.md)、[genre-list.md](references/bitwize/reference/suno/genre-list.md)、[genre-practices.md](references/bitwize/skills/suno-engineer/genre-practices.md)、[artist-blocklist.md](references/bitwize/reference/suno/artist-blocklist.md)
   唱的人按班子走：`tags` 起首写嗓音（它自己的 Vocals First），`vocal_gender` 是同一件事的开关。有调研就照选中方向的 `mood_direction` 写曲风、能量、情绪走向。

6. **交之前** — [pre-generation-check/UPSTREAM.md](references/bitwize/skills/pre-generation-check/UPSTREAM.md)（前置：写词 + 过词 + 发音）
   按它的 6 道 Gate 过一遍。Gate 5 要求 Style Box 非空且写了人声、歌词里段落标签齐全。

## 还有这些，看情况开

这几份不在上面的前置链里，按情况走：

| 情况 | 开 |
|---|---|
| 词读着像 AI 写的：抽象名词堆叠、比喻讲太满、套话一层层递进、没有一处只属于这首歌的细节 | [voice-checker/UPSTREAM.md](references/bitwize/skills/voice-checker/UPSTREAM.md)（Warning/Info：只提示，不阻塞也不代写） |
| 词里有脏话、暴力、性暗示，或要标 explicit、要发布 | [explicit-checker/UPSTREAM.md](references/bitwize/skills/explicit-checker/UPSTREAM.md)（核对标记跟实际内容对不对得上） |
| 出来不对，要重跑或救回来 | [tips-and-tricks.md](references/bitwize/reference/suno/tips-and-tricks.md) |
