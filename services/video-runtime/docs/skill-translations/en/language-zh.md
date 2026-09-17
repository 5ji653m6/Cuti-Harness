# language-zh: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/external/language-zh/SKILL.md). Source SHA-256: `b0bb8be7d55a3d5839eb7057555c3ebbfc044d534bcafc033f8d5b3cb1e291f1`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: language-zh
description: Keep one agent run's user-visible output, spoken narration or dialogue, and requested on-screen copy in Simplified Chinese. Use when the user invokes $language-zh or $zh.
metadata:
  kind: language
  version: "0.1.0"
  roles: [guidance, stage_supervisor]
  scope:
    type: run
  hooks: [before_stage, after_stage]
  language:
    code: zh-CN
    aliases: [zh]
```

# Chinese Language Contract

Maintain these language choices throughout every stage of this run:

- Use Simplified Chinese for user-visible replies, plans, task titles, summaries, scripts, shot plans, and review reports.
- Use Mandarin for natively generated video narration or dialogue; retain the same voice settings across segments.
- Use Simplified Chinese for on-screen text or subtitles only when the content calls for them; do not force their addition.
- Preserve brand names, model numbers, code, JSON keys, capability IDs, model IDs, and other machine identifiers.
- Use the prompt language best suited to the current model and workflow. The legacy `seedance2` workflow may still use Chinese generation prompts and explicitly require Chinese speech.

This choice lasts until the run ends or the user explicitly switches to another language Skill. Do not rewrite completed artifacts.
