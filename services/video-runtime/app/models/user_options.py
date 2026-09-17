"""
User-option models
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Imported from the unified enum file
from .tool_enums import Resolution, AspectRatio, ContentCategory, DefaultValues
from ..utils.i18n import get_i18n_message_async


class ImageGenerationTool(str, Enum):
    """Image-generation tool enum (user option)."""
    AUTO = "auto"  # auto-select, consistent with video auto; expanded to DEFAULT_IMAGE_TOOL for enqueue/billing/wrapper
    NANO_BANANA = "nano_banana"           # gemini-2.5-flash-image
    NANO_BANANA_2 = "nano_banana_2"       # gemini-3.1-flash-image-preview, cheaper Pro
    NANO_BANANA_PRO = "nano_banana_pro"   # gemini-3-pro-image-preview, pro version
    SEEDREAM = "seedream"                 # WaveSpeed Seedream v4.5
    GPT_IMAGE_2 = "gpt_image_2"           # WaveSpeed openai/gpt-image-2（T2I + Edit）


class NanoBananaModel(str, Enum):
    """Nano Banana model enum."""
    FLASH = "gemini-2.5-flash-image"  # Nano Banana (fast version)
    PRO = "gemini-3-pro-image-preview"  # Nano Banana Pro (pro version)


class VideoGenerationTool(str, Enum):
    """Video-generation tool enum (user option)."""
    AUTO = "auto"  # auto-select; frontend shows auto, backend uses DEFAULT_VIDEO_TOOL
    POLLO_SEEDANCE = "pollo_seedance"  # Seedance v1 Pro Fast (supports first/last frame via Lite)
    SEEDANCE_V1_5 = "pollo_seedance_v1_5"  # Seedance v1.5 Pro (image-to-video-fast), 720p/1080p, no audio by default
    SEEDANCE_2_I2V = "seedance_2_i2v"  # Seedance 2.0 Image-to-Video (WaveSpeed), 480p/720p/1080p, 4-15s, optional last_image, generate_audio=False
    SEEDANCE_2_I2V_TURBO = "seedance_2_i2v_turbo"  # Seedance 2.0 Image-to-Video Turbo (WaveSpeed), 720p/1080p, 4-15s, optional last_image, generate_audio=False
    SEEDANCE_2_FAST_I2V = "seedance_2_fast_i2v"  # Seedance 2.0 Fast Image-to-Video (WaveSpeed), 480p/720p (no 1080p), 4-15s, optional last_image, generate_audio=False
    SEEDANCE_2_FAST_I2V_TURBO = "seedance_2_fast_i2v_turbo"  # Seedance 2.0 Fast Image-to-Video Turbo（WaveSpeed legacy fast endpoint），720p/1080p，4–15s
    WAN_2_5 = "wan_2_5"  # Alibaba Wan 2.5 (WaveSpeed), I2V with optional audio, no end image
    WAN_2_6 = "wan_2_6_flash"  # Alibaba Wan 2.6 Flash (WaveSpeed), image-to-video-flash, 720p/1080p, 3-15s
    LTX_2_3 = "ltx_2_3"  # WaveSpeed LTX 2.3 Lipsync, audio+image→video, 480p/720p/1080p
    KLING_V2_AI_AVATAR_PRO = "kling_v2_ai_avatar_pro"  # Kwaivgi Kling V2 AI Avatar Pro, audio+image->talking-head; product resolution aligned by ensure_on_s3
    WAN_2_2_SPEECH_TO_VIDEO = "wan_2_2_speech_to_video"  # WAN 2.2 Speech-to-Video (WaveSpeed); official API is 480p/720p only; capabilities does not offer 1080p (to avoid upscaling a 720p result)
    KLING_V3_STD = "kling_v3_std"  # Kling v3.0 Std (WaveSpeed), image-to-video, 3-15s, $0.90/5s
    HAPPYHORSE_1_0_I2V = "happyhorse_1_0_i2v"  # Alibaba HappyHorse 1.0 (WaveSpeed), image-to-video, 720p/1080p, 3-15s
    HAPPYHORSE_1_1_I2V = "happyhorse_1_1_i2v"  # Alibaba HappyHorse 1.1 (WaveSpeed), image-to-video, 720p/1080p, 3-15s
    OPENAI_SORA = "openai_sora"
    OPENAI_SORA_PRO = "openai_sora_pro"


# The video tool actually used when the user picks auto (change only here to switch the default)
DEFAULT_VIDEO_TOOL = VideoGenerationTool.POLLO_SEEDANCE  # Seedance v1.0 Pro Fast, faster than v1.5

# User video tools that support reference-to-video (T2V + reference_images, etc.); extend this set when adding new models
REFERENCE_TO_VIDEO_VIDEO_TOOLS = frozenset({
    VideoGenerationTool.SEEDANCE_2_I2V,
    VideoGenerationTool.SEEDANCE_2_I2V_TURBO,
    VideoGenerationTool.SEEDANCE_2_FAST_I2V,
    VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO,
})

# The image tool actually used when the user picks image auto (consistent with DefaultValues.DEFAULT_IMAGE_TOOL_NAME)
DEFAULT_IMAGE_TOOL = ImageGenerationTool(DefaultValues.DEFAULT_IMAGE_TOOL_NAME)

# Video tools that support lip-sync (only those in this set are used for lipsync shots); to add a lip-sync model, change only here
LIPSYNC_CAPABLE_VIDEO_TOOLS = frozenset({
    VideoGenerationTool.LTX_2_3,
    VideoGenerationTool.KLING_V2_AI_AVATAR_PRO,
    VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO,
    VideoGenerationTool.WAN_2_5,
    VideoGenerationTool.WAN_2_6,
})

# Lip-sync video-tool dropdown options (for GET /options/capabilities and the frontend); includes auto, which lipsync_tool_wrapper expands to the default lip-sync model at execution
LIPSYNC_VIDEO_TOOL_OPTIONS = [
    {"value": VideoGenerationTool.AUTO.value, "label": "Auto"},
    {"value": VideoGenerationTool.LTX_2_3.value, "label": "WaveSpeed LTX 2.3 Lipsync"},
    {"value": VideoGenerationTool.KLING_V2_AI_AVATAR_PRO.value, "label": "Kling V2 AI Avatar Pro"},
    {"value": VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO.value, "label": "WAN 2.2 Speech-to-Video"},
    {"value": VideoGenerationTool.WAN_2_5.value, "label": "WaveSpeed Wan 2.5"},
    {"value": VideoGenerationTool.WAN_2_6.value, "label": "WaveSpeed Wan 2.6 Flash"},
]


def _is_short_drama_user_option(user_option: Optional["UserOption"]) -> bool:
    if not user_option or not getattr(user_option, "content_category", None):
        return False
    return user_option.content_category == ContentCategory.SHORT_DRAMA


def resolve_effective_video_tool(user_option: "UserOption") -> "VideoGenerationTool":
    """Resolve the VideoGenerationTool actually used for normal video (consistent with cost_estimation / wrapper chain).

    Short Drama + AUTO -> Seedance 2 Fast I2V Turbo (dialogue/in-clip audio); does not override a tool the user explicitly chose.
    """
    vgt = getattr(user_option, "video_generation_tool", None)
    if vgt is None or vgt == VideoGenerationTool.AUTO:
        if _is_short_drama_user_option(user_option):
            return VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO
        return DEFAULT_VIDEO_TOOL
    return vgt


def apply_short_drama_default_video_tool(user_option: Optional["UserOption"]) -> Optional["UserOption"]:
    """For Short Drama with the video tool set to AUTO, persist as Seedance2 Fast Turbo; unchanged if a manual tool was chosen."""
    if not user_option or not _is_short_drama_user_option(user_option):
        return user_option
    vgt = getattr(user_option, "video_generation_tool", None)
    if vgt is not None and vgt != VideoGenerationTool.AUTO:
        return user_option
    return user_option.model_copy(
        update={"video_generation_tool": VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO}
    )


def materialize_video_generation_tool(user_option: Optional["UserOption"]) -> Optional["UserOption"]:
    """Expand AUTO to the actual tool before enqueue (Short Drama -> SD2 Fast Turbo, otherwise DEFAULT_VIDEO_TOOL).

    Do not blindly write DEFAULT_VIDEO_TOOL first and then apply the short-drama default - that would lock Short Drama+AUTO into pollo_seedance,
    causing it to still go through the keyframe pipeline.
    """
    if not user_option:
        return user_option
    effective = resolve_effective_video_tool(user_option)
    current = getattr(user_option, "video_generation_tool", None)
    if current == effective:
        return user_option
    return user_option.model_copy(update={"video_generation_tool": effective})


def video_tool_supports_reference_to_video(tool: Optional[VideoGenerationTool]) -> bool:
    """Whether the current video tool supports reference-to-video (T2V + reference material)."""
    return tool is not None and tool in REFERENCE_TO_VIDEO_VIDEO_TOOLS


def should_skip_keyframe_pipeline(user_option: Optional["UserOption"]) -> bool:
    """Seedance2 family: skips first_frame_revision / keyframe / reflection and goes straight to reference-to-video."""
    if not user_option:
        return False
    return video_tool_supports_reference_to_video(resolve_effective_video_tool(user_option))


def should_use_reference_to_video(user_option: Optional["UserOption"]) -> bool:
    """Whether to use reference-to-video (T2V + reference_images) instead of I2V for normal video shots.

    Forced on for Seedance2 (which skips the keyframe pipeline); other tools remain gated by the USE_REFERENCE_TO_VIDEO switch.
    """
    if not user_option:
        return False
    if should_skip_keyframe_pipeline(user_option):
        return True
    from app.services.agent.video.agent_video_constants import USE_REFERENCE_TO_VIDEO

    if not USE_REFERENCE_TO_VIDEO:
        return False
    return video_tool_supports_reference_to_video(resolve_effective_video_tool(user_option))


def build_reference_to_video_images(
    start_image_url: Optional[str],
    end_image_url: Optional[str],
    character_ref_urls: Optional[List[str]],
    max_count: int,
) -> List[str]:
    """Assemble reference_images for reference-to-video: first frame -> last frame -> character images, deduplicated and truncated."""
    refs: List[str] = []
    for url in (start_image_url, end_image_url):
        if url and url not in refs:
            refs.append(url)
    for url in character_ref_urls or []:
        if url and url not in refs:
            refs.append(url)
    return refs[:max(1, max_count)]


def should_apply_lipsync_for_planning(user_option: Optional["UserOption"]) -> bool:
    """Whether to fold the lip-sync chain into AUDIO planning (duration intersection, explicit scene-split threshold)."""
    return should_enable_lipsync_for_run(user_option)


def should_enable_lipsync_for_run(
    user_option: Optional["UserOption"] = None,
    *,
    music_intent: Optional[str] = None,
    music_workflow_mode: Optional[str] = None,
    audio_transcription: Optional[Any] = None,
) -> bool:
    """Whether lip-sync is allowed for this run (scene/shot generation_mode, transcription splitting, video generation).

    Pure BGM / parallel BGM / no-lyrics transcription / fully vocal-less -> lip-sync disabled (regardless of lipsync_coverage).
    """
    if (music_intent or "").strip() == "instrumental_bgm":
        return False
    if (music_workflow_mode or "").strip() == "bgm_parallel":
        return False
    if audio_transcription is not None:
        if getattr(audio_transcription, "is_instrumental", False):
            return False
        segments = getattr(audio_transcription, "segments", None) or []
        if segments:
            has_vocal = False
            for seg in segments:
                vp = getattr(seg, "vocal_presence", None)
                if vp is True:
                    has_vocal = True
                    break
                if vp is None and (getattr(seg, "text", None) or "").strip():
                    has_vocal = True
                    break
            if not has_vocal:
                return False
    if not user_option:
        return False
    from app.models.tool_enums import ContentCategory

    if user_option.content_category == ContentCategory.LIP_SYNC_MV:
        return True
    if user_option.content_category == ContentCategory.PRODUCT_LAUNCH:
        return True
    # Short drama: character dialogue uses Seedance in-clip audio, not a standalone lipsync/TTS chain
    # (the frontend may still send lipsync_coverage, but that must not enable lip-sync)
    if user_option.content_category == ContentCategory.SHORT_DRAMA:
        return False
    if getattr(user_option, "lipsync_coverage", 0) > 0:
        return True
    return False


def resolve_effective_lipsync_tool(
    user_option: "UserOption",
) -> "VideoGenerationTool":
    """Resolve the VideoGenerationTool actually used for lipsync (single source of truth, shared by all callers).

    Resolution priority:
      1. user_option.lipsync_video_tool (the lip-sync tool the user explicitly chose, non-auto)
      2. user_option.video_generation_tool (non-auto and in LIPSYNC_CAPABLE)
      3. auto -> route by resolution: 1080p -> kling_v2_ai_avatar_pro, otherwise -> wan_2_2_speech_to_video

    Callers: cost_estimation._cost_per_lipsync_shot_dollar / lipsync_tool_wrapper / per_shot_routing
    """
    lip = getattr(user_option, "lipsync_video_tool", None)
    if lip is not None and lip != VideoGenerationTool.AUTO and lip in LIPSYNC_CAPABLE_VIDEO_TOOLS:
        return lip

    vgt = getattr(user_option, "video_generation_tool", None)
    if vgt is not None and vgt != VideoGenerationTool.AUTO and vgt in LIPSYNC_CAPABLE_VIDEO_TOOLS:
        return vgt

    res = getattr(user_option, "resolution", None)
    rv = getattr(res, "value", None) if res is not None else None
    if rv == Resolution.P1080.value:
        return VideoGenerationTool.KLING_V2_AI_AVATAR_PRO
    return VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO


async def get_tool_capabilities(
    image_tool: Optional[ImageGenerationTool] = None,
    video_tool: Optional[VideoGenerationTool] = None,
    lipsync_tool: Optional[VideoGenerationTool] = None,
) -> Dict[str, Any]:
    """Return the supported aspect_ratio, resolution, and lip-sync tool list for the currently selected image_tool / video_tool / lipsync_tool.
    warnings are only appended when the available range is narrowed by actual capability (e.g. Sora has no 1080p); no explanatory text is added for a "normal workflow"."""
    warnings: List[str] = []

    # 1) Resolutions supported by the video tool (see docs/resolution_aspect_ratio_support_and_rules.md 1.2)
    vt = video_tool or DEFAULT_VIDEO_TOOL
    if vt == VideoGenerationTool.AUTO:
        vt = DEFAULT_VIDEO_TOOL
    if vt in (VideoGenerationTool.OPENAI_SORA, VideoGenerationTool.OPENAI_SORA_PRO):
        # Sora API outputs 720p only; 480p is produced by downsampling the 720p result, so the product treats it as supporting 480p/720p
        allowed_res = [Resolution.P480, Resolution.P720]
        warnings.append(await get_i18n_message_async("capability_warnings.sora"))
    elif vt == VideoGenerationTool.KLING_V3_STD:
        allowed_res = [Resolution.P480, Resolution.P720]
        warnings.append(await get_i18n_message_async("capability_warnings.kling"))
    elif vt == VideoGenerationTool.SEEDANCE_2_FAST_I2V:
        allowed_res = [Resolution.P480, Resolution.P720]
        warnings.append(await get_i18n_message_async("capability_warnings.seedance_2_fast_i2v"))
    else:
        # Seedance v1, v1.5, 2.0, 2.0 Turbo, Wan 2.5, 2.6, etc.: 480p/720p/1080p (some 480p downscaled from 720p)
        allowed_res = [Resolution.P480, Resolution.P720, Resolution.P1080]

    # 2) Aspect ratios supported by the video tool (Sora has no 1:1)
    if vt in (VideoGenerationTool.OPENAI_SORA, VideoGenerationTool.OPENAI_SORA_PRO):
        allowed_ar = [AspectRatio.LANDSCAPE, AspectRatio.PORTRAIT]
    else:
        allowed_ar = [AspectRatio.LANDSCAPE, AspectRatio.PORTRAIT, AspectRatio.SQUARE]
    aspect_ratios = [{"value": ar.value, "label": ar.value} for ar in allowed_ar]

    # 3) The image tool narrows resolution further (see docs 1.1: only Nano Banana 2.5 Flash lacks 1080p)
    img_eff = image_tool
    if img_eff == ImageGenerationTool.AUTO:
        img_eff = DEFAULT_IMAGE_TOOL
    if img_eff == ImageGenerationTool.NANO_BANANA:
        allowed_res = [r for r in allowed_res if r != Resolution.P1080]
        warnings.append(await get_i18n_message_async("capability_warnings.nano_banana"))

    # 4) If a lipsync_tool is passed, intersect with the video capability (LTX / Kling / Wan 2.5/2.6: 480p/720p/1080p; WAN 2.2 S2V is 480p/720p only, see docs)
    lt_eff = lipsync_tool
    if lt_eff == VideoGenerationTool.AUTO:
        lt_eff = VideoGenerationTool(DefaultValues.DEFAULT_LIPSYNC_TOOL_VALUE)
    if lt_eff and lt_eff in LIPSYNC_CAPABLE_VIDEO_TOOLS:
        lipsync_res = [Resolution.P480, Resolution.P720, Resolution.P1080]
        if lt_eff == VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO:
            lipsync_res = [Resolution.P480, Resolution.P720]
        lipsync_ar = [AspectRatio.LANDSCAPE, AspectRatio.PORTRAIT, AspectRatio.SQUARE]
        allowed_res = [r for r in allowed_res if r in lipsync_res]
        allowed_ar = [a for a in allowed_ar if a in lipsync_ar]
        aspect_ratios = [{"value": ar.value, "label": ar.value} for ar in allowed_ar]

    resolutions = [{"value": r.value, "label": r.value} for r in allowed_res]

    return {
        "aspect_ratios": aspect_ratios,
        "resolutions": resolutions,
        "warnings": warnings,
        "lipsync_video_tools": list(LIPSYNC_VIDEO_TOOL_OPTIONS),
    }


class VideoMode(str, Enum):
    """Video-generation mode."""
    INSTANT = "instant"  # fast mode
    MASTER = "master"    # master mode


class UserOption(BaseModel):
    """User-option configuration."""
    image_generation_tool: ImageGenerationTool = Field(
        description="用户选择的图像生成工具；auto 时与视频 auto 一致由后端展开为 DEFAULT_IMAGE_TOOL（入队时与 Wrapper 内均解析）",
        default=ImageGenerationTool(DefaultValues.DEFAULT_IMAGE_TOOL_NAME)
    )
    # Removed the nano_banana_model field; it can be inferred from image_generation_tool:
    # NANO_BANANA -> gemini-2.5-flash-image
    # NANO_BANANA_2 -> gemini-3.1-flash-image-preview
    # NANO_BANANA_PRO -> gemini-3-pro-image-preview
    video_generation_tool: VideoGenerationTool = Field(
        description="用户选择的视频生成工具",
        default=VideoGenerationTool.AUTO
    )
    lipsync_video_tool: VideoGenerationTool = Field(
        description="口型视频模型：仅对口型同步镜头生效；可选 auto 或 LTX 2.3 / Kling V2 AI Avatar Pro / Wan 2.5 / Wan 2.6 Flash。默认 auto：由 per_shot_generation_routing 按分辨率写入 wan_2_2_speech_to_video / kling_v2_ai_avatar_pro，执行前经 resolve_user_option_for_shot 合并；未合并时再在 lipsync_tool_wrapper 内展开为 DEFAULT_LIPSYNC。",
        default=VideoGenerationTool.AUTO,
    )
    mode: VideoMode = Field(
        description="视频生成模式 - instant快速模式 或 master大师模式",
        default=VideoMode.MASTER
    )
    aspect_ratio: AspectRatio = Field(
        description="视频宽高比：16:9 横屏、1:1 方屏、9:16 竖屏。部分视频工具不支持全部组合（如 Sora 无 1:1 会回退横屏）；由后端自动映射，前端可通过 GET /agent-router/options/capabilities 按当前工具获取说明。",
        default=AspectRatio.LANDSCAPE
    )
    resolution: Resolution = Field(
        description="视频分辨率：480p / 720p / 1080p。部分工具仅支持子集（如 Sora 仅 720p，Seedance v1.5 / Wan 2.6 仅 720p/1080p）；由后端自动映射或降档，前端可通过 GET /agent-router/options/capabilities 按当前工具获取可选列表与说明。",
        default=Resolution.P1080
    )
    duration: int = Field(
        description="视频时长（秒），范围5-600秒",
        default=30,
        ge=5,
        le=600
    )
    lipsync_coverage: int = Field(
        description="唇形同步覆盖率百分比：0=关闭, 10/20/30...=覆盖比例",
        default=0,
        ge=0,
        le=100
    )
    content_category: Optional[ContentCategory] = Field(
        default=ContentCategory.DEFAULT,
        description="内容类别：Default / Lip-Sync MV / Product Launch / Short Drama（前端传字符串会被自动转成 enum）"
    )
    enable_continuity_mode: bool = Field(
        description="是否启用连续模式（所有帧从头到尾保持连续连接）",
        default=False
    )

    # Keyframe Reflection configuration
    enable_keyframe_reflection: bool = Field(
        description="是否启用关键帧反思（分析角色一致性并优化）",
        default=False
    )
    max_reflection_iterations: int = Field(
        description="关键帧反思最大迭代次数",
        default=2,
        ge=1,
        le=5
    )
    reflection_threshold: float = Field(
        description="关键帧反思停止阈值（一致性评分达到此值时停止）",
        default=0.8,
        ge=0.0,
        le=1.0
    )
    reflection_concurrency: int = Field(
        description="关键帧反思并发数",
        default=5,
        ge=1,
        le=10
    )
    full_auto: bool = Field(
        default=False,
        description="完全托管：视频管线门闩可跳过 interrupt，或 interrupt 后由后端延迟自动 continue；与前端 Full Auto / autoContinueOnInterrupt 一致，须持久化在 conversation_runs.user_option",
    )

    def __init__(self, **data):
        super().__init__(**data)

    @classmethod
    def default(cls) -> "UserOption":
        """Create default user options."""
        return cls(
            image_generation_tool=ImageGenerationTool(DefaultValues.DEFAULT_IMAGE_TOOL_NAME),
            video_generation_tool=VideoGenerationTool.AUTO,
            lipsync_video_tool=VideoGenerationTool.AUTO,
            mode=VideoMode.MASTER,
            aspect_ratio=AspectRatio.LANDSCAPE,
            resolution=Resolution.P1080,
            duration=30,
            lipsync_coverage=0,
            content_category=ContentCategory.DEFAULT,
            enable_continuity_mode=False,
            enable_keyframe_reflection=False,
            max_reflection_iterations=2,
            reflection_threshold=0.8,
            reflection_concurrency=5,
            full_auto=False,
        )
