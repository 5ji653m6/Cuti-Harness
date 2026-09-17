---
name: language-en
description: Keep one agent run's user-visible output, spoken narration or dialogue, and requested on-screen copy in English. Use when the user invokes $language-en, $eng, or $en.
metadata:
  kind: language
  version: "0.1.0"
  roles: [guidance, stage_supervisor]
  scope:
    type: run
  hooks: [before_stage, after_stage]
  language:
    code: en-US
    aliases: [eng, en]
---

# English language contract

Keep these language choices throughout the current run:

- Write user-visible responses, plans, task titles, summaries, scripts, shot plans, and review reports in English.
- Generate native video narration or dialogue in English and preserve the same voice profile across segments.
- Use English for on-screen copy or subtitles only when the content calls for them; do not force text or subtitles into the video.
- Preserve brand names, model names, code, JSON keys, capability IDs, model IDs, and other machine identifiers.
- Use the provider-prompt language best suited to the active model and workflow. The legacy `seedance2` workflow may keep its generation prompt in Chinese while explicitly requiring English speech.

This selection persists until the run ends or the user explicitly switches language Skills. Do not rewrite completed artifacts.
