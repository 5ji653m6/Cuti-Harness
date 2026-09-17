---
name: product-component-exploded-view
description: >-
  Design a controlled exploded-view product effect in which a precision product separates into ordered components, suspends them in space to reveal a selling point, and reassembles cleanly. Use for phones, cameras, watches, headphones, computers, appliances, tools, mechanical devices, and other engineered products when internal structure, materials, modularity, or precision craftsmanship supports the commercial idea. Also use when the user asks for product disassembly, component breakdown, exploded view, floating parts, internal structure, mechanical reveal, or reassembly. Do not apply automatically to every product ad.
metadata:
  kind: effect
  version: "0.3.0"
  roles: [guidance, stage_supervisor]
  scope:
    type: stage
    selectors:
    capabilities:
      - atomic.video.generate
      - api.provider.generate
      - api.ark_protocol.generate
  hooks: [before_stage, after_stage]
  effect:
    category: product_component_visualization
    activation: conditional
---

# Product Component Exploded View

Create a premium commercial effect: intact product, controlled separation, ordered suspended components, selling-point reveal, precise reassembly, and intact hero finish. Treat it as an optional visual technique, not a workflow.

Apply the effect only by modifying the `visual` and `effect` fields of an existing `segment_script` beat selected after the functional narrative is complete. Preserve its `beat_id`, selling-point status, surrounding causal sequence, and total 15-second coverage. Do not create a parallel timeline or write narration. Finish the visual modification before the narration Skill runs.

## Decide whether to use it

Evaluate the product, verified selling point, references, and chosen visual style before adding the effect.

Use it when:

- the product is engineered or mechanically assembled;
- component structure, material layering, compact engineering, repairability, modularity, cooling, optics, battery, acoustics, or craftsmanship supports the selling point;
- the commercial style benefits from precise technical visualization;
- a compact three-second reveal can fit naturally inside one complete 15-second segment.

Skip it when:

- the product is primarily food, liquid, fabric, cosmetics, a living subject, or another object without meaningful precision components;
- the selling point is purely lifestyle, taste, scent, softness, or emotion and internal structure adds no value;
- the requested style is documentary realism and the true internal construction is unknown;
- the effect would distract from the product or repeat another segment without adding information.

When evidence is incomplete, show a restrained conceptual layered construction based only on visible geometry. Do not present invented internals as verified engineering truth. If no credible version is possible, do not use the effect.

Record a short effect decision in the shot plan: `use`, `skip`, or `conceptual`, followed by one sentence of rationale. Do not expose internal routing metadata.

## Embed a fast effect beat in one 15-second segment

Keep the Seedance 2.0 generation task at `duration: 15`, but make the complete disassembly-and-reassembly effect last about three seconds inside that segment. Do not stretch the effect across the full 15 seconds. Use the remaining time for normal hero, material, function, lifestyle, or packshot cinematography.

A default three-second effect beat is:

- first `0.0-0.6s` of the beat: trigger the separation from the intact product;
- next `0.6-1.3s`: rapidly unfold shells, modules, and precision parts in a controlled order;
- next `1.3-2.0s`: hold the ordered suspended view briefly and emphasize one selling-point component;
- next `2.0-2.8s`: rapidly return every component along a coherent path and reassemble;
- final `2.8-3.0s`: settle on the intact product and continue into the next commercial beat.

Place this relative beat at the most useful position in the segment, for example `5-8s` or `9-12s`, and convert the relative timing into absolute `0-15s` prompt timestamps. Keep it between roughly 2.5 and 3.5 seconds by default. Extend it only when the user explicitly requests a slow technical visualization.

The complete 15-second timeline and the compact effect beat belong to one prompt and one generation task, never separate short video tasks.

## Adapt to the product and style

- Choose a mechanically plausible separation axis: thickness layers for a phone, optical axis for a camera or lens, concentric layers for a watch, and housing-to-driver layers for headphones.
- Preserve the product silhouette, exterior colors, finish, logo position, and distinctive controls before and after the effect.
- Keep component order and count visually consistent between separation and reassembly.
- Make separation and reassembly quick and decisive while keeping the short suspended moment readable. Avoid slow drifting parts or long museum-style inspection.
- Match motion and lighting to the commercial direction: clinical precision, luxury restraint, energetic technology, or industrial power. Do not force one universal look.
- Focus on one verified or explicitly conceptual selling point rather than touring every internal part.
- Prefer smooth magnetic or mechanical motion. “Exploded view” means spatial decomposition, not fire, impact, damage, fracture, or debris.

## Prompt requirements

In the final Chinese Seedance prompt, state:

1. the intact product and locked identity attributes;
2. the exact separation direction and ordered component groups;
3. the complete time-coded `0-15s` action, with the exploded-view effect explicitly limited to an approximately three-second interval;
4. the selling-point component and camera emphasis;
5. the reassembly path and final intact hero state;
6. concise failure prevention: no breakage, no random scattering, no missing or duplicated parts, no deformation, and no identity drift.

Do not overload the prompt with a full engineering bill of materials. Name only components supported by the brief or references; otherwise use neutral groups such as shell, structural frame, functional module, internal layer, and rear housing.

## Supervise the result

Accept the segment only when:

- the opening and closing product are recognizably the same object;
- separation reads as deliberate layered assembly rather than destruction;
- suspended parts remain ordered and legible;
- the selected selling point receives clear visual emphasis;
- reassembly completes without missing, duplicated, fused, or malformed parts;
- the complete separation, reveal, and return finishes in about three seconds without looking sluggish;
- the segment remains a product advertisement rather than a technical diagram or repair tutorial.

If it fails, retry by simplifying component count, clarifying one separation axis, reducing simultaneous camera movement, and making the three-second interval more explicit before adding more prompt detail.
