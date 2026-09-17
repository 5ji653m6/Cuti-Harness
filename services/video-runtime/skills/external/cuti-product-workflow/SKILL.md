---
name: cuti-product-workflow
description: >-
  A simple Cuti workflow for creating narrated commercial product videos from product images or a product brief. Use when the user asks for a product advertisement, launch video, ecommerce promo, commercial product film, or explicitly invokes $cuti-product-workflow. It extracts product truth, defines a concise commercial strategy, creates a 360-degree product setting image with GPT Image 2, plans functional shots and optional effects, designs native synchronized voiceover, generates with the legacy seedance2 Skill using that setting image as a reference, and assembles the final product ad.
metadata:
  kind: workflow
  version: "0.8.0"
  roles: [workflow, stage_supervisor]
  scope:
    type: run
  selectors:
    capabilities:
      - atomic.text.generate
      - atomic.image.generate
      - api.provider.generate
      - api.ark_protocol.generate
      - media.concat
  hooks: [before_stage, after_stage]
  workflow:
    title: Cuti Product Commercial Workflow
    mode: cuti_product_workflow
    planning:
      mode: staged
      checkpoints:
        - id: product_ready
          after_phase: source_analysis
          next_phase: visual_production
          required_artifacts: [product_analysis, source_image]
          resolves: [shots, product_constraints]
          instruction: Plan native-audio advertising shots only from verified product analysis and selected helper Skills.
    entrypoints: [text, image]
    dependencies:
      skills: [seedance2, product-feature-demo-script, product-component-exploded-view, product-voiceover-narration]
    parameters:
      workflow_mode: cuti_product_workflow
      shot_workflow_mode: seedance2_product_ad
      content_category: product_ad
      concept_image_model: gpt-image-2
      segment_duration_seconds: 15
      subordinate_skills: [product-feature-demo-script, product-component-exploded-view, product-voiceover-narration]
      skill_execution_order: [product-feature-demo-script, product-component-exploded-view, product-voiceover-narration]
      shot_script_skills: [product-feature-demo-script]
      effect_skills: [product-component-exploded-view]
      narration_skills: [product-voiceover-narration]
    pipeline:
      - atomic.text.generate
      - atomic.image.generate
      - api.provider.generate
      - api.ark_protocol.generate
      - media.concat
    requires_keyframe: false
    allowed_capabilities:
      - actions.suggest
      - atomic.text.generate
      - atomic.image.generate
      - api.provider.generate
      - api.ark_protocol.generate
      - media.concat
      - media.extract_frame
---

# Cuti Product Workflow

Create a product commercial with a short, understandable workflow. Use the installed legacy `seedance2` Skill for video-prompt grammar, but generate through WaveSpeed Seedance 2.5 (`model: seedance-2.5`). Do not load unrelated prompt-only helper bundles.

## Core rules

- Keep planning and prompts concise. Prefer a few concrete sentences over large schemas.
- Base product facts only on the user's brief and visible references. Mark missing facts as unknown; never invent claims, specifications, accessories, prices, awards, or certifications.
- Do not turn a product ad into a fictional story unless the user explicitly asks for one.
- Do not create Director's Read documents, continuity capsules, scene lineage, `S01/S02` identifiers, or observed-state ledgers.
- Do not visualize workflow internals such as agents, nodes, task lines, graphs, or data streams unless the user explicitly requests that visual concept.
- Generate independent commercial shots by default. Do not chain every previous tail frame into the next shot.
- Treat one complete 15-second Seedance video as the smallest generation unit. Timeline beats inside it are directions within one prompt, not separate provider tasks.
- Treat reference images as product-identity references, not mandatory first frames, unless the user explicitly requests first-frame generation.
- Match user-visible output language to the user's language. Keep Seedance prompts in Chinese as required by the legacy `seedance2` Skill.
- Show important creative results in the workspace. Hide raw model requests, raw tool I/O, internal IDs, retry bookkeeping, and machine-only state.
- Treat effect Skills as an optional creative vocabulary. Evaluate applicability from Product Truth, the selling point, and the chosen style; never force every available effect into the advertisement.
- Use shot-script Skills to turn verified selling points into observable product behavior. Camera rotation, orbit, push-in, floating, and macro photography alone do not count as a functional demonstration.

## Workflow

### 1. Product input

Accept product images, a product brief, or both. If neither contains enough information to identify the product, request only the missing essential input.

### 2. Product truth

