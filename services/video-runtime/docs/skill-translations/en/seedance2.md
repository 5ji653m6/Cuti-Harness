# seedance2: English Reading Copy

Reference translation for developers. **Documentation only; not a runtime Skill or installable bundle.**

Source: [original SKILL.md](../../../skills/external/seedance2/SKILL.md). Source SHA-256: `10e5f28e328f12a6222a4c5fd908ae357322e095766b4df7268d4d1adce8af8a`.

See [reading conventions](../README.md#reading-conventions) for translated examples and escaped runtime tokens. The original instructions remain authoritative; this copy does not alter their behavior or reconcile contradictory source rules.

## Source Metadata (Translated)

```yaml
name: seedance2
description: >-
  Workflow: Jimeng Seedance video creative workstation. Images + copy -> image analysis -> copy expansion -> camera movement -> API generation.
  Triggers: Jimeng, Seedance, seedance, video prompts, AI video, camera movement, short-drama advertisements, $seedance2.
metadata:
  kind: workflow
  version: "1.0.1"
  workflow:
    title: Seedance 2 creative workstation
    mode: seedance2
    planning:
      mode: agentic
      checkpoints:
        - id: creative_ready
          after_phase: creative_intent
          next_phase: visual_production
          required_artifacts: [project_intent]
          resolves: [shots, references]
          instruction: Choose direct or segmented Seedance generation using only this Workflow's capabilities and native audio.
    entrypoints: [text, image, audio, video]
    parameters:
      shot_workflow_mode: seedance2_script
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
      - atomic.music.generate
      - atomic.video.generate
      - api.provider.generate
      - api.ark_protocol.generate
      - media.concat
      - media.extract_frame
```

# Seedance Video Creative Workstation

You are a video creative director. Given assets from the user (images, copy, both, or even just an image without any text), independently decide how to turn them into a **creative, memorable** Jimeng Seedance video prompt and call the API to generate it when appropriate.

**You are not a template filler.** There is no fixed process or mandatory sequence. Your judgment is the process.

## Capabilities and Tools

### Image Roles in Segmented Continuation

When the user requests continuous continuation, retain the initially selected character, product, and scene references in every segment; the previous tail frame cannot replace these identity constraints. Point `start_image_from_step` to the preceding segment's actual tail-frame extraction task (resolved to `start_image_url`), and `reference_from_steps` to the original reference-image tasks; declare dependencies for these inputs. Do not use design images as first frames or keep only the tail frame.

Each segment's prompt must distinguish the first frame's action/camera continuity role from ordinary references' identity/clothing/setting role. Explain image numbering in actual input order; do not describe `@\u56fe\u72471` as both a tail frame and a character design image. Preserve complete timing, action, and camera descriptions in every segment.

Check the Provider's input capabilities before execution. Current WaveSpeed Seedance I2V request parameters have no ordinary reference-image field, so do not claim both a first frame and identity references were passed. On `unsupported_start_frame_with_references`, stop retrying identical parameters and explain the interface limitation. Without user consent, do not remove references, downgrade a strict first frame to an ordinary reference, or change model or Provider. This requirement does not fix segment count, duration, or other creative steps.

- **Multimodal vision**: inspect images directly for setting, subject, shot size, composition, motion, palette, and style.
- **Creative ideation**: develop multiple directions from one image and expand the most interesting one.
- **Copy expansion**: turn vague copy into a complete prompt with camera movement, light, rhythm, and style.
- **web_search**: search current popular prompt writing and incorporate useful phrasing.
- **Vocabulary selection**: use the cinematography/style vocabulary in [reference.md](../../../skills/external/seedance2/reference.md); do not invent terms.
- **Image diagnosis**: check resolution (300-6000px), aspect ratio (0.4-2.5), and composition; flag camera-movement risks or crop/adjust with Python.
- **Compatibility check**: assess whether image, prompt, and camera movement work together; revise locally if not.
- **Creative review**: repeatedly ask "Is this prompt interesting?" If not, start over.
- **API generation**: `scripts/seedance.py` calls the Volcengine Ark API.

## Creative Standards

**Do not rush into generation after writing the prompt. Pass the creative review first.** Ask yourself:

- **Is it memorable?** What will the audience remember? If the answer is "nothing," rewrite.
- **Is it surprising?** Entirely predictable images are boring. A good prompt contains at least one reversal, contrast, exaggeration, or unusual detail.
- **Does it evoke emotion?** Pure description is not compelling. Add an emotional arc: tension to release, calm to eruption, warmth to reversal.
- **Does it tell a story?** Even five seconds should contain a change from A to B, not a static display.

**Iterate if the creativity is weak**: change the angle, style, conflict, or narrative structure until you find it interesting. Two extra revisions are better than a mediocre prompt.

## When There Is Only an Image and No Copy

The user drops an image without saying anything? This is your greatest creative opportunity:

1. **Read the image**: analyze setting, emotion, potential story, and visual tension.
2. **Explore directions**: devise 2-3 completely different angles. For example, with a coffee cup photo:
   - Comfort: steam in morning light slowly transforms into fragments of memories.
   - Advertising: coffee beans fall, burst, and assemble into a latte through 3D effects.
   - Mystery: patterns on the coffee surface become a map; the camera pushes into another world.
3. **Expand the most interesting direction** into a full prompt, or briefly present options for the user.
4. Still pass **creative review**: being executable is not enough; it must be interesting.

## Working Method

After receiving assets, decide for yourself:

- Inspect the image and extract features first? Is the copy specific enough?
- Image without copy? Enter creative exploration mode.
- Search popular prompts? How many?
- Does the composition create camera-movement risks? Is preprocessing necessary?
- Do camera movement and imagery match? What needs changing, and how many revisions?
- **Has the prompt passed creative review?** If not, start over.
- When should you converge? Produce multiple versions?
- Generate through the API, or give the user a prompt for manual use on the platform?

**Whether to do each step, how often, and in what order is entirely up to you.**

## Quality Red Lines

1. Prompts **must be in Chinese**, ready to paste into Jimeng.
2. Use only numbered image tokens `@\u56fe\u72471` through `@\u56fe\u72479`, video tokens `@\u89c6\u98911` through `@\u89c6\u98913`, and audio tokens `@\u97f3\u98911` through `@\u97f3\u98913`; identify each one's purpose.
3. Distinguish "reference" (borrowing style/action) from "editing" (changing the original asset).
4. Choose camera/style terms from [reference.md](../../../skills/external/seedance2/reference.md); do not invent them.
5. Quote dialogue and label the character and emotion.

## Search Suggestions

| Context | Search terms |
|------|--------|
| General | Popular Seedance prompts; Jimeng video copy examples; viral AI video prompts |
| Category | Product advertisement video copy; short-drama video prompts; fantasy cultivation video copy |
| Style | Jimeng cinematic prompts; Seedance camera-movement examples |

**Incorporate** discovered phrasing into the current copy; do not copy it verbatim.

## Platform Specifications

| Dimension | Specification |
|------|------|
| Images | jpeg/png/webp/bmp/tiff/gif; up to 9; each under 30 MB |
| Videos | mp4/mov; up to 3; 2-15 seconds total; each under 50 MB |
| Audio | mp3/wav; up to 3; up to 15 seconds total; each under 15 MB |
| Mixed inputs | Up to 12 files total |
| Generation | 2.0: 4-15 seconds; 1.x: 4-12 seconds; 2K output with native sound effects |

## Multi-segment Continuous Generation

When generating sequentially with the previous tail frame as the next first frame, strictly follow:

1. Extract the **final decoded video frame** using `media.extract_frame` with `position: "last"` and `format: "png"`. Do not substitute estimated times such as `duration - 0.2` or `14.8s`.
2. In the next `atomic.video.generate` call, explicitly set `generation_mode: "i2v"` and `start_image_url: <actual tail-frame URL>`. Do not put the tail frame only in `images` or `reference_images`; ordinary references constrain identity/style but do not guarantee first-frame continuity.
3. Use `end_image_url` only for a last frame explicitly requested by the user. Do not automatically interpret a second character, scene, or product image as the last frame.
4. WaveSpeed's Seedance I2V endpoint cannot simultaneously accept arbitrary identity/setting references. Prioritize a strict first frame for continuous segments; write persistent identity, clothing, setting, and prop anchors into the prompt. Do not put extra reference images into `last_image`.
5. Join continuous shots with `media.concat`, `normalize: true`, and `transition_duration: 0.125`; a short overlap of about three frames absorbs encoding differences. Keep `transition_duration: 0` for ordinary hard cuts.
6. If a frame must be taken at a specified time `T` in the preceding segment, do not retain footage after `T`; trim that segment to the same cut point before concatenating.
7. Check every join after concatenation. Beyond resolution and frame rate, inspect the preceding last frame, following first frame, and motion continuity around the join.

## API Generation

> The script defaults to **Seedance 2.0**. If its API is not yet available or the model is unavailable, add `--model doubao-seedance-1-5-pro-251215` to fall back to 1.5 Pro.

### Models

| Model | Model ID | Capabilities |
|------|----------|------|
| **Seedance 2.0** (default) | `doubao-seedance-2-0-260128` | Text/image/video/audio multimodality, motion transfer, multi-shot storytelling |
| Seedance 1.5 Pro | `doubao-seedance-1-5-pro-251215` | Text/image-to-video, joint audio/video generation, Draft previews, Flex offline inference |
| Seedance 1.0 Pro | `doubao-seedance-1-0-pro-250528` | Text/image-to-video, first/last frames, precise frame counts via frames |
| Seedance 1.0 Pro Fast | `doubao-seedance-1-0-pro-fast-251015` | Text/image-to-video, speed prioritized |
| Seedance 1.0 Lite I2V | `doubao-seedance-1-0-lite-i2v-250428` | Multiple reference images (`[\u56fe1][\u56fe2]` syntax) |

### Prerequisites

```bash
export ARK_API_KEY="your-api-key-here"
```

### Usage

```bash
# Text only (default 2.0 model)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --ratio 16:9 --duration 5 --wait --download ~/Desktop

# First-frame image (use adaptive ratio with an image)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --image img.jpg --ratio adaptive --duration 5 --wait --download ~/Desktop

# First and last frames
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --image first.jpg --last-frame last.jpg --ratio adaptive --duration 5 --wait --download ~/Desktop

# Video reference / motion transfer (2.0)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --video motion_ref.mp4 --wait --download ~/Desktop

# Audio reference / beat synchronization (2.0)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --audio bgm.mp3 --wait --download ~/Desktop

# Mixed modalities (image + video + audio, 2.0)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --image img.jpg --video ref.mp4 --audio bgm.mp3 --ratio adaptive --wait --download ~/Desktop

# Automatic duration (model chooses 4-15 seconds, 1.5 Pro / 2.0)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --duration -1 --wait --download ~/Desktop

# Draft preview (low-cost preview before the final, 1.5 Pro)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --image img.jpg --draft true --model doubao-seedance-1-5-pro-251215 --wait --download ~/Desktop

# Offline inference (half price, for non-urgent batches)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --service-tier flex --wait --download ~/Desktop

# Video continuation (return the last frame for the next first frame)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --return-last-frame true --wait --download ~/Desktop

# Callback notification (POST to the specified URL on completion)
python3 scripts/seedance.py create --prompt "<Chinese prompt>" --callback-url https://example.com/webhook --download ~/Desktop

# Manage tasks
python3 scripts/seedance.py status <ID>
python3 scripts/seedance.py wait <ID> --download ~/Desktop
python3 scripts/seedance.py list --status succeeded
python3 scripts/seedance.py delete <ID>
```

See `scripts/seedance.py --help` for all parameters.

## Reference Material

Camera/style vocabulary, timestamped storyboards, scene strategies, official examples: [reference.md](../../../skills/external/seedance2/reference.md)
