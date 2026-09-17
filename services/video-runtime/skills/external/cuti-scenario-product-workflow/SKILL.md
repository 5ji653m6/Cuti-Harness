---
name: cuti-scenario-product-workflow
description: >-
  Create story-driven product advertisements in which a character pursues a goal, encounters a credible problem, and the product naturally changes the outcome so its value is understood through cause and effect. Use for scenario ads, branded micro-dramas, comedic product stories, lifestyle narratives, soft-sell commercials, or when the user explicitly invokes $cuti-scenario-product-workflow. Do not use for primarily visual product showcases, turntables, packshots, or specification-led demonstrations.
metadata:
  kind: workflow
  version: "0.6.0"
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
    title: Cuti Scenario Product Workflow
    mode: cuti_scenario_product_workflow
    planning:
      mode: staged
      checkpoints:
        - id: product_ready
          after_phase: source_analysis
          next_phase: visual_production
          required_artifacts: [product_analysis, source_image]
          resolves: [shots, product_constraints]
          instruction: >-
            Build a causal product story from the real product analysis. Return complete 15-second
            shots and set workflow_parameters.primary_selling_point plus one exact
            workflow_parameters.segment_proofs entry per shot. Keep the final Seedance prompts in
            Chinese with native synchronized audio; do not add TTS, BGM, subtitles, keyframes, or
            Director Skills.
    entrypoints: [text, image]
    dependencies:
      skills: [seedance2]
    parameters:
      workflow_mode: cuti_scenario_product_workflow
      shot_workflow_mode: seedance2_scenario_product_ad
      content_category: scenario_product_ad
      segment_duration_seconds: 15
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

# Cuti Scenario Product Workflow

Create a short product drama whose surface is an engaging human situation and whose causal outcome makes one product benefit believable. The product is a plot device and proof mechanism, not the subject of every shot.

Use the installed legacy `seedance2` Skill for Chinese prompt grammar, multimodal references, native audio, complete 15-second generation units, continuity, and assembly. Do not load unrelated prompt-only helper bundles.

## Creative contract

- Tell one simple story around one clear generated selling point.
- Establish `character goal -> obstacle -> product use -> visible consequence -> payoff`.
- Let viewers infer the benefit from events. Do not make characters recite a feature list.
- Generate useful consumer-facing selling points from the product category, the user's brief, visible design, expected use context, and desired audience. Prefer experiential value over a cautious inventory of visible facts.
- Do not fabricate precise specifications, measurements, prices, certifications, awards, or competitor comparisons unless the user supplied them; this does not prevent the workflow from proposing ordinary category-level benefits for creative advertising.
- The product may appear after the hook. Do not force it into the opening frame or every shot.
- Dialogue must sound like dialogue inside the situation. Use narration only when it improves comprehension or tone.
- Preserve character, location, product identity, narrator voice, and unresolved story state across segments.
- Match user-visible planning output, dialogue, and narration to the user's language. Keep final Seedance prompts in Chinese as required by `seedance2`.
- Show creative deliverables in the workspace; hide raw requests, tool payloads, internal IDs, retries, and orchestration state.

## Workflow

### 1. Product selling points

Generate a short set of candidate selling points from the user's brief, product category, visible design, likely audience, and credible use scenarios. Each selling point should answer:

- what value the audience receives;
- in what situation that value becomes noticeable;
- what visible action or result could demonstrate it on screen.

Choose one primary selling point with the strongest dramatic potential. The output must not include a `Product Truth`, `不可主张项`, unknown-facts, or claim-audit section. Avoid reducing the product to appearance alone when its category supports a credible functional or emotional benefit.

### 2. Dramatic selling point

Turn the chosen selling point into a causal dramatic proposition:

`In situation X, using the product causes observable result Y, which matters to character Z.`

Other candidate selling points may appear as background detail, but they must not compete with the primary proposition. The product's effect must be unmistakable from the event and outcome rather than merely from beauty shots or ownership sentiment.

### 2.5 Story structure selection

