---
name: product-feature-demo-script
description: >-
  Turn verified product features and selling points into visual commercial shot scripts with a clear trigger, product response, and visible user-facing result. Use for product advertisements that need functional demonstrations, interaction, before-and-after change, environmental stress, usage scenarios, or conceptual mechanism visualization instead of repeated rotations, orbit shots, floating packshots, and exterior-only beauty shots. Suitable for phones, cameras, headphones, watches, computers, appliances, tools, cosmetics devices, and other functional products. Never invent unsupported capabilities or performance claims.
metadata:
  kind: shot-script
  version: "0.2.0"
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
  shot_script:
    category: product_feature_demo
    activation: default
---

# Product Feature Demo Script

Convert a selling point into an observable event. Make the viewer understand what the product does, how it responds, and why the result matters. Do not use camera movement as a substitute for product behavior.

Own the visual narrative skeleton, not the spoken copy. Produce the shared `segment_script` first. Let effect Skills modify only selected visual beats, then let `product-voiceover-narration` fill narration into those finalized beats. Do not write final voiceover lines, select a narrator, or alter audio direction.

## Produce the shared segment script

Create one structure per complete 15-second segment:

```yaml
segment_script:
  segment_id: segment-01
  duration_seconds: 15
  purpose: concise commercial purpose
  beats:
    - beat_id: segment-01-beat-01
      start_seconds: 0
      end_seconds: 3
      narrative_role: hook
      selling_point_status: verified
      visual:
        scene: visible situation
        action: visible trigger or product action
      narration: null
```

Make beat IDs stable and cover `0-15` continuously without gaps or overlaps. Use `selling_point_status: verified`, `conceptual`, or `unknown`. Keep `narration: null` at this stage; the narration Skill fills it later without redesigning the visual timeline.

## Establish feature evidence

Classify each proposed feature before scripting it:

- `verified`: explicitly supplied by the user or reliably visible in the reference;
- `conceptual`: a visual metaphor requested by the user that does not assert measured performance;
- `unknown`: unsupported and forbidden from demonstration or claim.

Use only verified features for factual demonstrations. Label conceptual mechanism views as conceptual in the planning artifact, not as engineering truth. If no feature is verified, demonstrate visible use, material response, ergonomics, assembly, controls, or accessories without inventing a capability.

## Choose one demonstration pattern

Select the simplest pattern that makes the selling point visible:

1. **Direct function:** a user or object triggers the product and the function visibly operates.
2. **Trigger-response-result:** show the initiating action, product response, and observable outcome as one causal chain.
3. **Before-after:** show a credible state change without unsupported competitor comparisons or fabricated metrics.
4. **Environmental challenge:** place a verified function in a relevant situation such as low light, motion, noise, rain, heat, or workload.
5. **Conceptual mechanism:** visualize sound, light, heat, airflow, energy, or internal motion only when a literal demonstration is impractical and the representation is clearly conceptual.

Do not repeat the same pattern in every segment when several features are available.

## Write one complete 15-second segment

Keep every provider task at `duration: 15`. A useful functional segment is:

- `0-3s`: establish the user need, situation, or challenge;
- `3-6s`: show a clear user, object, or environmental trigger;
- `6-10s`: show the product responding through visible action or a concise conceptual mechanism;
- `10-13s`: reveal a concrete result the viewer can understand without explanatory text;
- `13-15s`: return to the intact product and connect the result to a hero or packshot finish.

Adapt the boundaries to the feature, but preserve causal order. Internal beats remain one prompt and one 15-second generation task.

For a 30-second advertisement with verified functionality, use at least one genuinely functional 15-second segment. Other segments may establish identity, material, lifestyle, or final brand value. Do not require every segment to contain a different feature.

## Make actions specific

State:

- who or what activates the product;
- the exact physical or interface action;
- the product's visible response;
- the resulting change in the subject, environment, captured media, or user experience;
- the camera position needed to make the causal link readable.

Prefer hands, silhouettes, environment interaction, objects, or product mechanisms when no actor reference is available. Avoid unreadable screen UI, generated text, charts, numerical overlays, and unsupported benchmark imagery.

## Coordinate with effect Skills

Decide the functional script before choosing a visual effect. Use an effect only when it clarifies the response or result. For example, use a compact exploded-view beat to reveal a verified or conceptual cooling structure, acoustic module, optical path, or battery layout; do not add disassembly merely because the product is mechanical.

An effect Skill may update the `visual` and `effect` fields of an existing beat. It must preserve the beat ID, segment duration, commercial purpose, and verified selling-point basis. After effects are finalized, freeze the visual beats before narration begins.

## Reject empty beauty-shot plans

Revise the plan before generation when:

- all segments consist only of rotation, orbit, push-in, macro, floating, or static packshots;
- a claimed feature has no visible trigger or result;
- camera movement is the only action;
- the same exterior view is repeated from several directions without new information;
- the script depends on text to explain what the image does not show;
- the prompt invents a feature, metric, comparison, certification, or internal mechanism.

## Supervise the result

Accept a functional segment only when the trigger, response, and result remain understandable in sequence; the product identity stays consistent; the action supports one primary selling point; and the segment still reads as a commercial rather than a tutorial.

If the result becomes vague, simplify to one feature, one trigger, one visible response, and one result before increasing prompt detail.
