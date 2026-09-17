"""Resolve authoritative task media inputs before dispatch to any Cuti Provider."""
import re
from app.chat.v2.atomic_executor import (
    _AUDIO_ARTIFACT_TYPES, _IMAGE_ARTIFACT_TYPES, _VIDEO_ARTIFACT_TYPES,
    _explicit_http_media_urls, _is_mv_workflow, _merge_urls,
    _resolve_artifact_media_values, _selected_urls,
)


def ordered_inputs(completed, version_ids):
    """Preserve explicit input order, then append remaining dependency artifacts."""
    by_id = {item.id: item for item in completed.values()}
    missing = [value for value in version_ids if value not in by_id]
    if missing:
        raise ValueError("task input artifacts are unavailable: " + ", ".join(missing))
    result = [by_id[value] for value in dict.fromkeys(version_ids)]
    result.extend(item for item in completed.values() if item.id not in version_ids)
    kinds = _IMAGE_ARTIFACT_TYPES | _AUDIO_ARTIFACT_TYPES | _VIDEO_ARTIFACT_TYPES
    for item in result:
        if item.type in kinds and not (item.uri or "").strip():
            raise ValueError(f"media input has no URI: {item.id}")
    return result


def resolve_media_parameters(parameters, selected, *, validate_prompt_slots=True):
    """Reuse Cuti ID resolution and merging for direct and atomic execution alike."""
    for field, aliases, kinds in (
        ("images", ("images", "image_urls", "reference_images", "reference_urls"), _IMAGE_ARTIFACT_TYPES),
        ("videos", ("videos", "video_urls", "reference_videos"), _VIDEO_ARTIFACT_TYPES),
        ("audios", ("audios", "audio_urls", "reference_audios"), _AUDIO_ARTIFACT_TYPES),
    ):
        values = []
        for alias in aliases:
            raw = parameters.get(alias)
            if raw is not None and (not isinstance(raw, list) or any(not isinstance(v, str) for v in raw)):
                raise ValueError(f"{alias} must be an array of media URIs or artifact IDs")
            if _is_mv_workflow(parameters):
                values = _merge_urls(values, _explicit_http_media_urls(raw, field=field))
            else:
                values = _merge_urls(values, _resolve_artifact_media_values(raw, selected, kinds))
        if not _is_mv_workflow(parameters):
            values = _merge_urls(values, _selected_urls(selected, kinds))
        if values:
            parameters[field] = values
            for alias in aliases:
                if alias in parameters:
                    parameters[alias] = values
    if validate_prompt_slots:
        for pattern, field in ((r"@(?:图片|image)\s*(\d+)", "images"),
                               (r"@(?:视频|video)\s*(\d+)", "videos"),
                               (r"@(?:音频|audio)\s*(\d+)", "audios")):
            for index in re.findall(pattern, str(parameters.get("prompt") or ""), re.IGNORECASE):
                if not 1 <= int(index) <= len(parameters.get(field) or []):
                    raise ValueError(f"prompt references missing {field} slot {index}")