Before designing the scenario, read [references/story-structures.md](references/story-structures.md). Select one primary story structure based on the product benefit, emotional tone, audience, duration, and requested genre. Do not combine every framework or expose theory for its own sake.

Persist a short `Story Structure Choice` containing:

- selected structure and why it fits;
- protagonist's concrete goal and stakes;
- the causal event chain;
- planned midpoint choice, reveal, or reversal;
- how the product changes the chain;
- final payoff and opening callback.

Default to the compact causal structure when the user gives no genre preference. Choose another structure only when it produces a clearer or more memorable demonstration.

### 3. Scenario and conflict

Define five compact items:

1. protagonist and immediate goal;
2. specific setting;
3. obstacle related to the chosen benefit;
4. natural reason the product enters the action;
5. emotional, practical, or comedic payoff.

Prefer ordinary recognizable situations with one memorable twist. The conflict must remain understandable without explanatory on-screen text. The product should affect the causal chain rather than arriving only for a final beauty shot.

Build narrative richness from consequential variation: attempts, responses, misunderstandings, discoveries, choices, reversals, product interaction, and downstream consequences. Do not confuse richness with more locations, more characters, more selling points, or decorative detail.

### 4. Story script

Write a complete short-drama arc:

1. **Hook:** an action, question, surprise, or unmet goal;
2. **Escalation:** the obstacle becomes concrete;
3. **Product intervention:** the character uses the product for a believable reason;
4. **Proof:** picture and sound reveal the result;
5. **Payoff:** resolve or reverse the situation;
6. **Brand close:** one restrained product or brand beat.

Treat this as one continuous story, not six mandatory standalone scenes. Combine beats when the requested duration is short. Avoid unrelated subplots, lore, excessive characters, and generic cinematic filler.

Use the available duration to tell more story, not to prolong a single reaction. Build a chain of concrete actions and responses: a character attempts something, another person or the environment answers, the situation changes, and the next choice follows. Prefer meaningful interaction, discovery, reversal, or product use over repeated typing, looking around, frowning, breathing, waiting, walking, or atmospheric noise that leaves the story state unchanged.

For a 60-second ad, plan enough causal development for four distinct 15-second movements. Each movement must add a new obstacle, choice, interaction, demonstration, consequence, or payoff; it must not merely restate the same emotion from another camera distance.

As a planning target for 60 seconds, use roughly `8-12 macro story beats` across the whole arc and `6-10 micro visual beats` inside each 15-second segment. Macro beats change the plot, relationship, knowledge, risk, or decision; micro beats make those changes visible at 1-2 second resolution. Do not invent arbitrary twists merely to reach a count.

### 5. Fifteen-second segment plan

Plan the requested duration as complete 15-second Seedance segments. A 30-second ad has two segments; a 60-second ad has four. Do not turn internal beats into separate 3-second or 6-second provider tasks.

For each segment, specify:

- its story purpose and starting state;
- time-coded visual actions covering the complete `0-15s` timeline;
- concise dialogue or narration with speaker, emotion, and exact time range;
- synchronized ambient sound, product sound, and restrained music;
- ending state that the next segment must inherit.

Design the internal timeline as a dense beat sheet:

- Normally divide all 15 seconds into consecutive `1-2 second` beats. A beat may last up to 3 seconds only when uninterrupted dialogue, a physically legible product operation, or a deliberate payoff genuinely needs it.
- Cover every second exactly once with no gaps or overlapping ranges. Prefer ranges such as `0-2s`, `2-3s`, `3-5s`, not broad blocks such as `0-4s`, `4-9s`, `9-15s`.
- Give every beat an observable verb and a state change. Specify who acts, what changes on screen or in sound, and what new information the audience receives.
- Use reactions as bridges, not filler. A repeated emotion or static pose may occupy at most 2 seconds unless a user explicitly asks for a slow contemplative style.
- Do not spend more than two consecutive beats on the same activity without interruption, escalation, discovery, or response from another character.
- Include at least one meaningful interaction or causal exchange in each 15-second segment. Interaction may be character-to-character, character-to-product, or character-to-environment, but it must change the next action.
- Dialogue timing must fit inside its beat and should overlap purposeful visible action. Do not freeze the scene merely to let a line finish.
- Environmental sound must react to or clarify events; ambience alone does not count as a story beat.

