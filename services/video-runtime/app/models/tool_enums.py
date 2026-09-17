"""
Unified enum definitions for tools
"""
from enum import Enum
from typing import Any, Dict, Optional, Tuple


# ==================== Tool modes ====================

class ToolMode(str, Enum):
    """Tool generation modes."""
    # Image modes
    T2I = "t2i"  # Text-to-Image
    I2I = "i2i"  # Image-to-Image

    # Video modes
    T2V = "t2v"  # Text-to-Video
    I2V = "i2v"  # Image-to-Video

    # Generic
    ALL = "all"  # all modes


# ==================== LLM model enum ====================

class LLMModel(str, Enum):
    """LLM model enum (used for cost calculation)."""
    # OpenAI models
    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_5_NANO = "gpt-5-nano"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_4_MINI = "gpt-5.4-mini"
    GPT_5_4_NANO = "gpt-5.4-nano"
    GPT_5_6_SOL = "gpt-5.6-sol"
    GPT_5_6_TERRA = "gpt-5.6-terra"
    GPT_5_6_LUNA = "gpt-5.6-luna"

    # Google Gemini models
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_3_PRO_PREVIEW = "gemini-3-pro-preview"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"
    GEMINI_2_0_FLASH = "gemini-2.0-flash"


# ==================== Tool types (down to specific model level) ====================

