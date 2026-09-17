# hyperframes-captions: English Reading Copy

Reference copy for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/builtin/sound/hyperframes-captions/SKILL.md). Source SHA-256: `144069ea5847eb7e3aafaac5ccca9b38ebaabf7ff24e6b7b741b725965d3f525`.

See [reading conventions](../README.md#reading-conventions). The runtime Skill remains authoritative.

## Runtime behavior

The finished film already exists. Overlay words on it: lyrics, dialogue, titles,
or decorative type. Write the HyperFrames HTML yourself and pass it as
`caption_html`.

1. Transcribe the complete mixed film. Keep source-language timestamps unless
   translation is requested.
2. Look at the picture, the song, and the story. Load `hyperframes-core` if you
   need the `data-*` contract.
3. Write `caption_html` with the transcript's words and times. The film sits
   underneath. Without `caption_html`, this overlay does not run.
4. Finish the same film and transcript in one pass.

Whether words follow the vocal, whether titles appear, and where type sits are
Agent decisions. User direction wins. Keep the subject readable. Keep Chinese on
a CJK-capable font. Surface missing Node / Chrome / GSAP / CLI errors.