For each beat, record this compact structure:

`time | framing/camera | visible action | interaction or new information | dialogue/audio | resulting story state`

After drafting, run an information-density pass. Merge or replace beats that only repeat mood, camera proximity, ambient sound, or an unchanged action. Across a 60-second story, each of the four segments must have a different dramatic job and together form a continuous escalation and resolution.

Every segment must advance the story. Do not fill a segment with rotation, orbit, macro shots, or packshots when no new event occurs. Reserve enough silent space for reactions and product action; do not fill all 15 seconds with speech.

Prefer one user-visible planning artifact containing Selling Points, Chosen Dramatic Proposition, Scenario, Story Script, and Segment Plan as concise sections.

Include `Story Structure Choice` in that artifact. The story script must make the causal chain readable using connectors such as `because`, `therefore`, `but`, or their natural-language equivalents; a list joined only by `then` is not sufficient.

### 6. Character, scene, and product setting references

After the story script and segment plan succeed, generate three durable setting images with `atomic.image.generate` and `model: gpt-image-2`. They may run in parallel because all three depend on the same completed script artifact. They are multimodal identity references, not mandatory first frames.

#### Character setting reference

- Base the character designs on the actual script: age, identity, face, hairstyle, wardrobe, props, emotional tone, and story world.
- Include every recurring speaking character in one clean multi-character setting sheet with consistent front or three-quarter views and useful full-body proportions.
- Use a neutral, uncluttered layout without readable text, labels, captions, logos, watermarks, storyboards, or shot frames.
- Keep the uploaded product image as the product identity source; do not redesign the product inside the character sheet.
- Persist the image with `artifact_role: character_setting_reference` and a user-readable title.

#### Scene setting reference

- Derive the recurring advertisement location from the approved script, including spatial layout, architecture, surfaces, palette, time of day, lighting direction, weather, and stable environmental props.
- Show one coherent location as a useful wide or three-quarter establishing view. If the story genuinely requires multiple recurring locations, use one clean multi-view environment sheet while keeping each location spatially legible.
- Do not include people, product demonstrations, readable text, captions, logos, watermarks, or storyboard borders.
- Persist the image with `artifact_role: scene_setting_reference` and a user-readable title.

#### Product setting reference

- Use the original uploaded product image as the authoritative identity source. Preserve shape, proportions, color, materials, controls, openings, camera or component placement, and any real visible brand placement; do not redesign or invent accessories.
- Create a clean product identity sheet with useful front, rear, side, and three-quarter views when the source supports them. Keep all views recognizably the same physical item.
- Use a neutral background and consistent studio lighting. Do not include characters, usage scenes, readable added labels, captions, watermarks, or decorative concepts that change the product.
- Persist the image with `artifact_role: product_setting_reference` and a user-readable title.

All three stages must depend on the completed script artifact. Video generation must not begin until `character_setting_reference`, `scene_setting_reference`, and `product_setting_reference` have all succeeded.

### 7. Reference and continuity plan

Use uploaded product images as the original product truth reference, not mandatory first frames. For every video-generation task, attach all of:

- the original uploaded product reference image; and
- the generated `character_setting_reference` artifact;
- the generated `scene_setting_reference` artifact; and
- the generated `product_setting_reference` artifact.

Express all three generated setting images as durable dependencies through `input_artifact_version_ids`, not merely by repeating their URLs in prompt text. The video segments may run in parallel only after all three dependencies succeed. Do not bind any setting image as `first_frame`, `start_frame`, or an equivalent I2V start image unless the user explicitly asks for that exact opening frame.

Maintain a compact continuity record containing:

- character appearance, wardrobe, and voice;
- location, time of day, and lighting;
- product shape, color, material, logo placement, and state;
- story state and screen direction at each segment boundary.

