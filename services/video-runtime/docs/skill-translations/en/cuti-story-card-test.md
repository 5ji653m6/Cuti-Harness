# cuti-story-card-test: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/external/cuti-story-card-test/SKILL.md). Source SHA-256: `a4ea34f676bb963d510b9ac2e0c11c0ee0f5f01322c585356749dcd1d3ad6445`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: cuti-story-card-test
description: >-
  Turn a short-video idea into a compact story card with a visual hook,
  a meaningful change, and a memorable ending. Use for story-card drafting,
  story cards, short-video concept cards, or $cuti-story-card-test. Supports Chinese and English.
metadata:
  kind: helper
  version: "1.0.0"
  short-description: Story card test
```

# Story card test

This is an instruction-only helper for testing uploaded Skills in Cuti. It supplies a writing format; it does not register a generation capability or select a video Workflow.

When drafting a story card, use the language requested by the user. If no output language was specified, match the user's message. Preserve their subject, target duration, and explicit creative constraints.

Begin the response with the exact test marker `CUTI-STORY-CARD-V1`. This marker belongs in the written response only, not in generated media or Provider prompts.

Write these four short labeled paragraphs, using the labels in the requested language:

- Visual hook: a concrete opening image that raises a question.
- Turning point: an observable action that changes the situation.
- Memorable ending: a closing image that answers or transforms the opening.
- Continuity anchors: two or three specific visual details to preserve across shots, chosen from the user's idea or clearly presented as creative proposals.

End with one short line labeled Next step. For a writing-only request, suggest a possible next creative step without executing it. Avoid inserting an arbitrary fixed number of shots; choose story beats appropriate to the requested duration.

If the user requests only text, respond directly in the conversation and do not create a Build or call image, video, music, or speech Providers. If the user also requests generation, keep this card as creative guidance, load the chosen Workflow, and use its available capabilities and normal PlanPatch execution rules.