class ToolType(str, Enum):
    """Tool type enum (down to specific model level).

    ToolProvider + ToolType uniquely identifies a specific API call.
    Each enum value maps to a specific model name.
    """
    # ==================== Image-generation tools ====================
    GEMINI_2_5_FLASH = "gemini-2.5-flash"

    # Nano Banana (Google Gemini, via WaveSpeed)
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"
    GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image-preview"
    GEMINI_3_1_FLASH_IMAGE_PREVIEW = "gemini-3.1-flash-image-preview"  # Nano Banana 2, cheaper Pro

    # Seedream (ByteDance, via WaveSpeed)
    SEEDREAM_V4_5 = "seedream-v4.5"

    # OpenAI GPT Image 2 (via WaveSpeed openai/gpt-image-2)
    GPT_IMAGE_2 = "gpt-image-2"

    # ==================== Video-generation tools ====================
    # Seedance (ByteDance, via WaveSpeed)
    SEEDANCE_V1_PRO_FAST = "seedance-v1-pro-fast"
    SEEDANCE_V1_5_PRO_FAST = "seedance-v1.5-pro-fast"  # image-to-video-fast, 720p/1080p, generate_audio defaults to False
    SEEDANCE_2_I2V = "seedance-2.0-i2v"  # image-to-video，480p/720p/1080p，4–15s，last_image，generate_audio=False
    SEEDANCE_2_I2V_TURBO = "seedance-2.0-i2v-turbo"  # image-to-video-turbo，720p/1080p，4–15s，last_image，generate_audio=False
    SEEDANCE_2_FAST_I2V = "seedance-2.0-fast-i2v"  # image-to-video，480p/720p/1080p，4–15s，last_image，generate_audio=False
    SEEDANCE_2_FAST_I2V_TURBO = "seedance-2.0-fast-i2v-turbo"  # image-to-video-turbo (fast)，720p/1080p，4–15s，last_image，generate_audio=False
    SEEDANCE_2_T2V = "seedance-2.0-t2v"  # text-to-video, 480p/720p/1080p, 4-15s, generate_audio defaults to True, supports reference_images/videos/audios
    SEEDANCE_2_FAST_T2V = "seedance-2.0-fast-t2v"  # fast text-to-video, 480p/720p/1080p, 4-15s, generate_audio defaults to True, supports reference_images/videos/audios, speed-optimized and cheaper
    SEEDANCE_2_T2V_TURBO = "seedance-2.0-t2v-turbo"  # text-to-video-turbo, 720p/1080p only (480p->720p), 4-15s, generate_audio defaults to True, supports reference_images/videos/audios, HD turbo speedup
    SEEDANCE_2_FAST_T2V_TURBO = "seedance-2.0-fast-t2v-turbo"  # fast text-to-video-turbo, 720p/1080p only (480p->720p), 4-15s, generate_audio defaults to True, supports reference_images/videos/audios, fastest and cheapest HD turbo
    SEEDANCE_V1_LITE_I2V_480P = "seedance-v1-lite-i2v-480p"
    SEEDANCE_V1_LITE_I2V_720P = "seedance-v1-lite-i2v-720p"
    SEEDANCE_V1_LITE_I2V_1080P = "seedance-v1-lite-i2v-1080p"

    # Wan 2.5 (Alibaba, via WaveSpeed) - single model, resolution is a parameter, optional audio, no end image
    WAN_2_5_I2V = "wan-2.5-i2v"
    # Wan 2.6 Flash (Alibaba, via WaveSpeed) - image-to-video-flash, 720p/1080p, duration 3-15, enable_audio affects billing
    WAN_2_6_FLASH_I2V = "wan-2.6-flash-i2v"
    # LTX 2.3 Lipsync (WaveSpeed) - main-flow lip-sync, audio+image(+prompt)->video, 480p/720p/1080p
    LTX_2_3_LIPSYNC = "wavespeed-ai/ltx-2.3/lipsync"
    # Kling V2 AI Avatar Pro (Kwaivgi, WaveSpeed) - audio+image(+prompt)->talking-head; billed by audio duration, min 5s
    KLING_V2_AI_AVATAR_PRO = "kwaivgi/kling-v2-ai-avatar-pro"
    # WAN 2.2 Speech-to-Video (WaveSpeed) - audio+image(+prompt)->video; official resolution 480p/720p, up to ~10min
    WAN_2_2_SPEECH_TO_VIDEO = "wavespeed-ai/wan-2.2/speech-to-video"

    # Kling v3.0 Std (via WaveSpeed) - image-to-video, 3-15s, $0.90/5s, sound 1.5x
    KLING_V3_STD = "kling-v3.0-std"
    # HappyHorse 1.0 (Alibaba, via WaveSpeed) - image-to-video, 720p/1080p, 3-15s, $0.14/s (720p)
    HAPPYHORSE_1_0_I2V = "happyhorse-1.0-i2v"
    # HappyHorse 1.1 (Alibaba, via WaveSpeed) - image-to-video, 720p/1080p, 3-15s, $0.70/5s (720p)
    HAPPYHORSE_1_1_I2V = "happyhorse-1.1-i2v"

    # OpenAI Sora
    SORA_2 = "sora-2"
    SORA_2_PRO = "sora-2-pro"

    # ==================== Audio tools ====================
    # Suno
    CHIRP_V4_5 = "chirp-v4-5"

    # MMAudio (via WaveSpeed)
    MMAUDIO_V2 = "mmaudio-v2"

    # Minimax Speech (via WaveSpeed)
    MINIMAX_SPEECH_2_5 = "minimax-speech-2.5"

    # Lipsync 2 Pro lip-sync (via WaveSpeed), standalone API: video+audio->synced video
    LIPSYNC_2_PRO = "sync/lipsync-2-pro"


# ==================== Tool function names ====================

