---
name: short-drama-workflow
description: >-
  Workflow for producing plot-dense short dramas with character and location
  reference sheets, complete 15-second Seedance segments, native dialogue,
  parallel multi-reference T2V generation, duration validation, and final assembly. Use for
  爽文短剧、都市反转短剧、对白短剧、连续多段短剧，或用户明确调用
  $short-drama-workflow. Do not use for product-centered scenario advertisements.
metadata:
  kind: workflow
  version: "1.1.0"
  workflow:
    title: Short drama production
    mode: short_drama_workflow
    planning:
      mode: staged
      checkpoints:
        - id: story_ready
          after_phase: story_intent
          next_phase: visual_production
          required_artifacts: [story_draft]
          resolves: [characters, scenes, shots, audio]
          instruction: Complete dialogue, shared references, and parallel shot specifications from the story draft.
    entrypoints: [text, image, audio, video]
    dependencies:
      # Planning guidance only. Runtime leaf steps still carry no legacy
      # Director Skill injection and remain owned by this Workflow compiler.
      skills: [seedance2]
    parameters:
      shot_workflow_mode: seedance2_short_drama
      content_category: short_drama
      segment_duration_seconds: 15
      segment_execution_mode: parallel
      video_generation_mode: t2v
      continuity_mode: shared_reference_images
    pipeline:
      - atomic.text.generate
      - atomic.image.generate
      - atomic.video.generate
      - media.concat
      - media.transcribe
      - subtitle.compose
      - media.subtitle_burn
    requires_keyframe: false
    allowed_capabilities:
      - actions.suggest
      - atomic.text.generate
      - atomic.image.generate
      - atomic.video.generate
      - api.provider.generate
      - api.ark_protocol.generate
      - media.concat
      - media.transcribe
      - subtitle.compose
      - media.subtitle_burn
---

# Short Drama Workflow

Create a compact narrative in complete 15-second video units. Use the installed
legacy `seedance2` Skill for Seedance prompt grammar and multi-reference mechanics.
Generate through WaveSpeed Seedance 2.5 unless the user explicitly selects a
different available model. Do not load unrelated prompt-only helper bundles.

## Workflow identity

Carry these fields on every stage task:

```json
{
  "workflow_mode": "short_drama_workflow",
  "activated_workflow": "short-drama-workflow",
  "shot_workflow_mode": "seedance2_short_drama",
  "content_category": "short_drama"
}
```

Also preserve the project `thread_id`, chosen aspect ratio, resolution, model,
output language, and spoken-language contract across all stages.

## Main production flow

### 1. Lock the story and production bible

Use `atomic.text.generate` once to create the executable production blueprint.
This is a language-model stage: omit `model`, or use a supported `llm_model` only.
Never set `model: seedance-2.5` on this task; that video model belongs exclusively
to `atomic.video.generate` segment tasks.
It must contain:

- the complete causal story and ending;
- a compact character bible with stable appearance, clothing, temperament, and
  relationships;
- a location and lighting bible for recurring spaces;
- one dramatic function for each 15-second segment;
- a complete time-coded beat plan for every segment, with a new action, reaction,
  revelation, or power shift roughly every 1-2 seconds;
- native dialogue, ambience, sound effects, music or deliberate silence;
- a narrative handoff describing what changes at the end of each segment and what
  the next segment must continue, without requiring pixel-matched boundary frames;
- one generation-ready Seedance prompt per segment.

For a default 60-second request, produce four 15-second segments. For another
duration, use the smallest sensible number of complete 15-second segments and
tell the user if the requested duration requires rounding or a shorter final edit.
Do not silently replace 15-second units with 5- or 6-second clips.

### 2. Generate character and location reference images

Before any video generation, create and persist the setting images described by
the approved production blueprint.

Use `atomic.image.generate` to produce:

- a character setting reference for every recurring principal character, showing
  stable face, hair, apparent age, body proportions, costume, palette, and one or
  more useful views; use an ensemble sheet only when it remains easy to identify
  each person unambiguously;
- a scene setting reference for every recurring primary location, showing spatial
  layout, entrances, important furniture or props, lighting direction, time of day,
  palette, and the camera-facing geography needed by the script.

Use the configured image-generation tool selected for the run. Do not silently
switch providers. Keep these images neutral and reusable: they define identity and
space, not a frozen opening shot from one segment.

Persist each image as a visible workspace artifact with a clear semantic title,
such as `character_setting_reference` or `scene_setting_reference`, and record which
characters or locations it covers. Do not begin video generation until all required
references exist and are readable.

These are setting references, not per-shot keyframes. `requires_keyframe: false`
still applies: do not create a first-frame gallery or force every segment to begin
with the same composition.

### 3. Build dense dramatic causality

Every beat must change the situation. Prefer a readable progression such as:

1. immediate conflict, accusation, danger, or impossible situation;
2. the protagonist absorbs pressure while preparing a countermove;
3. evidence, leverage, identity, or intent is revealed in escalating steps;
4. the opponent interrupts, denies, or overcommits;
5. the power relationship reverses through an earned consequence;
6. end on a restrained payoff or a new hook.