Use the previous segment's true decoded tail frame only when the next segment is a continuous shot. For an editorial cut to another angle or location, keep reference identities but do not force the prior tail frame as the next first frame.

### 8. Seedance prompts and generation

Write exactly one Chinese Seedance prompt for each complete 15-second segment. Each prompt must include:

- an opening declaration that this is a `产品宣传片` rather than a standalone drama scene;
- the exact primary selling point selected upstream, expressed as a concrete audience benefit rather than a vague mood word;
- this segment's `selling-point proof objective`: what product action, perceptible evidence, and changed outcome the shot must show;
- the full `0-15s` sequence with explicit time ranges;
- character goal, action, reaction, and relevant dialogue;
- product interaction and visible causal result;
- framing, camera movement, lighting, location sound, and music direction;
- essential character, product, location, and voice continuity locks;
- an explicit instruction that the character reference controls character identity, the scene reference controls spatial design and lighting, and the product setting plus original upload control product identity;
- native synchronized audio instructions.

Translate the dense beat sheet faithfully into each Seedance prompt. Preserve its `1-2 second` timing and causal order; do not collapse several planned beats back into three broad time blocks. A prompt should describe concrete changing action throughout the segment while remaining one 15-second provider request.

Use this compact header at the beginning of every final provider prompt and preserve it verbatim through Stage splitting:

```text
任务类型：产品宣传片
核心产品卖点：<the same primary selling point used by the whole advertisement>
本片段卖点证明：<product action -> visible/audible evidence -> changed story outcome>
镜头创作要求：剧情、表演、声音和摄影必须共同强化上述卖点；不得把产品降级为无关道具或把片段拍成与产品无关的普通剧情。
```

The planner must also copy the same values into the video task parameters:

- `ad_format: product_commercial`
- `primary_selling_point: <non-empty exact selling point>`
- `segment_proof: <non-empty proof objective for this segment>`

These fields are execution contracts, not hidden creative instructions. The Harness must reject the provider task when any field is absent, when the prompt does not explicitly identify itself as a product advertisement, or when the exact selling point and segment proof were lost during Stage decomposition. Every segment shares the same `primary_selling_point`; `segment_proof` changes per segment according to that segment's role in the proof chain.

Set `duration: 15` and `generate_audio: true`. Generate picture, dialogue or narration, ambience, sound effects, and music together through `api.provider.generate` or `api.ark_protocol.generate`. Do not add a separate TTS stage.

Before submission, reject or revise a segment when:

- its provider Prompt does not explicitly say that it is a product advertisement;
- its provider Prompt omits the exact primary selling point or the segment-specific proof objective;
- the chosen selling point is absent, vague, or not demonstrated by a visible cause-and-effect event;
- the product has no causal effect on the story;
- dialogue merely reads selling points;
- the full timeline is not covered;
- any interval longer than 3 seconds contains no new action, interaction, information, or story-state change;
- two consecutive beats repeat the same action or emotional state without escalation;
- a 15-second segment lacks a meaningful interaction or causal exchange;
- the protagonist remains passive across more than one consecutive macro beat;
- the product appears as an unrelated insert instead of changing what happens next;
- a 60-second plan has no midpoint choice/reveal and no payoff that answers the opening;
- character, product, or voice continuity is unspecified;
- any required character, scene, or product setting reference is absent;
- the plan relies on generated captions or interface text to explain the result.

Generate at most two segments concurrently. Preserve successful outputs and retry only transient provider failures with bounded backoff.

### 9. Assembly

Assemble approved segments in story order with `media.concat` and `normalize: true`. Use clean cuts for normal scene changes. Use a very short overlap only for genuine continuous-shot joins, following `seedance2` continuity guidance. Persist the final MP4 as a visible workspace artifact.

## User-visible outputs

Show only:

1. generated selling points and chosen dramatic proposition;
2. scenario and short-drama script;
3. 15-second segment plan;
4. character, scene, and product setting reference images;
5. final Seedance prompts;
6. generated segments;
7. assembled product advertisement.
