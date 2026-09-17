"""Pure atomic generation boundary.

Atomic capabilities consume a final prompt prepared by the harness and call the
underlying model/provider exactly once.  They deliberately do not invoke a
business agent, inspect conversation history, choose a creative style, or
rewrite the prompt.
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from app.chat.config import get_settings

from .models import AgentRun, ArtifactVersion, Task


_IMAGE_ARTIFACT_TYPES = {
    "image", "source_image", "keyframe", "poster", "character", "character_reference",
    "character_setting_reference", "scene_reference", "scene_setting_reference",
    "product_reference", "product_setting", "product_setting_reference",
    "continuity_frame",
}
_AUDIO_ARTIFACT_TYPES = {
    "audio", "source_audio", "music", "audio_bgm", "audio_narration",
    "audio_segment", "audio_cut",
}
_VIDEO_ARTIFACT_TYPES = {
    "video", "source_video", "video_clip", "video_segment", "final_video",
    "video_assembled", "video_mixed",
}


def _final_prompt(task: Task) -> str:
    prompt = task.parameters.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{task.capability_id} requires parameters.prompt")
    return prompt.strip()


def _selected_urls(selected: list[ArtifactVersion], kinds: set[str]) -> list[str]:
    return [
        item.uri.strip() for item in selected
        if item.type in kinds and isinstance(item.uri, str) and item.uri.strip()
    ]


def _merge_urls(explicit: Any, selected: list[str]) -> list[str]:
    values = explicit if isinstance(explicit, list) else []
    merged = [str(value).strip() for value in values if isinstance(value, str) and value.strip()]
    for value in selected:
        if value not in merged:
            merged.append(value)
    return merged


def _is_mv_workflow(parameters: dict[str, Any] | None) -> bool:
    """MV sends exact http(s) media URLs; Runtime must not invent locators."""
    payload = parameters or {}
    return any(
        str(payload.get(key) or "").strip().casefold() == "mv"
        for key in ("workflow_mode", "activated_workflow")
    )


def _is_http_media_url(value: str) -> bool:
    locator = value.strip()
    return locator.startswith("http://") or locator.startswith("https://")


def _explicit_http_media_urls(values: Any, *, field: str) -> list[str]:
    raw_values = values if isinstance(values, list) else []
    urls: list[str] = []
    for value in raw_values:
        if not isinstance(value, str) or not value.strip():
            continue
        locator = value.strip()
        if not _is_http_media_url(locator):
            raise ValueError(f"MV {field} must be http(s) URLs, not artifact ids or step names")
        if locator not in urls:
            urls.append(locator)
    return urls


def _resolve_artifact_media_values(
    values: Any,
    selected: list[ArtifactVersion],
    kinds: set[str],
) -> list[str]:
    """Resolve planner-supplied artifact IDs into their persisted media URLs.

    Plan normalization may copy ``input_artifact_version_ids`` into an atomic
    capability's ``images``/``videos``/``audios`` field.  Those fields are
    provider-facing media locators, so sending a bare UUID makes the remote
    provider try to decode the UUID text as a file.  Resolve IDs at the atomic
    execution boundary, where the selected artifact records are authoritative.
    """
    raw_values = values if isinstance(values, list) else []
    lookup: dict[str, str] = {}
    for item in selected:
        if item.type not in kinds or not isinstance(item.uri, str) or not item.uri.strip():
            continue
        uri = item.uri.strip()
        lookup[str(item.id)] = uri
        lookup[str(item.artifact_id)] = uri

    resolved: list[str] = []
    for value in raw_values:
        if not isinstance(value, str) or not value.strip():
            continue
        locator = lookup.get(value.strip(), value.strip())
        if locator not in resolved:
            resolved.append(locator)
    return resolved


def _resolve_artifact_media_value(
    value: str | None,
    selected: list[ArtifactVersion],
    kinds: set[str],
) -> str | None:
    if not value:
        return None
    resolved = _resolve_artifact_media_values([value], selected, kinds)
    return resolved[0] if resolved else None


def _first_url(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _selected_continuity_frame(selected: list[ArtifactVersion]) -> str | None:
    """Return an explicitly extracted final frame, never a generic reference.

    ``media.extract_frame(position="last")`` persists its result fields in the
    artifact metadata.  Recognising that provenance here lets the harness keep
    a continuation frame separate from character/scene reference sheets.
    """
    for item in reversed(selected):
        if item.type not in _IMAGE_ARTIFACT_TYPES:
            continue
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        role = str(metadata.get("artifact_role") or "").strip().lower()
        position = str(metadata.get("position") or "").strip().lower()
        is_tail = position == "last" or role in {
            "continuity_tail_frame",
            "tail_frame",
        }
        if is_tail and isinstance(item.uri, str) and item.uri.strip():
            return item.uri.strip()
    return None


def _atomic_text_model_name(params: dict[str, Any], default: str) -> tuple[str, str | None]:
    """Resolve a language model without leaking media-model IDs into OpenAI.

    Workflow planners use ``model`` for image and video capabilities as well,
    so a workflow-wide value such as ``seedance-2.5`` can accidentally land on
    an atomic text task.  Only recognised OpenAI text-model families are valid
    overrides here; everything else deterministically falls back to the
    configured coordinator model.
    """
    requested = _first_url(params, "llm_model", "model")
    if requested:
        normalized = requested.lower()
        if normalized.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4")):
            return requested, None
        return default, requested
    return default, None


def _atomic_input_images(
    run: AgentRun,
    params: dict[str, Any],
    selected: list[ArtifactVersion],
) -> list[str]:
    """Collect image inputs without assigning them any creative meaning.

    The planner historically used several parameter names for the same atomic
    input.  Run uploads are also authoritative inputs, even when the planner did
    not first materialize them as artifacts.
    """
    images: list[str] = []
    for key in (
        "images", "image_urls", "reference_images", "reference_urls",
        "input_image_urls",
    ):
        images = _merge_urls(
            _resolve_artifact_media_values(
                params.get(key), selected, _IMAGE_ARTIFACT_TYPES,
            ),
            images,
        )
    images = _merge_urls(
        _selected_urls(selected, _IMAGE_ARTIFACT_TYPES), images,
    )
    images = _merge_urls(
        [
            item.url for item in run.input_files
            if item.type == "image" and isinstance(item.url, str) and item.url.strip()
        ],
        images,
    )
    return images


def _atomic_image_model_value(run: AgentRun, params: dict[str, Any]) -> str:
    """Resolve one requested image model without silently changing providers."""
    configured = None
    if isinstance(run.user_option, dict):
        configured = run.user_option.get("image_generation_tool")
    value = str(
        params.get("model")
        or params.get("provider")
        or configured
        or "gemini-3.1-flash-image-preview"
    ).strip()
    aliases = {
        "gpt_image_2": "gpt-image-2",
        "gpt-image-2": "gpt-image-2",
        "nano_banana": "gemini-2.5-flash-image",
        "nano-banana": "gemini-2.5-flash-image",
        "nano_banana_2": "gemini-3.1-flash-image-preview",
        "nano-banana-2": "gemini-3.1-flash-image-preview",
        "nano_banana_pro": "gemini-3-pro-image-preview",
        "nano-banana-pro": "gemini-3-pro-image-preview",
    }
    return aliases.get(value.lower(), value)


def _atomic_text_timeout(settings: Any) -> float:
    """Use the leaf-provider budget for durable text artifacts.

    The coordinator timeout is intentionally short for interactive turns, but a
    production blueprint can be several thousand tokens and is an asynchronous
    build task. Applying the interactive timeout here caused deterministic
    failures around 120 seconds.
    """
    interactive = float(settings.DEEP_AGENT_V2_TIMEOUT_SECONDS)
    provider = float(
        getattr(settings, "DEEP_AGENT_V2_PROVIDER_TIMEOUT_SECONDS", interactive)
    )
    return max(interactive, provider)


async def execute_atomic(
    *,
    run: AgentRun,
    task: Task,
    selected: list[ArtifactVersion],
    idempotency_key: str,
    on_remote_submitted: Callable[[str, str], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any]]:
    prompt = _final_prompt(task)
    params = dict(task.parameters)
    title = str(params.get("artifact_title") or task.capability_id).strip()
    operation_id = str(params.get("run_id") or f"atomic:{task.id}")

    if task.capability_id == "atomic.text.generate":
        from app.llm.openai_text import generate_openai_text
        from app.utils.file_utils import inline_local_image_url_for_llm

        settings = get_settings()
        model_name, ignored_model = _atomic_text_model_name(
            params,
            str(settings.DEEP_AGENT_V2_MODEL),
        )
        api_key = (
            settings.DEEP_AGENT_V2_OPENAI_API_KEY
            or os.getenv("OPENAI_API_KEY", "")
        ).strip()
        image_urls = _atomic_input_images(run, params, selected)
        if image_urls:
            inlined_urls = [
                await inline_local_image_url_for_llm(url) for url in image_urls
            ]
            message_content: Any = [
                {"type": "text", "text": prompt},
                *[
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in inlined_urls
                ],
            ]
        else:
            message_content = prompt
        text = await generate_openai_text(
            model=model_name,
            content=message_content,
            api_key=api_key,
            fallback_api_key=settings.OPENAI_API_KEY_FALLBACK,
            base_url=settings.DEEP_AGENT_V2_OPENAI_BASE_URL,
            timeout=_atomic_text_timeout(settings),
        )
        if not text.strip():
            raise RuntimeError("atomic text model returned empty content")
        return operation_id, {
            "title": title, "summary": text, "uri": None,
            "metadata": {
                "text": text,
                "final_prompt": prompt,
                "model": model_name,
                "ignored_non_text_model": ignored_model,
                "atomic": True,
                "input_image_count": len(image_urls),
            },
        }

    if task.capability_id == "atomic.image.generate":
        from app.models.tool_enums import AspectRatio, Resolution, ToolType

        images = _atomic_input_images(run, params, selected)
        model_value = _atomic_image_model_value(run, params)
        aspect_ratio = AspectRatio(str(params.get("aspect_ratio") or "16:9"))
        resolution = Resolution(str(params.get("resolution") or "1080p"))
        model_type = ToolType(model_value)
        if model_type == ToolType.GPT_IMAGE_2:
            from types import SimpleNamespace

            from app.tools.context_schemas import ImageGenerationContext
            from app.tools.image.gpt_image_2 import (
                edit_image_with_wavespeed_gpt_image_2,
                generate_image_with_wavespeed_gpt_image_2_t2i,
            )
            from app.utils.media_egress import resolve_outbound_media_url

            outbound_images = [
                await resolve_outbound_media_url(url) for url in images
            ]
            runtime = SimpleNamespace(
                context=ImageGenerationContext(
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    reference_image_urls=outbound_images or None,
                    model=model_type,
                    language=run.output_language,
                ),
                config=None,
            )
            if outbound_images:
                result = await edit_image_with_wavespeed_gpt_image_2.coroutine(
                    prompt=prompt, images=outbound_images, runtime=runtime,
                )
            else:
                result = await generate_image_with_wavespeed_gpt_image_2_t2i.coroutine(
                    prompt=prompt, runtime=runtime,
                )
        else:
            from app.tools.image.nano_banana import _generate_image_with_nano_banana

            result = await _generate_image_with_nano_banana(
                prompt=prompt,
                reference_image_urls=images or None,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                model=model_type,
            )
        if not result.success or not result.image_url:
            raise RuntimeError(result.raw_error_msg or result.error_msg or "atomic image generation failed")
        metadata = result.model_dump(mode="json")
        metadata.update({"final_prompt": prompt, "atomic": True})
        # Persist planner-assigned semantic roles so downstream stages can
        # select and validate references without inferring meaning from titles.
        artifact_role = str(params.get("artifact_role") or "").strip()
        if artifact_role:
            metadata["artifact_role"] = artifact_role
        return operation_id, {"title": title, "summary": result.message or title, "uri": result.image_url, "metadata": metadata}

    if task.capability_id == "atomic.music.generate":
        from app.tools.music.suno import _generate_music_with_suno_impl

        result = await _generate_music_with_suno_impl(
            prompt=prompt,
            has_lyrics=bool(params.get("has_lyrics", False)),
            auto_lyrics=bool(params.get("auto_lyrics", False)),
            target_duration=params.get("target_duration") or params.get("duration"),
            tags=params.get("tags"),
            vocal_gender=params.get("vocal_gender"),
            mv=str(params.get("mv") or "") or None,
        )
        if not result.success or not result.clips:
            raise RuntimeError(result.error or result.message or "atomic music generation failed")
        clip = result.clips[0]
        metadata = result.model_dump(mode="json")
        metadata.update({"final_prompt": prompt, "atomic": True})
        return str(result.task_id or operation_id), {"title": title, "summary": result.message or title, "uri": clip.audio_url, "metadata": metadata}

    if task.capability_id == "atomic.video.generate":
        from app.integrations.providers.provider_bridge import (
            generate_video,
            normalize_video_frame_inputs,
        )

        profile = dict(params)
        profile.pop("workflow_parameters", None)
        profile["prompt"] = prompt
        profile["idempotency_key"] = idempotency_key
        if _is_mv_workflow(profile):
            # MV only forwards the agent's explicit http(s) lists. Dest
            # continuity aliases and selected-artifact stuffing stay off.
            profile["images"] = _explicit_http_media_urls(profile.get("images"), field="images")
            profile["videos"] = _explicit_http_media_urls(profile.get("videos"), field="videos")
            explicit_audios = profile.get("audios") or profile.get("audio_urls") or []
            if profile.get("audio_url"):
                explicit_audios = [*explicit_audios, profile["audio_url"]]
            profile["audios"] = _explicit_http_media_urls(explicit_audios, field="audios")
        else:
            selected_images = _selected_urls(selected, _IMAGE_ARTIFACT_TYPES)
            start_image = _resolve_artifact_media_value(
                _first_url(
                    profile,
                    "start_image_url",
                    "start_image",
                    "first_frame_url",
                    "first_frame",
                    "continuity_frame_url",
                ),
                selected,
                _IMAGE_ARTIFACT_TYPES,
            ) or _selected_continuity_frame(selected)
            end_image = _resolve_artifact_media_value(
                _first_url(
                    profile,
                    "end_image_url",
                    "end_image",
                    "last_image_url",
                    "last_image",
                ),
                selected,
                _IMAGE_ARTIFACT_TYPES,
            )
            if start_image:
                # An explicit continuity frame has stronger semantics than a
                # reference image.  The provider bridge uses it to select I2V.
                profile["start_image_url"] = start_image
                profile["generation_mode"] = "i2v"
            if end_image:
                profile["end_image_url"] = end_image
            excluded_frames = {url for url in (start_image, end_image) if url}
            profile["images"] = [
                url for url in _merge_urls(
                    _resolve_artifact_media_values(
                        profile.get("images"), selected,
                        _IMAGE_ARTIFACT_TYPES,
                    ),
                    selected_images,
                )
                if url not in excluded_frames
            ]
            profile["videos"] = _merge_urls(
                _resolve_artifact_media_values(
                    profile.get("videos"), selected, _VIDEO_ARTIFACT_TYPES,
                ),
                _selected_urls(selected, _VIDEO_ARTIFACT_TYPES),
            )
            explicit_audios = profile.get("audios") or profile.get("audio_urls") or []
            if profile.get("audio_url"):
                explicit_audios = [*explicit_audios, profile["audio_url"]]
            profile["audios"] = _merge_urls(
                _resolve_artifact_media_values(
                    explicit_audios, selected, _AUDIO_ARTIFACT_TYPES,
                ),
                _selected_urls(selected, _AUDIO_ARTIFACT_TYPES),
            )
        profile = normalize_video_frame_inputs(profile)
        result = await generate_video(profile, on_remote_submitted=on_remote_submitted)
        uri = result.get("video_url") or result.get("uri")
        if not uri:
            raise RuntimeError("atomic video generation completed without video URL")
        result.update({"final_prompt": prompt, "atomic": True})
        return str(result.get("raw_task_id") or operation_id), {"title": title, "summary": title, "uri": uri, "metadata": result}

    raise ValueError(f"unsupported atomic capability: {task.capability_id}")
