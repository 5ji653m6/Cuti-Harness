# product-voiceover-narration: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/external/product-voiceover-narration/SKILL.md). Source SHA-256: `f2bba26e7dd533357196fd0b74db3c8b81b11eb98fda57012653b7f4329aa0c1`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: product-voiceover-narration
description: >-
  Design concise native voiceover for commercial product-video segments and bind each spoken line to verified selling points, visible actions, and exact timeline ranges. Use when a product advertisement should introduce the product through narration, when Seedance 2.0 should generate picture and voice together, or when product shots need coordinated narration, music, and sound direction. Do not synthesize a separate voice track and never invent product claims.
metadata:
  kind: narration
  version: "0.3.0"
  roles: [guidance, stage_supervisor]
  scope:
    type: stage
    selectors:
    capabilities:
      - atomic.text.generate
      - atomic.video.generate
      - api.provider.generate
      - api.ark_protocol.generate
    artifact_types:
      - script
      - storyboard
      - video_clip
  hooks: [before_stage, after_stage]
  narration:
    category: product_native_voiceover
    activation: default
```

# Product Voiceover Narration

Design narration as part of the Seedance 2.0 audiovisual prompt. Generate picture, narration, music, and sound effects together in the same 15-second provider task. Do not call TTS, create a separate narration asset, or add a post-production dubbing stage.

Run only after `product-feature-demo-script` has produced the shared `segment_script` and all selected effect Skills have finalized its visual beats. Fill narration into that structure; do not create a parallel timeline, add selling points, redesign shots, or change the trigger-response-result chain. If a visual beat cannot support truthful narration, return `revision_required` to the visual script stage instead of silently changing it.

## Fill the shared segment script

Attach narration to the exact existing beat it supports:

```yaml
narration_mode: native_voiceover
voice_profile: {project-level frozen profile}
voice_profile_hash: {Harness-generated SHA-256}
segment_script:
  beats:
    - beat_id: segment-01-beat-01
      start_seconds: 0
      end_seconds: 3
      selling_point_status: verified
      visual: {unchanged visual direction}
      narration:
        start_seconds: 0.8
        end_seconds: 2.8
        text: exact spoken words
```

Use only existing `beat_id` values. Keep every spoken interval inside its visual beat. Narrate only `verified` or explicitly `conceptual` beats; never narrate an `unknown` claim. Use `narration_mode: music_only` with all narration fields null only when the user explicitly requests no voiceover.

## Ground every line

Use only Product Truth and verified selling points. Bind every spoken line to:

- an exact time range inside the segment;
- the visible shot or product action at that moment;
- one verified selling point or restrained brand idea;
- the project's language, speaker profile, tone, and pace.

Never invent specifications, performance numbers, awards, comparisons, certifications, accessories, or capabilities. When the image cannot demonstrate a claim, remove or soften the line instead of using narration to assert it.

## Decide narration density

Use narration by default for a commercial product workflow, but keep it selective:

- use one to three short lines per 15-second segment;
- keep Chinese narration around 30–50 characters per segment by default;
- leave breathing space for product action, transitions, sound effects, and the final packshot;
- avoid speaking across every second or reading a product manual;
- omit narration from a beat when silence or a product sound communicates the idea better.

If the user explicitly requests music-only output, skip narration and record that decision in the shot plan.

## Maintain project-level voice continuity

Choose one reusable voice direction for the whole advertisement:

- language and pronunciation;
- speaker identity and vocal age range;
- tone and emotional restraint;
- speaking pace;
- narrative perspective;
- fixed pronunciation of the product or brand name when supplied.

Offer `male_mid_low` as an optional reusable voice preset. Select it when the user requests a male mid-low voice, a steady male commercial narrator, or an equivalent direction. Do not force it when the user asks for another voice or leaves voice casting to the creative context.

```yaml
voice_profile:
  preset: male_mid_low
  gender_presentation: male
  apparent_age: adult
  timbre: natural mid-low register, warm and steady, clear low-frequency body
  pitch: moderately low, never artificially deep
  pace: measured and conversational
  delivery_style: restrained cinematic commercial narration, not an announcer voice
  emotional_energy: calm confidence
  microphone_distance: consistent close studio distance
  recording_space: clean, dry, intimate studio sound