class ToolName(str, Enum):
    """Enum of tool function names registered at runtime.

    Each value matches the string in an @tool("xxx") decorator,
    i.e. the name found in on_tool_end's kwargs["name"].
    """
    # Image generation - Nano Banana (Google Gemini)
    NANO_BANANA_T2I = "generate_image_with_nano_banana_t2i"
    NANO_BANANA_I2I = "generate_image_with_nano_banana_i2i"

    # Image generation - Seedream (ByteDance)
    SEEDREAM_T2I = "generate_image_with_wavespeed_seedream_t2i"
    SEEDREAM_I2I = "edit_image_with_wavespeed_seedream"

    # Image generation - OpenAI GPT Image 2 (WaveSpeed)
    GPT_IMAGE_2_T2I = "generate_image_with_wavespeed_gpt_image_2_t2i"
    GPT_IMAGE_2_I2I = "edit_image_with_wavespeed_gpt_image_2"

    # Video generation - Seedance (ByteDance)
    SEEDANCE_V1 = "generate_video_with_wavespeed_seedance"
    SEEDANCE_V1_5 = "generate_video_with_wavespeed_seedance_v1_5"
    SEEDANCE_2_I2V = "generate_video_with_wavespeed_seedance_2_i2v"
    SEEDANCE_2_I2V_TURBO = "generate_video_with_wavespeed_seedance_2_i2v_turbo"
    SEEDANCE_2_FAST_I2V = "generate_video_with_wavespeed_seedance_2_fast_i2v"
    SEEDANCE_2_FAST_I2V_TURBO = "generate_video_with_wavespeed_seedance_2_fast_turbo"
    SEEDANCE_2_T2V = "generate_video_with_wavespeed_seedance_2_t2v"
    SEEDANCE_2_FAST_T2V = "generate_video_with_wavespeed_seedance_2_fast_t2v"
    SEEDANCE_2_T2V_TURBO = "generate_video_with_wavespeed_seedance_2_t2v_turbo"
    SEEDANCE_2_FAST_T2V_TURBO = "generate_video_with_wavespeed_seedance_2_fast_t2v_turbo"

    # Video generation - Wan (Alibaba) / LTX Lipsync (WaveSpeed)
    WAN_2_5 = "generate_video_with_wavespeed_wan25"
    WAN_2_6 = "generate_video_with_wavespeed_wan26"
    LIPSYNC_LTX23 = "generate_video_with_wavespeed_ltx23_lipsync"
    LIPSYNC_KLING_V2_AI_AVATAR_PRO = "generate_video_with_wavespeed_kling_v2_ai_avatar_pro"
    LIPSYNC_WAN_22_SPEECH_TO_VIDEO = "generate_video_with_wavespeed_wan22_speech_to_video"

    # Video generation - Kling
    KLING_V3 = "generate_video_with_wavespeed_kling"
    HAPPYHORSE_1_0_I2V = "generate_video_with_wavespeed_happyhorse_1_0_i2v"
    HAPPYHORSE_1_1_I2V = "generate_video_with_wavespeed_happyhorse_1_1_i2v"

    # Video generation - Sora (OpenAI)
    SORA_2_T2V = "generate_video_with_sora_2_t2v"
    SORA_2_I2V = "generate_video_with_sora_2_i2v"
    SORA_2_PRO_T2V = "generate_video_with_sora_2_pro_t2v"
    SORA_2_PRO_I2V = "generate_video_with_sora_2_pro_i2v"

    # Music generation - Suno
    SUNO = "generate_music_with_suno"

    # Sound-effect generation - MMAudio
    MMAUDIO = "generate_audio_with_wavespeed"

    # Narration generation - Minimax Speech
    MINIMAX_SPEECH = "generate_speech_with_wavespeed"

    # Lip-sync - Lipsync (standalone API)
    LIPSYNC = "generate_lipsync_with_wavespeed"

    # Wrapper tools (fallback chain; on_tool_end may also fire)
    IMAGE_WRAPPER_T2I = "generate_image_with_fallback_t2i"
    IMAGE_WRAPPER_I2I = "generate_image_with_fallback_i2i"
    VIDEO_WRAPPER_I2V = "generate_video_with_fallback_i2v"
    VIDEO_WRAPPER_REF_T2V = "generate_video_with_fallback_ref_t2v"
    LIPSYNC_WRAPPER_I2V = "generate_lipsync_video_with_fallback_i2v"
    SPEECH_WRAPPER = "generate_speech_with_fallback"


