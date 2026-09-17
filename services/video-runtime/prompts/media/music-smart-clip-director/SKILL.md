---
name: music-smart-clip-director
description: >-
  Analyze music for smart clip points.
---

# Music Smart Clip Director

Recommend a continuous clip near target duration from transcription JSON facts. Text-only — you do not hear audio.

## Process

1. **Read the Human JSON facts**: `audio_duration_sec`, `target_duration_sec`, `global_bpm`, `global_emotion`, `genre`, `sections[]`, `segments[]` (with `vocal_presence`).
2. If `audio_duration_sec ≤ target_duration_sec + 1`: recommend full `[0, audio_duration_sec]`, `candidates=[]`.
3. Otherwise pick recommended window + 3–6 scored candidates. Output schema JSON.

## Selection priority

1. Keep chorus/refrain/hook **complete** when present.
2. Prefer cuts on segment boundaries / `vocal_presence=false` gaps — not mid-lyric.
3. Bar align: `bar_dur ≈ 60/BPM × 4`; prefer bar-line multiples.
4. Low-energy features (soft/quiet/fade/ambient) as fade-out anchors.
5. Minimize `|actual - target|` among options that satisfy 1–4.

## Fade & candidates

- `fade_in_sec`: 0.3–0.8 if start ≠ 0 and not on section boundary; else 0.
- `fade_out_sec`: 1.0–2.0 if end not natural outro; 0.5–1.0 if natural_fadeout.
- `fade_in + fade_out < 0.5 × (end - start)`.
- Candidates kinds: `phrase_end|bar_line|low_energy|section_boundary|natural_fadeout`; `time_sec ∈ [0, audio_duration_sec - 0.5]`; sort by `score` desc.
- `vocal_safe=true` ≈ ±300ms silence gap; else fade_out ≥ 1.0s.

## Constraints

- `start_sec ≥ 0`, `end_sec ≤ audio_duration_sec`, duration ≥ 1.0s.
- Compute `actual_duration_sec` and `duration_error_sec` correctly.
- `method` = `"ai_reuse_transcription"`; `fallback_used` = `false`.
