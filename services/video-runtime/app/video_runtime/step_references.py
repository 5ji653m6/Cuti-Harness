"""Task selectors shared by plan admission and failed-task repair."""

STEP_REFERENCE_PARAMETER_KEYS = (
    "start_image_from_step", "strict_start_frame_from_step",
    "character_reference_from_step", "character_reference_from_steps",
    "scene_reference_from_steps", "product_identity_reference_steps",
    "reference_from_steps", "video_reference_from_steps",
    "audio_reference_from_step", "audio_reference_from_steps",
    "video_step", "video_steps", "source_video_step", "audio_step",
    "transcription_step", "subtitle_step", "analysis_step", "media_step",
)


def remap_step_parameters(parameters: dict, mapping: dict[str, str]) -> dict:
    """Rewrite exact task selectors, preserving ordering and all non-selector data."""
    result = dict(parameters)
    for key in STEP_REFERENCE_PARAMETER_KEYS:
        value = result.get(key)
        if isinstance(value, str):
            result[key] = mapping.get(value, value)
        elif isinstance(value, list):
            result[key] = [mapping.get(item, item) if isinstance(item, str) else item for item in value]
    return result