# Mapping from tool function name -> ToolType (for callback cost tracking)
# nano_banana t2i / i2i share one ToolType (cost is by token, mode-agnostic)
# sora t2v / i2v share one ToolType (cost is by resolution and duration, mode-agnostic)
TOOL_NAME_TO_TYPE: dict["ToolName", "ToolType"] = {
    ToolName.NANO_BANANA_T2I:   ToolType.GEMINI_2_5_FLASH_IMAGE,
    ToolName.NANO_BANANA_I2I:   ToolType.GEMINI_2_5_FLASH_IMAGE,
    ToolName.SEEDREAM_T2I:      ToolType.SEEDREAM_V4_5,
    ToolName.SEEDREAM_I2I:      ToolType.SEEDREAM_V4_5,
    ToolName.GPT_IMAGE_2_T2I:   ToolType.GPT_IMAGE_2,
    ToolName.GPT_IMAGE_2_I2I:   ToolType.GPT_IMAGE_2,
    ToolName.SEEDANCE_V1:       ToolType.SEEDANCE_V1_PRO_FAST,
    ToolName.SEEDANCE_V1_5:     ToolType.SEEDANCE_V1_5_PRO_FAST,
    ToolName.SEEDANCE_2_I2V: ToolType.SEEDANCE_2_I2V,
    ToolName.SEEDANCE_2_I2V_TURBO: ToolType.SEEDANCE_2_I2V_TURBO,
    ToolName.SEEDANCE_2_FAST_I2V: ToolType.SEEDANCE_2_FAST_I2V,
    ToolName.SEEDANCE_2_FAST_I2V_TURBO: ToolType.SEEDANCE_2_FAST_I2V_TURBO,
    ToolName.SEEDANCE_2_T2V: ToolType.SEEDANCE_2_T2V,
    ToolName.SEEDANCE_2_FAST_T2V: ToolType.SEEDANCE_2_FAST_T2V,
    ToolName.SEEDANCE_2_T2V_TURBO: ToolType.SEEDANCE_2_T2V_TURBO,
    ToolName.SEEDANCE_2_FAST_T2V_TURBO: ToolType.SEEDANCE_2_FAST_T2V_TURBO,
    ToolName.WAN_2_5:           ToolType.WAN_2_5_I2V,
    ToolName.WAN_2_6:           ToolType.WAN_2_6_FLASH_I2V,
    ToolName.KLING_V3:          ToolType.KLING_V3_STD,
    ToolName.HAPPYHORSE_1_0_I2V: ToolType.HAPPYHORSE_1_0_I2V,
    ToolName.HAPPYHORSE_1_1_I2V: ToolType.HAPPYHORSE_1_1_I2V,
    ToolName.SORA_2_T2V:        ToolType.SORA_2,
    ToolName.SORA_2_I2V:        ToolType.SORA_2,
    ToolName.SORA_2_PRO_T2V:    ToolType.SORA_2_PRO,
    ToolName.SORA_2_PRO_I2V:    ToolType.SORA_2_PRO,
    ToolName.SUNO:              ToolType.CHIRP_V4_5,
    ToolName.MMAUDIO:           ToolType.MMAUDIO_V2,
    ToolName.MINIMAX_SPEECH:    ToolType.MINIMAX_SPEECH_2_5,
    ToolName.LIPSYNC:           ToolType.LIPSYNC_2_PRO,
    ToolName.LIPSYNC_LTX23:     ToolType.LTX_2_3_LIPSYNC,
    ToolName.LIPSYNC_KLING_V2_AI_AVATAR_PRO: ToolType.KLING_V2_AI_AVATAR_PRO,
    ToolName.LIPSYNC_WAN_22_SPEECH_TO_VIDEO: ToolType.WAN_2_2_SPEECH_TO_VIDEO,
    # Wrapper tools do not map directly to a ToolType (they call leaf tools internally, and each leaf tool fires its own on_tool_end)
}


# ==================== Providers ====================

class ToolProvider(str, Enum):
    """Tool provider enum."""
    GOOGLE = "google"  # Google Gemini (Nano Banana image generation)
    WAVESPEED = "wavespeed"
    OPENAI = "openai"
    SUNO = "suno"
    USER_UPLOAD = "user_upload"  # user-uploaded images


