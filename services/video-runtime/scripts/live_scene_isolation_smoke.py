"""One-call live smoke for scenario scene-reference prompt isolation.

This intentionally attaches a contaminating Workflow SkillContext to an image
step.  The Cuti provider adapter must keep that context available for audit but
must send only the compiled leaf prompt to GPT Image 2.

Run from ``services/video-runtime`` after loading the normal Cuti provider env:

    PYTHONPATH=.runtime-deps:. python3 scripts/live_scene_isolation_smoke.py

Validate the saved output again without another paid image generation:

    PYTHONPATH=.runtime-deps:. python3 scripts/live_scene_isolation_smoke.py \
      --validate-image ../../.local-media/scene-isolation-live-smoke.png

The script performs one 480p image generation and prints a JSON result without
printing provider credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv


SCENE_PROMPT = (
    "Create exactly one unoccupied environment-only setting reference for the "
    "recurring advertisement location: a modern city apartment living room and "
    "wood dining table at dusk, warm table lamps, rain-softened window light, "
    "stable architectural layout and restrained amber palette. Render a single "
    "coherent wide three-quarter architectural view. Keep the foreground and "
    "midground clear so later action can be staged. Deliver one frame with no "
    "signage, readable text, labels, captions, logos, watermarks, panels, "
    "contact-sheet layout, or storyboard borders."
)


async def main(validate_image: Path | None = None) -> None:
    # Import application modules only after the environment has been loaded.
    # Cuti settings are initialized during import and must not attempt the
    # production account-config backend in this self-hosted smoke test.
    from app.orchestration.skills.models import ResolvedSkillRef, SkillContext
    from app.video_runtime.builtin_plugins.cuti_provider import CutiAtomicProviderPlugin
    from app.video_runtime.builtin_plugins.continuity_validator import _inspect_scene_reference
    from app.video_runtime.models import MediaArtifactVersion
    from app.video_runtime.security import CapabilityExecutionEnvelope, CapabilityGrant

    if validate_image is not None:
        image_uri = (
            "data:image/png;base64,"
            + base64.b64encode(validate_image.read_bytes()).decode("ascii")
        )
        print(json.dumps(
            await _inspect_scene_reference(image_uri),
            ensure_ascii=False,
        ))
        return

    skill_context = SkillContext(
        instructions=(
            "Create a character sheet for Maya, show the uploaded beverage "
            "bottle, and create a product identity sheet."
        ),
        applied_skills=[ResolvedSkillRef(
            skill_id="cuti-scenario-product-workflow",
            version="live-smoke",
            content_hash="deliberately-contaminating-context",
            source="workflow",
        )],
    )
    source = MediaArtifactVersion(
        project_id="scene-isolation-live-smoke",
        artifact_id="scene-setting-reference",
        type="image",
        title="Empty apartment setting",
        metadata={
            "generation_parameters": {
                "prompt": SCENE_PROMPT,
                "model": "gpt-image-2",
                "aspect_ratio": "16:9",
                "resolution": "480p",
                "artifact_role": "scene_setting_reference",
            },
            "skill_context": skill_context.model_dump(mode="json"),
        },
    )
    grant = CapabilityGrant(
        project_id=source.project_id,
        session_id="scene-isolation-live-smoke",
        user_id="local-user",
        plugin_id="cuti.atomic-providers",
        capability="atomic.image.generate",
        allowed_capabilities=["atomic.image.generate"],
        max_cost_usd=1,
        timeout_seconds=300,
        idempotency_key="scene-isolation-live-smoke-v1",
        audit_id="scene-isolation-live-smoke-v1",
        nonce="scene-isolation-live-smoke-v1",
        expires_at=int(time.time()) + 600,
    )
    artifact = await CutiAtomicProviderPlugin().capability_handlers()[
        "atomic.image.generate"
    ](
        CapabilityExecutionEnvelope(grant),
        {"build": {"id": "scene-isolation-live-smoke"}, "source": source.model_dump(mode="json")},
    )
    resolved = dict(artifact.metadata.get("resolved_generation_parameters") or {})
    final_prompt = str(artifact.metadata.get("final_prompt") or "")
    if final_prompt != SCENE_PROMPT:
        raise RuntimeError("leaf provider prompt was changed by Workflow SkillContext")
    if resolved.get("images") or resolved.get("image_urls"):
        raise RuntimeError("scene reference unexpectedly received image dependencies")
    if artifact.metadata.get("skill_prompt_applied") is not False:
        raise RuntimeError("scene reference reports Workflow prompt injection")
    print(json.dumps({
        "artifact_id": artifact.artifact_id,
        "uri": artifact.uri,
        "final_prompt": final_prompt,
        "skill_prompt_applied": artifact.metadata.get("skill_prompt_applied"),
        "input_images": resolved.get("images") or [],
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--validate-image",
        type=Path,
        help="Validate an existing scene image without generating a new one.",
    )
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    os.environ.setdefault("ACCOUNT_BACKEND", "env")
    asyncio.run(main(args.validate_image))
