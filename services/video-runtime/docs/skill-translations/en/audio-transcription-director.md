# audio-transcription-director: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../prompts/media/audio-transcription-director/SKILL.md). Source SHA-256: `1523ff41dd233d77d9db419053ee59c960f4fbcfb6bfdf0f8b2a37d71e9aebdb`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: audio-transcription-director
description: >-
  Transcribe uploaded audio with Gemini.
```

# Audio Transcription Director

Three-layer music analysis (global / section / segment) from Human JSON facts + audio media.

## Process

1. **Read the Human JSON facts**: `granularity` (`phrase`|`sentence`|`beat`), optional `generated_lyrics`, `user_input`, `audio_duration_sec` / `actual_duration`, optional lipsync max duration, optional `suno_alignment_context`, optional `content_language`.
2. Transcribe/analyze the attached audio. Reference priority: `user_input` > `generated_lyrics` > autonomous listen.
3. Output global + `sections[]` + `segments[]` per schema. Branch segment cutting on `facts.granularity` below.
4. When `suno_alignment_context` is non-empty, also apply **Suno word-alignment mode**.

## Segment granularity

### phrase
Cut on musical phrases, emotion turns, rhythm changes — not every sung breath. Multi-line lyrics OK in one segment if mood/tempo matches. Every segment needs `emotion` + `tempo`.

### sentence
One grammatical/semantic sentence is approximately one segment. Merge breathlets inside the same sentence. Chinese examples (translated): "Let this second slow down" versus "Let me see your face clearly" -> 2 segments. An English hook line stays one segment despite short pauses. Align ends to word boundaries. Pure instrumental: about 4-8s by mood.
If lipsync max duration is set and a sung sentence exceeds it: split only at the largest pause **inside that sentence**.

### beat
Override defaults: `bar_dur ≈ 240 / global_bpm` (4/4). Segments ≈ 1–4 bars; prefer downbeats; never cut mid-word. Pure instrumental: 1 bar_dur per segment. `global_bpm` must be accurate for bar snapping.

## Suno word-alignment mode

When facts include `suno_alignment_context` (structured facts: `section_hints`, `vocal_gender_hint`, word list with MM:SS.mmm, `(silence X.XXXs)` gaps):

1. **Use word timestamps** for each segment’s `start`/`end` — copy concrete word bounds; do not invent times.
2. **Word list ≠ lyric line breaks** — do not treat each word line (or silence gap) as a finished lyric sentence. Segment by heard phrase/sentence/beat per `granularity`.
3. **Silence gaps are cut candidates** — `(silence …)` marks breath/pause candidates; prefer cuts at phrase/sentence boundaries that also land on silence (lipsync-friendly). Not every silence starts a new segment.
4. **phrase**: merge semantically continuous words into one segment; cut at silence + musical/semantic boundary.
5. **sentence**: one independent semantic sentence = one segment; silence inside a sentence is breath only; open a new segment only when a new sentence begins.
6. **beat**: cut near downbeats / bar multiples; if a bar line falls mid-word, snap to nearest word start/end; output accurate `global_bpm`.
7. **vocal_presence**: true on windows with sung words; false on long instrumental silence regions.
8. **sections**: prefer boundaries matching `section_hints` starts.
9. **vocal_gender**: when `vocal_gender_hint` is `f`|`m`, use it on voiced segments.
10. **Coverage**: `segment.text` must cover what is actually sung in that window (trust audio over occasional Suno phantom repeats).

## Global fields

`task="transcribe"`, `language`, `duration` (MM:SS.mmm), `text`, `is_instrumental`, `song_name`, `global_bpm`, `genre`, `global_emotion`, `suggested_global_theme`, `suggested_color_palette`.

## sections[] (required)

`section_type`, `start_seconds`/`end_seconds` (MM:SS.mmm), `musical_features`, `section_emotion`, `suggested_visual_intensity`, `suggested_rhythmic_strategy`, `suggested_visual_theme`, `suggested_context`. Minimal form: one `Full` covering the track.

## segments[]

`id` (0-based), `start`/`end`/`duration` (MM:SS.mmm), `text`, required `emotion`/`tempo`, `vocal_presence`, optional `vocal_gender` (`f`|`m`), `section_index`.

## Hard constraints

1. No timestamp beyond total `duration`; chronological order.
2. All times MM:SS.mmm.
3. Segments must not cross section boundaries — split at the boundary if needed.
4. **Transcribe, don’t translate**: lyrics language = sung language; `language` is a label only. If refs disagree with audio, trust audio.
5. When `facts.content_language` is set, write user-visible analysis prose (`genre`, `global_emotion`, suggested theme/palette, section `musical_features` / emotions / visual notes, segment `emotion` / `tempo`) in that language. JSON keys stay English. Do not use `ui_locale` for those fields.