# ==================== Tool categories ====================

class ToolCategory(str, Enum):
    """Tool categories (to distinguish functional domains)."""
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    MUSIC_GENERATION = "music_generation"
    AUDIO_EFFECT = "audio_effect"
    SPEECH_SYNTHESIS = "speech_synthesis"
    LIPSYNC = "lipsync"
    TRANSCRIPTION = "transcription"


# Mapping from ToolType -> ToolCategory (for per-category callback stats; maintain here when adding a ToolType)
TOOL_TYPE_TO_CATEGORY: dict[ToolType, ToolCategory] = {
    ToolType.GEMINI_2_5_FLASH_IMAGE:         ToolCategory.IMAGE_GENERATION,
    ToolType.GEMINI_3_PRO_IMAGE_PREVIEW:     ToolCategory.IMAGE_GENERATION,
    ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW: ToolCategory.IMAGE_GENERATION,
    ToolType.SEEDREAM_V4_5:                  ToolCategory.IMAGE_GENERATION,
    ToolType.GPT_IMAGE_2:                  ToolCategory.IMAGE_GENERATION,
    ToolType.SEEDANCE_V1_PRO_FAST:       ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_V1_5_PRO_FAST:     ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_I2V: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_I2V_TURBO: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_FAST_I2V: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_FAST_I2V_TURBO: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_T2V: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_FAST_T2V: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_T2V_TURBO: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_2_FAST_T2V_TURBO: ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_V1_LITE_I2V_480P:  ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_V1_LITE_I2V_720P:  ToolCategory.VIDEO_GENERATION,
    ToolType.SEEDANCE_V1_LITE_I2V_1080P: ToolCategory.VIDEO_GENERATION,
    ToolType.WAN_2_5_I2V:                ToolCategory.VIDEO_GENERATION,
    ToolType.WAN_2_6_FLASH_I2V:          ToolCategory.VIDEO_GENERATION,
    ToolType.KLING_V3_STD:               ToolCategory.VIDEO_GENERATION,
    ToolType.HAPPYHORSE_1_0_I2V:         ToolCategory.VIDEO_GENERATION,
    ToolType.HAPPYHORSE_1_1_I2V:         ToolCategory.VIDEO_GENERATION,
    ToolType.SORA_2:                     ToolCategory.VIDEO_GENERATION,
    ToolType.SORA_2_PRO:                 ToolCategory.VIDEO_GENERATION,
    ToolType.CHIRP_V4_5:                 ToolCategory.MUSIC_GENERATION,
    ToolType.MMAUDIO_V2:                 ToolCategory.AUDIO_EFFECT,
    ToolType.MINIMAX_SPEECH_2_5:         ToolCategory.SPEECH_SYNTHESIS,
    ToolType.LIPSYNC_2_PRO:              ToolCategory.LIPSYNC,
    ToolType.LTX_2_3_LIPSYNC:            ToolCategory.LIPSYNC,
    ToolType.KLING_V2_AI_AVATAR_PRO:     ToolCategory.LIPSYNC,
    ToolType.WAN_2_2_SPEECH_TO_VIDEO:    ToolCategory.LIPSYNC,
}


# ==================== Resolution (unified) ====================

class Resolution(str, Enum):
    """Resolution enum (unified)."""
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"


# ==================== Aspect ratio (unified) ====================

class AspectRatio(str, Enum):
    """Aspect-ratio enum (unified)."""
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


# Product target pixels: Resolution x AspectRatio -> (width, height)
# Image generation uses this to pick an API tier and downsample to these pixels (Nano Banana, etc.)
TARGET_PIXELS: dict[tuple[Resolution, AspectRatio], tuple[int, int]] = {
    (Resolution.P480, AspectRatio.LANDSCAPE): (854, 480),
    (Resolution.P480, AspectRatio.PORTRAIT): (480, 854),
    (Resolution.P480, AspectRatio.SQUARE): (480, 480),
    (Resolution.P720, AspectRatio.LANDSCAPE): (1280, 720),
    (Resolution.P720, AspectRatio.PORTRAIT): (720, 1280),
    (Resolution.P720, AspectRatio.SQUARE): (720, 720),
    (Resolution.P1080, AspectRatio.LANDSCAPE): (1920, 1080),
    (Resolution.P1080, AspectRatio.PORTRAIT): (1080, 1920),
    (Resolution.P1080, AspectRatio.SQUARE): (1080, 1080),
}


