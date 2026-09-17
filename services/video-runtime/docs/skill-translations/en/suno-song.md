# suno-song: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/external/suno-song/SKILL.md). Source SHA-256: `3baa60f09a43d4726d907eb76f2d1058b980ee6436cb8a621c987a701f15f3b6`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: suno-song
description: >-
  Instruction helper: write a singable original Suno song from Bitwize
  (verbatim copy), then call suno.generate.
  Trigger: original songs, songwriting, Suno lyrics, $suno-song.
  Not a workflow.
metadata:
  kind: instruction
  version: "1.2.3"
  short-description: Native Suno song craft (Bitwize copy)
```

# Suno Song

You are a **songwriter/composer and Suno prompt engineer**. This skill is **not a workflow** and does not produce an artifact. Generate through `suno.generate`; consult that capability for fields.

The Bitwize skill is a **verbatim copy**; do not rewrite its body. See [references/SOURCES.md](../../../skills/external/suno-song/references/SOURCES.md) for sources and licensing.

Bitwize's **Lyrics Box** maps to `prompt`, and its **Style Box** to `tags`; supplying both means `custom_mode: true`.

## Pipeline (Prerequisites Declared by Bitwize)

Open each step's original instructions. Do not proceed downstream before finishing prerequisites.

1. **Write lyrics** — [lyric-writer/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-writer/UPSTREAM.md) (no prerequisites).
   Tables and examples: [craft-reference.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-writer/craft-reference.md), [examples.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-writer/examples.md). For adaptations of real events, also read [documentary-standards.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-writer/documentary-standards.md).
   Run its 13-point self-check after writing without waiting to be asked. Section tags and per-section Performance Cues: [structure-tags.md](../../../skills/external/suno-song/references/bitwize/reference/suno/structure-tags.md).

2. **Pronunciation** — [pronunciation-specialist/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/pronunciation-specialist/UPSTREAM.md) (requires lyrics).
   \+ [word-lists.md](../../../skills/external/suno-song/references/bitwize/skills/pronunciation-specialist/word-lists.md), [pronunciation-guide.md](../../../skills/external/suno-song/references/bitwize/reference/suno/pronunciation-guide.md)

3. **Tighten** — [lyric-refiner/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-refiner/UPSTREAM.md) (requires lyrics).

4. **Review lyrics** — [lyric-reviewer/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-reviewer/UPSTREAM.md) (requires lyrics + pronunciation).
   \+ [checklist-reference.md](../../../skills/external/suno-song/references/bitwize/skills/lyric-reviewer/checklist-reference.md)

5. **Style Box** — [suno-engineer/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/suno-engineer/UPSTREAM.md) (requires lyrics; **instrumentals start here**, skipping 1-4).
   Plus [v5-best-practices.md](../../../skills/external/suno-song/references/bitwize/reference/suno/v5-best-practices.md) (formula, Keep It Simple), [voice-tags.md](../../../skills/external/suno-song/references/bitwize/reference/suno/voice-tags.md), [instrumental-tags.md](../../../skills/external/suno-song/references/bitwize/reference/suno/instrumental-tags.md), [genre-list.md](../../../skills/external/suno-song/references/bitwize/reference/suno/genre-list.md), [genre-practices.md](../../../skills/external/suno-song/references/bitwize/skills/suno-engineer/genre-practices.md), [artist-blocklist.md](../../../skills/external/suno-song/references/bitwize/reference/suno/artist-blocklist.md).
   Follow the cast commitments for the singer: describe the voice at the beginning of `tags` (its Vocals First rule); `vocal_gender` controls the same choice. If research exists, derive musical style, energy, and emotional progression from the chosen direction's `mood_direction`.

6. **Before submission** — [pre-generation-check/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/pre-generation-check/UPSTREAM.md) (requires lyrics + lyric review + pronunciation).
   Pass all six Gates. Gate 5 requires a nonempty Style Box specifying vocals and complete section labels in the lyrics.

## Optional Resources

These are outside the prerequisite chain; use when relevant:

| Situation | Open |
|---|---|
| Lyrics sound AI-written: stacked abstractions, overexplained metaphors, escalating stock phrases, no song-specific detail | [voice-checker/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/voice-checker/UPSTREAM.md) (Warning/Info only: advises, does not block or ghostwrite) |
| Profanity, violence, sexual references, explicit labeling, or publication | [explicit-checker/UPSTREAM.md](../../../skills/external/suno-song/references/bitwize/skills/explicit-checker/UPSTREAM.md) (check that labels match actual content) |
| The result is wrong and needs another run or recovery | [tips-and-tricks.md](../../../skills/external/suno-song/references/bitwize/reference/suno/tips-and-tricks.md) |
