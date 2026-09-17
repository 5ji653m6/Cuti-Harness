# Subtitle quality rules

## Timing

- Keep every cue inside the video duration.
- Prefer at least 0.7 seconds per cue and avoid overlaps.
- Target no more than 15 characters per second for CJK and 20 for Latin text.
- Preserve the transcription timestamps; do not invent speech outside detected audio.
- Start each cue on the first detected spoken word. Do not add leading padding that makes
  text appear before the voice.
- End on the last detected word plus at most 120 ms of trailing padding, and clamp the
  result before the next cue to prevent overlap.
- Use full final-video transcription as the timing source. Script timing and shot timing
  are content references only and must never drive dialogue cue times.

## Layout

- Use no more than two lines.
- Break CJK text near punctuation and keep semantic phrases together.
- Break Latin text between words, never inside a word.
- Use `bottom-safe` unless the user requests another placement.
- Use `center` only for title-like captions, not continuous dialogue.
- For continuous dialogue, keep the visible glyph height around 4-6% of video height
  and the baseline roughly 4-7% above the bottom edge.
- Review at least one rendered frame containing a two-line cue before reporting the
  captioned video complete. Reject layouts that cover faces or the central action.

## Style presets

- `short-video-bold`: bold white text with a dark outline; use only when explicitly
  requested for social-video emphasis.
- `clean`: regular white text, restrained outline, and normal bottom-caption sizing;
  use this default for dialogue in landscape or portrait video.
- `minimal`: smaller text and lighter outline for presentation-style video.

## Review

- Confirm the compose result reports zero overlaps and no invalid cues.
- Treat CPS violations as warnings unless readability is clearly unacceptable.
- Keep the original video artifact; burned captions must create a new version.