# ==================== Content categories (templates) ====================

class GenerationMode(str, Enum):
    """Video generation mode: decides how a shot is generated."""
    NORMAL = "normal"           # normal shot: image -> video (current approach)
    LIPSYNC = "lipsync"        # lip-sync shot: image + audio -> lipsync video (wan audio_url)
    EMPTY_SHOT = "empty_shot"   # empty shot: no characters, only environment/objects; uses the normal video tool and is not a lipsync candidate


class AudioSegmentGranularity(str, Enum):
    """Audio-transcription segment granularity (orthogonal to TRANSCRIPTION_METHOD; decides how boundaries are cut).

    - PHRASE   : cut by musical phrase, emotion, rhythm changes; may merge several sentences into one segment.
    - SENTENCE : default. A complete semantic sentence (grammatically/semantically standalone) ~ 1 segment; in-sentence breaths/short pauses are merged; endpoints align to word boundaries.
    - BEAT     : boundaries prefer aligning to 4/4 bar lines (bar_sec = 240/BPM);
                 does not cut mid-word when vocals are present; falls back to PHRASE when BPM is unknown.
    """
    PHRASE = "phrase"
    SENTENCE = "sentence"
    BEAT = "beat"

    @classmethod
    def from_value(cls, value: "str | AudioSegmentGranularity | None") -> "AudioSegmentGranularity":
        """Normalize None/str/enum to an enum; None falls back to SENTENCE, unknown values to PHRASE."""
        if value is None:
            return cls.SENTENCE
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            raw = value.strip().lower()
            for m in cls:
                if m.value == raw:
                    return m
        return cls.PHRASE


class ContentCategory(str, Enum):
    """Content category: used for template-level rules and parameter selection (an enum, consistent with aspect_ratio, etc.)."""
    DEFAULT = "Default"             # default, story-driven MV
    LIP_SYNC_MV = "Lip-Sync MV"    # template: full lip-sync, multi-scene, fixed front-face/holding a mic
    PRODUCT_LAUNCH = "Product Launch"  # template: talking head + TTS narration + captions
    SHORT_DRAMA = "Short Drama"  # template: short drama - in-clip Seedance dialogue + sparse TTS narration

    @classmethod
    def from_value(cls, value: "str | ContentCategory | None") -> "ContentCategory":
        """Normalize a str or enum (as the LLM/frontend may return) to an enum. None/empty string -> DEFAULT."""
        if value is None:
            return cls.DEFAULT
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if raw == cls.LIP_SYNC_MV.value:
                return cls.LIP_SYNC_MV
            if raw == cls.PRODUCT_LAUNCH.value:
                return cls.PRODUCT_LAUNCH
            if raw == cls.SHORT_DRAMA.value:
                return cls.SHORT_DRAMA
            return cls.DEFAULT
        return cls.DEFAULT

    @classmethod
    def to_value(cls, value: "str | ContentCategory | None") -> str:
        """Convert to the string value (for DB storage and templates). None/empty string -> Default."""
        return cls.from_value(value).value


# ==================== Default-value constants ====================

# Image model -> user-option tool name; to change the default, change only DefaultValues.IMAGE_MODEL and this stays consistent
_IMAGE_MODEL_TO_TOOL_NAME = {
    ToolType.GEMINI_2_5_FLASH_IMAGE: "nano_banana",
    ToolType.GEMINI_3_PRO_IMAGE_PREVIEW: "nano_banana_pro",
    ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW: "nano_banana_2",  # standalone option, 3 nano banana models
    ToolType.GPT_IMAGE_2: "gpt_image_2",
}