```

Adapt language, accent, narrative perspective, emotional nuance, and supplied product pronunciation to the project, then freeze the complete profile. Preserve the defining `male_mid_low` characteristics: adult male presentation, natural middle-to-low register, warm steady body, moderate pitch, and restrained delivery. Avoid exaggerated bass, breathy whispering, trailer-style growling, radio-host projection, or a different vocal age between segments.

Create the voice profile once before the first narrated segment and persist it unchanged for the entire advertisement. Treat language, accent, gender presentation, apparent age, timbre, pitch, pace, delivery style, emotional energy, narrative perspective, product pronunciation, and recording-space description as immutable.

The Harness serializes the profile canonically and writes `voice_profile_hash`. Every narrated segment must carry the exact same profile and hash. Do not paraphrase, regenerate, or extend the profile per segment. From segment 2 onward, explicitly request a direct continuation by the same narrator, with unchanged microphone distance, loudness, pace, pitch, accent, emotional tone, and recording environment. Do not claim exact biometric identity when the provider cannot guarantee it.

## Write a complete native-audio prompt

For every 15-second segment, merge narration into the same time-coded Chinese Seedance prompt as the visual plan. State:

1. generate one complete 15-second video with native synchronized audio;
2. the visual action and the exact start and end time of each spoken line;
3. the exact words to speak, enclosed as direct speech;
4. the language, speaker direction, tone, and pace;
5. where narration pauses for transitions, product actions, or the closing shot;
6. concise music and sound-effect direction, with music kept below speech while narration is active.

When `voice_profile.preset` is `male_mid_low`, repeat a compact but exact voice lock in every provider prompt: `The same adult male mid-low voice, naturally warm in timbre, steady and clear, moderately low in pitch, restrained with a cinematic advertising quality; no exaggerated bass, roaring trailer delivery, or broadcast-presenter delivery.` This textual lock supplements rather than replaces the persisted profile and hash.

Do not output narration as an unrelated paragraph after the visual prompt. Place each line next to its corresponding timeline beat.

Example structure:

```text
Generate a complete 15-second Chinese product advertisement with native synchronized audio.
0-4s: Macro view of product materials. At 1-3.8s, a composed, restrained adult female narrator says: "Precision acoustics, distilled into a lighter silhouette."
4-8s: Show the product's functional action, with action sound effects only and no narration.
8-12s: Show the function's visible result. At 8.5-11.5s, the same female narrator says: "Bringing every listening experience closer to sound itself."
12-15s: Hold a complete product hero shot; music naturally builds, with the final second left open.
Audio requirements: Clear, natural Mandarin; the same speaker; narration synchronized to visuals; lower background music during narration so it does not mask speech.
```

Adapt the wording and timings to the actual product. Do not reuse example claims when they are unsupported.

## Validate before generation

Reject or revise the prompt before calling Seedance when:

- a narration line has no time range or visible-shot binding;
- the spoken language does not match the user's language without an explicit request;
- the line introduces an unsupported product fact;
- the estimated reading time exceeds its assigned interval;
- narration covers nearly the entire segment without a creative reason;
- the prompt asks for separate TTS, dubbing, or an external narration track;
- it does not explicitly request native synchronized audio.
- its `voice_profile_hash` differs from any earlier narrated segment;
- a selected `male_mid_low` profile is missing its defining voice lock from the provider prompt;
- it changes an existing visual beat instead of returning `revision_required`.

## Supervise the result

Accept the generated segment when the narration is audible, uses the requested language and direction, starts near the intended visual beat, supports what the viewer sees, and does not overpower or get buried by the music. If narration timing or intelligibility fails, simplify the number of lines, shorten the text, widen the speaking interval, and make the audio priority explicit before retrying.
