from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..models import MediaArtifactVersion, MediaCapabilityContract, MediaCapabilityInputContract
from ..plugins import BaseVideoPlugin
from ..security import CapabilityExecutionEnvelope


AtomicExecutor = Callable[..., Awaitable[tuple[str, dict[str, Any]]]]


class CutiAtomicProviderPlugin(BaseVideoPlugin):
    """Transition adapter that reuses Cuti's proven atomic provider implementations."""

    CAPABILITIES = (
        "atomic.text.generate",
        "atomic.image.generate",
        "atomic.music.generate",
        "atomic.video.generate",
        "suno.generate",
        "api.provider.generate",
    )

    def __init__(self, executor: AtomicExecutor | None = None) -> None:
        self._executor = executor

    def capability_handlers(self):
        return {capability: self._generate for capability in self.CAPABILITIES}

    def plan_patch_capability_contracts(self):
        """Expose generation through the same project-owned inputs as media edits."""
        from app.capabilities.manifests.platform import platform_capabilities

        music_schema = next(
            item.parameters_schema
            for item in platform_capabilities()
            if item.id == "atomic.music.generate"
        )
        music = MediaCapabilityContract(
            capability="atomic.music.generate",
            description=(
                "Generate one standalone music artifact from the user's explicit music request. "
                "This does not imply video generation."
            ),
            output_artifact_type="music",
            estimated_cost=0.1,
            parameters_schema=dict(music_schema),
        )
        image = MediaCapabilityContract(
            capability="atomic.image.generate",
            description=(
                "Generate one image in the current project from an explicit prompt, with optional "
                "project-owned reference images."
            ),
            inputs=[MediaCapabilityInputContract(
                role="images", artifact_types=["image"], parameter="reference_from_steps",
                required=False, multiple=True,
            )],
            output_artifact_type="image",
            estimated_cost=0.1,
        )
        videos = [MediaCapabilityContract(
            capability=capability,
            description="Generate an additional video in the current project; chain its output into media.concat only when the request requires assembly. Specify provider, model and prompt explicitly.",
            inputs=[MediaCapabilityInputContract(
                role="images", artifact_types=["image"], parameter="reference_from_steps",
                required=False, multiple=True,
            ), MediaCapabilityInputContract(
                role="audio", artifact_types=["audio"], parameter="audio_reference_from_steps",
                required=False, multiple=True,
            )],
            output_artifact_type="video",
            estimated_cost=0.5,
        ) for capability in ("atomic.video.generate", "api.provider.generate")]
        return [music, image, *videos]

    async def _generate(
        self,
        envelope: CapabilityExecutionEnvelope,
        payload: dict[str, Any],
    ) -> MediaArtifactVersion:
        from app.chat.v2.models import AgentRun, ArtifactVersion, Task
        from app.orchestration.skills.models import SkillContext

        planned = payload.get("step")
        if planned is not None:
            step = dict(planned)
            source = MediaArtifactVersion(
                artifact_id=str(step.get("output_artifact_id") or ""),
                project_id=envelope.grant.project_id,
                type=str(step.get("output_artifact_type") or "generated_media"),
                title=str((step.get("parameters") or {}).get("title") or step.get("step_id") or "Media"),
                summary=str((step.get("parameters") or {}).get("prompt") or ""),
                metadata={
                    "generation_parameters": dict(step.get("parameters") or {}),
                    "rebuild_capability": envelope.grant.capability,
                    "plan_step_id": step.get("step_id"),
                    "language_contract": step.get("language_contract"),
                },
            )
            completed_payload = payload.get("completed_artifacts", {})
            raw_skill_context = step.get("skill_context")
        else:
            source = MediaArtifactVersion.model_validate(payload["source"])
            completed_payload = payload.get("completed_replacements", {})
            raw_skill_context = source.metadata.get("skill_context")
        skill_context = (
            SkillContext.model_validate(raw_skill_context)
            if raw_skill_context
            else None
        )
        metadata = dict(source.metadata)
        parameters = dict(metadata.get("generation_parameters") or {})
        parameters.update(metadata.get("rebuild_parameters") or {})
        completed_by_step = {
            key: MediaArtifactVersion.model_validate(value)
            for key, value in completed_payload.items()
        }
        from app.chat.v2.atomic_executor import _is_mv_workflow
        if _is_mv_workflow(parameters):
            for key in (
                "start_image_from_step",
                "strict_start_frame_from_step",
                "character_reference_from_step",
                "character_reference_from_steps",
                "reference_from_steps",
                "video_reference_from_steps",
                "audio_reference_from_steps",
                "audio_reference_from_step",
                "audio_segment_index",
            ):
                parameters.pop(key, None)
        else:
            start_step = parameters.pop("start_image_from_step", None)
            strict_start_step = parameters.pop("strict_start_frame_from_step", None)
            character_step = parameters.pop("character_reference_from_step", None)
            character_steps = parameters.pop("character_reference_from_steps", None) or []
            reference_steps = parameters.pop("reference_from_steps", None) or []
            video_reference_steps = parameters.pop("video_reference_from_steps", None) or []
            audio_reference_steps = parameters.pop("audio_reference_from_steps", None) or []
            audio_reference_step = parameters.pop("audio_reference_from_step", None)
            audio_segment_index = parameters.pop("audio_segment_index", None)
            required_steps = [start_step, strict_start_step, character_step, audio_reference_step,
                              *character_steps, *reference_steps, *video_reference_steps, *audio_reference_steps]
            for required in required_steps:
                if required and (str(required) not in completed_by_step or not completed_by_step[str(required)].uri):
                    raise ValueError(f"required media dependency is unavailable: {required}")
            start_artifact = completed_by_step.get(str(start_step or strict_start_step or ""))
            if start_artifact and start_artifact.uri:
                parameters.setdefault("start_image_url", start_artifact.uri)
                parameters.setdefault("image_url", start_artifact.uri)
            character_artifact = completed_by_step.get(str(character_step or ""))
            if character_artifact and character_artifact.uri:
                parameters.setdefault("images", [character_artifact.uri])
                parameters.setdefault("image_urls", [character_artifact.uri])
            character_urls = [
                completed_by_step[str(step)].uri
                for step in character_steps
                if completed_by_step.get(str(step)) and completed_by_step[str(step)].uri
            ]
            if character_urls:
                parameters.setdefault("images", character_urls)
                parameters.setdefault("image_urls", character_urls)
            reference_urls = [
                completed_by_step[str(step)].uri
                for step in reference_steps
                if completed_by_step.get(str(step)) and completed_by_step[str(step)].uri
            ]
            if reference_urls:
                parameters.setdefault("images", reference_urls)
                parameters.setdefault("reference_urls", reference_urls)
                parameters.setdefault("image_urls", reference_urls)
            video_reference_urls = [
                completed_by_step[str(step)].uri
                for step in video_reference_steps
                if completed_by_step.get(str(step)) and completed_by_step[str(step)].uri
            ]
            if video_reference_urls:
                parameters.setdefault("videos", video_reference_urls)
                parameters.setdefault("reference_videos", video_reference_urls)
                parameters.setdefault("video_urls", video_reference_urls)
            audio_reference_urls = [
                completed_by_step[str(step)].uri
                for step in audio_reference_steps
                if completed_by_step.get(str(step)) and completed_by_step[str(step)].uri
            ]
            if audio_reference_urls:
                parameters.setdefault("audios", audio_reference_urls)
                parameters.setdefault("reference_audios", audio_reference_urls)
                parameters.setdefault("audio_urls", audio_reference_urls)
            audio_reference = completed_by_step.get(str(audio_reference_step or ""))
            if audio_reference:
                audio_url = audio_reference.uri
                if audio_segment_index is not None:
                    segments = audio_reference.metadata.get("segments") or []
                    index = int(audio_segment_index)
                    if index < 0 or index >= len(segments):
                        raise ValueError(f"audio cut has no segment {index}")
                    segment = segments[index] if isinstance(segments[index], dict) else {}
                    audio_url = segment.get("audio_url") or audio_url
                if audio_url:
                    parameters.setdefault("audios", [audio_url])
                    parameters.setdefault("audio_url", audio_url)
                    parameters.setdefault("audio_urls", [audio_url])
        explicit_prompt = parameters.get("prompt")
        if not explicit_prompt:
            objective = str(parameters.get("objective") or "").strip()
            instruction = str(parameters.get("instruction") or "").strip()
            explicit_prompt = "\n\n".join(
                value for value in (objective, instruction) if value
            )
        prompt = str(
            explicit_prompt
            or metadata.get("rebuild_prompt")
            or metadata.get("prompt")
            or source.summary
            or source.title
        ).strip()
        if not prompt:
            raise ValueError("Cuti provider rebuild requires a persisted prompt")
        # Match Cuti's atomic execution boundary: Workflow/Director instructions
        # may guide an LLM planning/text stage, but a leaf media provider must
        # consume the already-compiled prompt exactly as written.  Appending an
        # entire Workflow SKILL to an image/video prompt makes the provider try
        # to render every workflow section (for example character + scene +
        # product sheets in one image) instead of the requested artifact.
        skill_prompt_applied = (
            skill_context is not None
            and envelope.grant.capability == "atomic.text.generate"
        )
        if skill_prompt_applied:
            prompt = skill_context.apply_to(prompt)
        parameters["prompt"] = prompt
        parameters.setdefault("artifact_title", source.title or source.type)
        # Generated media is a reusable canonical Artifact, not a presentation
        # derivative.  Keep it clean so tail frames, retries and PlanPatches do
        # not feed a baked watermark back into image/video generation.
        if envelope.grant.capability in {
            "atomic.image.generate", "atomic.video.generate", "api.provider.generate",
        }:
            parameters["watermark"] = False

        from .media_inputs import ordered_inputs, resolve_media_parameters
        input_ids = (planned or {}).get("input_artifact_version_ids", [])
        selected = ordered_inputs(completed_by_step, input_ids)
        if any(item.project_id != envelope.grant.project_id for item in selected):
            raise PermissionError("input artifact does not belong to this project")
        # The output under construction is not an input image/video. Rebuilds
        # retain the previous source as a fallback after explicit dependencies.
        if planned is None:
            selected.append(source)
        legacy_artifacts = [ArtifactVersion(
            id=item.id,
            artifact_id=item.artifact_id,
            project_id=item.project_id,
            type=item.type,
            version=item.version,
            status=item.status,
            produced_by_task_id=f"video-build:{payload['build']['id']}",
            title=item.title,
            summary=item.summary,
            uri=item.uri,
            metadata=item.metadata,
            created_at=item.created_at,
        ) for item in selected]
        # A text blueprint may document the slot syntax consumed by a future
        # media task. Only leaf media providers require those slots now.
        resolve_media_parameters(
            parameters,
            legacy_artifacts,
            validate_prompt_slots=envelope.grant.capability != "atomic.text.generate",
        )
        if envelope.grant.capability in {
            "atomic.video.generate", "api.provider.generate",
        }:
            from app.integrations.providers.provider_bridge import (
                normalize_video_frame_inputs,
            )

            parameters = normalize_video_frame_inputs(parameters)
        if (
            envelope.grant.capability in {
                "atomic.video.generate", "api.provider.generate",
            }
            and str(parameters.get("continuity_mode") or "").casefold()
            == "shared_reference_images"
            and not any(
                parameters.get(key)
                for key in (
                    "images", "image_urls", "reference_images", "reference_urls",
                    "input_image_urls", "start_image_url", "image_url",
                    "first_frame_url", "continuity_frame_url",
                )
            )
        ):
            raise ValueError(
                "shared_reference_images requires at least one resolved image URI "
                "before video provider dispatch"
            )
        if envelope.grant.capability == "api.provider.generate":
            from app.integrations.providers.provider_bridge import normalize_video_profile

            parameters = normalize_video_profile(parameters)
        raw_language_contract = metadata.get("language_contract")
        language_contract = (
            raw_language_contract if isinstance(raw_language_contract, dict) else {}
        )
        run = AgentRun(
            id=f"video-build:{payload['build']['id']}",
            thread_id=envelope.grant.session_id,
            project_id=envelope.grant.project_id,
            user_id=envelope.grant.user_id,
            objective=prompt,
            idempotency_key=envelope.grant.idempotency_key,
            output_language=(
                "zh"
                if str(language_contract.get("content_language") or "").lower().startswith("zh")
                else "en"
            ),
        )
        task = Task(
            run_id=run.id,
            revision=0,
            client_key=str(metadata.get("plan_step_id") or source.id),
            capability_id=envelope.grant.capability,
            objective=prompt,
            input_artifact_version_ids=[item.id for item in legacy_artifacts],
            parameters=parameters,
            resolved_skills=(
                list(skill_context.applied_skills) if skill_context is not None else []
            ),
            skill_context=skill_context,
        )
        capability = envelope.grant.capability
        if capability == "suno.generate":
            from app.integrations.providers.suno_bridge import generate_suno_native

            profile = dict(parameters)
            profile.pop("workflow_parameters", None)
            generated = await generate_suno_native(profile)
            remote_operation_id = str(generated.get("clip_id") or envelope.grant.idempotency_key)
        elif capability == "api.provider.generate":
            from app.integrations.providers.provider_bridge import generate_video

            profile = dict(parameters)
            profile.pop("workflow_parameters", None)
            profile["idempotency_key"] = envelope.grant.idempotency_key
            generated = await generate_video(
                profile, on_remote_submitted=envelope.report_remote_operation,
            )
            if not generated.get("uri"):
                generated["uri"] = generated.get("video_url")
            remote_operation_id = str(
                generated.get("raw_task_id") or envelope.grant.idempotency_key
            )
        else:
            executor = self._executor
            if executor is None:
                from app.chat.v2.atomic_executor import execute_atomic
                executor = execute_atomic
            remote_operation_id, generated = await executor(
                run=run,
                task=task,
                selected=legacy_artifacts,
                idempotency_key=envelope.grant.idempotency_key,
                on_remote_submitted=envelope.report_remote_operation,
            )
        generated_metadata = {
            **metadata,
            **dict(generated.get("metadata") or {}),
            **{
                key: generated[key]
                for key in ("provider_used", "model", "model_family", "generation_mode")
                if generated.get(key) is not None
            },
            "rebuild_capability": envelope.grant.capability,
            # Keep the concrete URLs resolved from BuildStep dependencies for
            # post-generation identity/continuity validators. The Runtime also
            # preserves the immutable, unresolved plan parameters separately.
            "resolved_generation_parameters": dict(parameters),
            "resolved_input_artifacts": [
                {"version_id": item.id, "type": item.type, "uri": item.uri}
                for item in selected if item.uri
            ],
            "skill_prompt_applied": skill_prompt_applied,
            "watermark_policy": "clean_canonical",
        }
        public_uri = generated.get("uri")
        if (
            envelope.grant.capability in {
                "atomic.video.generate", "api.provider.generate",
            }
            and public_uri
        ):
            from app.video_runtime.watermark import publish_public_watermark

            canonical_uri = str(public_uri)
            public_uri = await publish_public_watermark(
                canonical_uri,
                generation_id=f"video-build-{payload['build']['id']}",
            )
            generated_metadata["canonical_uri"] = canonical_uri
            generated_metadata["watermark_policy"] = "public_overlay"
        digest_payload = json.dumps(
            {"uri": public_uri, "metadata": generated_metadata},
            sort_keys=True,
            default=str,
        ).encode()
        return MediaArtifactVersion(
            artifact_id=source.artifact_id,
            project_id=source.project_id,
            type=source.type,
            version=source.version + 1,
            uri=public_uri,
            title=str(generated.get("title") or source.title),
            summary=str(generated.get("summary") or source.summary),
            content_digest=hashlib.sha256(digest_payload).hexdigest(),
            generation_spec_digest=hashlib.sha256(
                json.dumps(parameters, sort_keys=True, default=str).encode(),
            ).hexdigest(),
            provider_id=str(generated_metadata.get("provider_used") or "cuti"),
            provider_version=str(generated_metadata.get("model") or "legacy-atomic"),
            plugin_id="cuti.atomic-providers",
            plugin_version="1.0.0",
            provenance={
                "source_artifact_version_id": source.id if planned is None else None,
                "remote_operation_id": remote_operation_id,
                "idempotency_key": envelope.grant.idempotency_key,
                "skills": (
                    [
                        item.model_dump(mode="json")
                        for item in skill_context.applied_skills
                    ]
                    if skill_context is not None
                    else []
                ),
            },
            metadata=generated_metadata,
        )