class DefaultValues:
    """Default-value constants."""
    # Image-generation defaults (change the default model only at IMAGE_MODEL; the rest stays consistent)
    IMAGE_ASPECT_RATIO = AspectRatio.LANDSCAPE  # "16:9"
    IMAGE_RESOLUTION = Resolution.P1080  # "1080p"
    IMAGE_MODEL = ToolType.GPT_IMAGE_2  # default GPT Image 2: "gpt-image-2" (most stable in practice; the only one whose location reference image avoids the "giant" problem)
    IMAGE_MODEL_PRO = ToolType.GEMINI_3_PRO_IMAGE_PREVIEW  # "gemini-3-pro-image-preview"
    DEFAULT_IMAGE_TOOL_NAME = _IMAGE_MODEL_TO_TOOL_NAME[IMAGE_MODEL]  # "nano_banana" | "nano_banana_2" | "nano_banana_pro"

    # Video-generation defaults
    VIDEO_ASPECT_RATIO = AspectRatio.LANDSCAPE  # "16:9"
    VIDEO_RESOLUTION = Resolution.P1080  # "1080p"
    VIDEO_DURATION = 30  # default video duration (seconds)

    # Lipsync video-generation default (fallback tool used when the user's chosen tool does not support lipsync)
    DEFAULT_LIPSYNC_TOOL_VALUE: str = "wan_2_6_flash"  # Wan 2.6 Flash (default lipsync fallback)

    # Language default
    DEFAULT_LANGUAGE = "en"  # default language code (ISO 639-1)

    # Audio-transcription method (gradual-rollout switch)
    # - "gemini": Gemini only (matches historical behavior; does not call Suno)
    # - "hybrid": serial Suno->Gemini: first Suno gets word-level timestamps, then feeds the lyrics to Gemini as reference transcription,
    # then merges (endpoints snapped to Suno word boundaries + vocal_mask correction + word-level timestamp injection, with Suno as the source of truth throughout).
    # latency ~ Suno + Gemini, about 127s (user upload) / 87s (Suno-generated reuses clip_id and skips upload).
    # on Suno failure/copyright block, auto-falls back to Gemini-only, transparent to downstream.
    TRANSCRIPTION_METHOD: str = "hybrid"

    # hybrid word-level alignment provider (only effective when TRANSCRIPTION_METHOD="hybrid"; unrelated to the gemini-only path)
    # - "mureka": Mureka V7.6 recognize-song (default; via WaveSpeed, no upload step; no song-structure/gender hint,
    # but gives word-level timestamps directly; after reshaping it uses the same generated_lyrics + alignment_context injection as the Suno path)
    # alignment quality is better than Suno in practice, so it is the default.
    # - "suno":   Suno Sonic upload + aligned-lyrics (historical behavior; includes song-structure/vocal-gender hint)
    # if any provider fails, auto-falls back to Gemini-only, transparent to downstream.
    ALIGNMENT_PROVIDER: str = "mureka"

    # fallback granularity (see agent_config.transcription.TRANSCRIPTION_ENGINE_PROFILES)
    AUDIO_SEGMENT_GRANULARITY: str = AudioSegmentGranularity.SENTENCE.value


def get_target_pixels_for_video(
    resolution: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
) -> Tuple[int, int]:
    """Look up (width, height) by resolution and aspect_ratio, consistent with the tool layer / WaveSpeed.
    Shared by the tool layer and the sync fallback migration; later changes to TARGET_PIXELS or defaults go only here."""
    try:
        res_enum = Resolution(resolution) if resolution else DefaultValues.VIDEO_RESOLUTION
    except ValueError:
        res_enum = DefaultValues.VIDEO_RESOLUTION
    try:
        ar_enum = AspectRatio(aspect_ratio) if aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO
    except ValueError:
        ar_enum = DefaultValues.VIDEO_ASPECT_RATIO
    target = TARGET_PIXELS.get((res_enum, ar_enum))
    if target:
        return target
    return (1920, 1080)