Extract a compact factual record:

- shape and geometry;
- material and finish;
- colors;
- logo or label placement;
- verified features and claims;
- visible or supplied accessories;
- unknowns that must not be invented.

This stage internalizes the Product Truth function shown in the workflow design. It does not require or call a separate HiAPIAI Skill.

### 3. Commercial strategy

Define four short items:

- hook;
- desired viewer response;
- primary selling point;
- call to action.

Derive them from Product Truth. This stage internalizes the commercial-strategy function shown in the workflow design; it does not require or call a separate `seedance-ecommerce-ad` Skill.

Classify candidate functional selling points as `verified`, `conceptual`, or `unknown`. Only verified features may become factual demonstrations; unknown features must not enter the shot plan.

### 4. 360-degree product setting image

After Product Truth and Commercial Strategy are complete, generate one product setting sheet before planning video shots. Use `atomic.image.generate` with:

- `model: gpt-image-2`;
- `artifact_role: product_360_reference`;
- `artifact_title: 360-degree product setting image` in the user's language;
- the user's product images as identity references;
- one clean 16:9 setting sheet containing coordinated front, rear, left/right side, and front/rear three-quarter views, plus one restrained detail inset for the primary selling point.

The views must depict the same product identity and provide a practical 360-degree understanding. Keep shape, proportions, color, material, logo placement, and distinctive components consistent across the sheet. Do not invent unseen ports, controls, accessories, internal parts, or product claims. Keep the image prompt short and base it on Product Truth and the verified primary selling point. This is a product reference sheet, not a storyboard or a collection of video keyframes.

Persist the successful setting image and display it in the workspace. Complete this task before creating video-generation tasks.

### 5. Shot design

Plan the whole advertisement as complete 15-second segments. A 30-second advertisement has exactly two segments; a 60-second advertisement has exactly four. Do not plan normal generation as 3-second or 6-second provider clips.

Within each 15-second segment, plan several time-coded beats when useful. For example:

- Segment 1 (15s): 0-3s opening hero move; 3-6s camera or scene change; 6-9s selling-point detail; 9-15s product action and transition.
- Segment 2 (15s): another complete 0-15s timeline that continues the commercial intent.

These beats may use the following shot types as options, not mandatory slots:

- hero product shot;
- macro material shot;
- functional demonstration;
- lifestyle use;
- final packshot.

Apply `product-feature-demo-script` before selecting effects. For each verified primary function, translate the selling point into a visible trigger, product response, and understandable result. In a 30-second advertisement with verified functionality, include at least one genuinely functional 15-second segment. Reject a plan when every segment only rotates, orbits, floats, pushes toward, or shows macro views of the product without a product action or visible outcome.

Evaluate the available effect Skills before finalizing the segments. `product-component-exploded-view` is the first product effect Skill: use it for suitable precision products when a controlled component separation directly supports a verified selling point; skip it when the product, evidence, or visual style does not justify internal structure. Record only a short `use`, `skip`, or `conceptual` decision and rationale in the shot plan. When selected, embed the complete separation, brief suspended-component reveal, selling-point focus, and reassembly as a fast approximately three-second beat inside one 15-second segment; use the rest of that segment for normal commercial cinematography.

Apply `product-voiceover-narration` after the visual and effect decisions. Design one to three concise native voiceover lines per 15-second segment, bind every line to an exact time range and the visible selling-point action, and preserve one compact voice direction across the advertisement. Use the user's language unless requested otherwise. Keep deliberate silent space for product actions, transitions, and the final packshot. If the user explicitly requests music-only output, record a short skip decision instead of forcing narration.

The three subordinate Skills are sequential, not parallel authors. `product-feature-demo-script` owns one shared `segment_script` and its visual causal skeleton. `product-component-exploded-view` may modify only selected visual beats. `product-voiceover-narration` then fills narration into the finalized beats without changing them. A narration conflict returns to the visual script stage as `revision_required`; it does not create another timeline.

Persist the shared structure inside each video task as `_workflow_contract` with `segment_script`, `narration_mode`, one project-level `voice_profile`, and its Harness-generated `voice_profile_hash`. Beats must have stable IDs and continuously cover `0-15s`. Every narrated line must remain inside its referenced visual beat and use a `verified` or explicitly `conceptual` selling-point basis. All narrated segments must carry the exact same voice profile hash.