This is a decision pattern, not a fixed plot template. Adapt it to suspense,
workplace, family, romance, comedy, fantasy, or another user-selected genre.
Preserve the user's premise and ending rather than forcing a workplace reveal.

### 4. Compile each 15-second generation prompt

Each prompt must be self-sufficient and include:

- model, exact duration, aspect ratio, and resolution;
- character and location anchors relevant to the current segment;
- time-coded actions covering the whole 15 seconds;
- short dialogue lines labeled by speaker and delivery;
- stable shot sizes during spoken lines when lip synchronization matters;
- native ambience and concrete sound cues;
- the closing dramatic beat and the narrative state inherited by the next segment;
- only the negative constraints justified by the brief.

Attach the relevant character and scene setting images to every segment as reusable
identity and environment references. In the prompt, state what each reference owns:
character references control identity and costume; scene references control layout,
lighting, and recurring props. They must not dictate the segment's first-frame
composition or replace its time-coded action plan.

Keep dialogue speakable within its assigned time. Prefer one speaker at a time
and short turns over overlapping speeches. Do not use narration unless requested.

Follow the run's language contract:

- user-visible plans and artifacts use the selected output language;
- dialogue and narration use the selected spoken language;
- provider prompts may remain in Chinese when that helps legacy `seedance2`, but
  they must explicitly state the required spoken language and preserve dialogue
  verbatim;
- words such as “英文短剧”, “English-language video”, or “全片英语” count as an
  explicit English spoken-language request even if the surrounding request is Chinese;
- never translate explicit dialogue into the UI language.

Plan every segment boundary as an intentional editorial cut, reaction cut, location
change, insert, or motivated time jump. Parallel T2V generation does not guarantee
that one segment's first frame is pixel-identical to another segment's last frame.

### 5. Generate all segments in parallel with multi-reference T2V

After the blueprint and all required character and scene references are ready,
schedule every segment as an independent `atomic.video.generate` task. Segment tasks
may run in parallel; none may depend on another segment task. Each depends only on
the approved blueprint and the setting artifacts relevant to that segment.

Use:

- `provider: wavespeed` when provider selection is exposed;
- `model: seedance-2.5` or the capability's exact equivalent;
- `generation_mode: "t2v"`;
- `duration: 15` and `duration_seconds: 15`;
- the run's resolution and aspect ratio;
- native dialogue and ambience.

Pass the relevant setting artifacts through the capability's multi-reference image
field (`reference_images` or its exact supported equivalent). Use reference-driven
text-to-video behavior rather than treating the first character or scene sheet as a
forced first frame.

Every segment must receive all references needed for the identities and location it
contains. Do not attach irrelevant references merely to maximize image count. Bind
each supplied image to its role in the prompt, for example: character identity and
costume, recurring location layout and lighting, or a persistent hero prop.

Do not set `start_image_url`, `end_image_url`, or `generation_mode: "i2v"`. Do not
extract or pass a previous segment's tail frame. Those choices would serialize the
graph and prevent the multi-reference T2V behavior required by this workflow.

Verify the returned media duration before using it. A nominal request is not
proof that the provider returned 15 seconds. If the segment is materially short,
reject it, strengthen the explicit duration contract, and retry that segment once.
One segment's failure must not cause successful sibling segments to be regenerated.

### 6. Assemble the approved segments

Call `media.concat` with the accepted videos in narrative order and
`normalize: true`.

- Use `transition_duration: 0` by default because boundaries were designed as
  intentional cuts. Add a transition only when the script explicitly calls for it.
- Check assembled duration, ordering, audio presence, and each join.
- Persist the assembled MP4 as the visible final workspace artifact; do not return
  only a raw URL in chat.

## Optional captions

Captions are not part of the default generation path. Add them only when the user
asks for subtitles or approves them in the original brief:

1. transcribe the assembled video with `media.transcribe` using the spoken language;
2. create audio-timed subtitles with `subtitle.compose`;
3. validate timestamps, overlaps, and reading speed;
4. burn them with `media.subtitle_burn` using a bottom-safe, language-compatible
   font and a restrained size;
5. persist the captioned MP4 as a new visible artifact without replacing the clean
   master.

## Acceptance gates

Do not advance past a segment when any of these are false:

- all required character and scene setting artifacts exist before segment 1;
- every segment received the relevant setting references;
- every segment used multi-reference T2V rather than I2V or tail-frame chaining;
- its actual duration satisfies the intended 15-second unit;
- required dialogue language matches the run contract;
- the segment performs its assigned dramatic function;
- identity, costume, location, lighting, and recurring props agree with the shared
  references, while boundary frames are evaluated as intentional cuts rather than
  pixel-equal continuations;
- the output contains a usable video artifact and audio when native audio was requested.

Retry a failed generation at most once unless the user explicitly asks for further
attempts. Provider credit, authentication, or unsupported-model errors are blockers,
not creative failures; report them immediately instead of repeatedly resubmitting.
