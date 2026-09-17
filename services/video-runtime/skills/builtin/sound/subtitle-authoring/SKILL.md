---
name: subtitle-authoring
description: Plan and execute readable burned-in captions for an existing video. Use for requests to add subtitles, captions, speech transcription, subtitle files, or caption styling to a selected video artifact.
---

# Subtitle Authoring

If the user explicitly requests HyperFrames, kinetic, karaoke-highlighted, neon, glitch,
or other animated captions, use `hyperframes-captions` instead of this static workflow.

Create captions as three persisted stages. Schedule only the next stage after its
required artifact exists so task history and failures remain observable.

1. Run `media.transcribe` with the selected `video` artifact. Preserve the detected
   source language unless the user explicitly provides a language hint. Transcribe the
   complete final video, not one representative segment.
2. Run `subtitle.compose` with the resulting `transcript` artifact. Default to SRT,
   `timing_mode=audio`, two lines, 18 CJK characters or 42 Latin characters per line,
   and 15 CPS. Audio timing is authoritative: each cue must start at the first detected
   spoken word and end at the final detected word, with only a minimal trailing pad.
3. Run `media.subtitle_burn` with both the original `video` and generated `subtitle`
   artifacts. Default to `clean` and `bottom-safe`. Continuous dialogue must use a
   normal film-caption scale near the lower edge; do not use center placement or
   oversized social-video typography unless the user explicitly requests it.

Do not claim success after transcription or subtitle-file generation. The requested
captioned video is complete only when `media.subtitle_burn` produces a durable Cuti
video artifact.

Do not translate speech unless the user explicitly requests translation. The current
tool chain creates source-language captions; explain that translation is a separate
step if source and target languages differ.

Never infer dialogue timestamps from a script, shot boundary, prompt, or segment duration.
When a transcript artifact exists, do not pass replacement cues. For explicitly requested
manual captions, set `timing_mode=manual` and pass `cues` directly to `subtitle.compose`.
Each cue must contain numeric `start`, numeric `end`, and non-empty `text`.

Read [references/quality-rules.md](references/quality-rules.md) when choosing layout,
line breaking, or a non-default style.