For each 15-second segment, state its purpose and selling point, then describe framing, camera movement, product action, scene changes, and transition with explicit time ranges covering the complete `0-15s` timeline. Avoid fictional plots and decorative shots that do not support the selling point. Do not turn its internal beats into separate generation tasks.

Prefer one user-visible planning artifact containing Product Truth, Commercial Strategy, and Shot Design as three short sections.

### 6. Video references

Use the user's clearest product image plus the approved 360-degree product setting image as identity references. Do not generate another keyframe or hero reference unless the user explicitly requests it.

Every video-generation task must include the setting image artifact ID in `input_artifact_version_ids`. Merely mentioning the setting image in the prompt or copying its URL into prose does not satisfy this requirement. The Harness will reject a video task that does not carry an image artifact with `artifact_role: product_360_reference`.

Lock only essential identity attributes: silhouette, main color, material, logo placement, and distinctive components. Do not produce a large constraint schema.

### 7. Video prompts

Write exactly one Chinese Seedance prompt per 15-second segment using the legacy `seedance2` guidance. The prompt must describe the complete `0-15s` timeline with time-coded beats such as `0-3s`, `3-6s`, `6-9s`, and `9-15s`; choose different boundaries when appropriate, but leave no part of the 15 seconds unplanned. All camera cuts and scene changes inside that timeline belong to this single prompt and single generation call.

Each segment prompt should compactly cover:

1. framing, camera, and lens feel;
2. lighting and material response;
3. product or environment action;
4. the few identity details that must remain unchanged.
5. native synchronized audio, including exact spoken lines, their time ranges, voice direction, music level, and relevant product sound effects.

For a functional segment, explicitly describe the trigger, response, and visible result in chronological order. Do not rely on captions, generated interface text, charts, or unsupported performance numbers to explain the function.

When an effect Skill was selected in Shot Design, apply its prompt grammar and supervision rules only to the relevant segment. Do not inject its visual behavior into unrelated segments. When it was skipped, keep normal product cinematography and do not mention the effect in the final generation prompt.

Apply `product-voiceover-narration` directly inside every narrated Seedance prompt. Generate picture, narration, music, and sound effects together in the same provider call. Do not call TTS, create a separate voice artifact, or add a post-production dubbing stage. Reject a prompt when a spoken line lacks an exact time range, visible-shot binding, or verified basis; when the reading length cannot fit its interval; or when the prompt does not explicitly request native synchronized audio.

Set `generate_audio: true` for narrated tasks. Store `_workflow_contract` for audit and deterministic validation; the Executor removes this internal field before sending the provider payload. The Harness rejects missing or discontinuous beats, narration outside its beat, unknown narrated claims, missing native audio, a modified voice-profile hash, or different narrator profiles between segments.

Do not include workflow IDs, internal stage names, JSON/YAML, unverifiable claims, or long negative-prompt lists. Persist and display the final shot prompts because they are important creative results.

### 8. Video generation

Use WaveSpeed Seedance 2.5 by default through `api.provider.generate` with `model: seedance-2.5`, following the legacy `seedance2` Skill's prompt grammar. Keep multi-image product and setting inputs in `reference_images`/`images` and use text-to-video mode so they remain references rather than a forced first frame. Use Kling or Veo only when the user requests one or when an enabled provider is deliberately selected as an alternative; do not generate all three by default.

Submit one provider task for each planned segment and set `duration: 15`. Never split a segment into multiple 3-second, 6-second, 8-second, or 10-second generation tasks. Before submission, verify that every task has a 15-second duration and one prompt covering the full `0-15s` timeline; revise an invalid plan instead of submitting it.

For every segment, select the persisted `product_360_reference` artifact as a task input. Treat it as a multi-view identity reference, not as a mandatory first frame. Keep the setting image attached even when the segment also uses other reference images.

Generate at most two 15-second segments concurrently. Preserve successful segments when one fails. Retry transient provider errors with bounded backoff; revise a deterministic failure before retrying.

### 9. Product ad assembly

Assemble the approved 15-second segments in order with `media.concat` and `normalize: true`. Use clean cuts by default and a short transition only when it improves the edit. Do not re-split the segments during assembly. Persist the final MP4 as a visible workspace artifact.

## User-visible outputs

Show only:

1. concise product truth and commercial strategy;
2. GPT Image 2 360-degree product setting image;
3. concise shot plan;
4. final video prompts;
5. generated video shots;
6. final product advertisement.

Keep all other orchestration state internal.
