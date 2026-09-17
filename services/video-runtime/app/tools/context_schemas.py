"""
Context schema definitions for image and video generation

Used for the context_schema parameter of create_agent, passed via context=Context(...)
Defined with dataclass, for lightweight runtime context injection.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict

from ..models.tool_enums import AspectRatio, Resolution, ToolType, DefaultValues


@dataclass
class ImageGenerationContext:
    """Image-generation context.

    Used for the context_schema parameter of create_agent, passed via context=ImageGenerationContext(...)
    Accessed in tools via ToolRuntime[ImageGenerationContext] and runtime.context
    """
    aspect_ratio: AspectRatio = field(default=DefaultValues.IMAGE_ASPECT_RATIO)  # aspect ratio
    resolution: Resolution = field(default=DefaultValues.IMAGE_RESOLUTION)  # resolution
    reference_image_urls: Optional[List[str]] = None  # list of reference image URLs (for i2i or style reference)
    reference_image_labels: Optional[List[Dict[str, Any]]] = None  # one-to-one with reference_image_urls: index/name/type_label/description/appearance/style/body_type/role, for the consistency-check prompt
    model: Optional[ToolType] = None  # specific model type (optional), e.g. ToolType.GEMINI_2_5_FLASH_IMAGE
    language: Optional[str] = None  # user language (ISO 639-1), for in-tool i18n text, passed through by runtime
    skip_consistency_check: bool = False  # skip character-consistency checking (during character-image generation the prompt deliberately changes the character, so the check would always fail)


@dataclass
class VideoGenerationContext:
    """Video-generation context.

    Used for the context_schema parameter of create_agent, passed via context=VideoGenerationContext(...)
    Accessed in tools via ToolRuntime[VideoGenerationContext] and runtime.context
    """
    aspect_ratio: AspectRatio = field(default=DefaultValues.VIDEO_ASPECT_RATIO)  # aspect ratio
    resolution: Resolution = field(default=DefaultValues.VIDEO_RESOLUTION)  # resolution
    start_image_url: Optional[str] = None  # first-frame image URL (higher priority than LLM-passed args)
    end_image_url: Optional[str] = None  # end-frame image URL (higher priority than LLM-passed args)
    audio_url: Optional[str] = None  # audio URL (lipsync mode: the audio_url passed to the wan tool)
    reference_images: Optional[List[str]] = None  # list of T2V reference image URLs (user-uploaded/historical, higher priority than LLM-passed args)
    reference_videos: Optional[List[str]] = None  # list of T2V reference video URLs (total duration <= 15s, higher priority than LLM-passed args)
    reference_audios: Optional[List[str]] = None  # list of T2V reference audio URLs (total duration <= 15s, higher priority than LLM-passed args)
    duration: Optional[int] = None  # video duration in seconds (higher priority than LLM-passed args; lipsync mode uses ceil(audio_duration))
    language: Optional[str] = None  # user language (ISO 639-1), for in-tool i18n text, passed through by runtime
    character_ref_image_urls: Optional[List[str]] = None  # list of character reference-image URLs this shot depends on, used only for video consistency checking (not for generation)
    character_ref_labels: Optional[List[Dict[str, Any]]] = None  # one-to-one with character_ref_image_urls: index/name/type_label/description/appearance/style/body_type/role, for the consistency-check prompt
    skip_consistency_check: bool = False  # skip video-consistency checking (the wrapper's built-in check is not run in the regenerate scenario)
    # in-clip dialogue: when there is character dialogue, Seedance I2V passes generate_audio=True and does not strip audio on S3 upload.
    # the dialogue text is written into i2v_prompt by the video-director skill (says: "..." / Character says), not injected in Python.
    generate_audio: bool = False


@dataclass
class SpeechGenerationContext:
    """Speech-generation context.

    Used for the context_schema parameter of create_agent, passed via context=SpeechGenerationContext(...)
    Accessed in tools via ToolRuntime[SpeechGenerationContext] and runtime.context
    """
    target_duration: Optional[float] = None  # shot target duration (seconds), used by the wrapper for +/-0.5s validation and speed retry
    detected_language: Optional[str] = None  # user language (ISO 639-1), for default voice selection
    default_voice_id: Optional[str] = None  # voice inferred from the shot's character; highest priority, overrides the LLM's choice
    speaker_gender: Optional[str] = None  # narrator gender: 'f' female / 'm' male; used to check whether the LLM picked the wrong voice
    shot_number: Optional[int] = None  # shot number (metrics / logging)
