"""
Data models for image-generation results
"""
import json
import re
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, asdict
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator


class ImageProvider(str, Enum):
    """Image-generation service provider enum."""
    OPENAI = "openai"
    NANO_BANANA = "nano_banana"
    WAVESPEED = "wavespeed"
    SEEDREAM = "seedream"


class VideoProvider(str, Enum):
    """Video-generation service provider enum."""
    POLLO = "pollo"
    WAVESPEED = "wavespeed"
    OPENAI_SORA = "openai_sora"
    JIMENG_VIDEO = "jimeng_video"


class StoryProvider(str, Enum):
    """Story-generation service provider enum."""
    GPT = "gpt"


class StoryGenerationResult(BaseModel):
    """Story-generation result."""
    success: bool = True
    story_content: Optional[str] = None
    generated_prompt: Optional[str] = None
    provider: Optional[StoryProvider] = None
    message: Optional[str] = None
    error_message: Optional[str] = None

    def to_json(self, ensure_ascii: bool = True, indent: int = 2) -> str:
        """Convert to a JSON string."""
        return json.dumps(self.model_dump(), ensure_ascii=ensure_ascii, indent=indent)

    @classmethod
    def success_result(
        cls,
        story_content: str,
        generated_prompt: str,
        provider: StoryProvider,
        message: str = "故事生成成功"
    ) -> "StoryGenerationResult":
        """Create a success result."""
        return cls(
            success=True,
            story_content=story_content,
            generated_prompt=generated_prompt,
            provider=provider,
            message=message
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: StoryProvider
    ) -> "StoryGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            error_message=error_message,
            provider=provider
        )


class SpeechProvider(str, Enum):
    """Speech-generation service provider enum."""
    WAVESPEED = "wavespeed"


class AudioProvider(str, Enum):
    """Sound-effect-generation service provider enum."""
    WAVESPEED = "wavespeed"


class MusicProvider(str, Enum):
    """Music-generation service provider enum."""
    SUNO = "suno"


class VoiceID(str, Enum):
    """WaveSpeed voice-ID enum."""
    # Based on the voice_id parameter in the official WaveSpeed docs

    # ===== General voices =====
    WISE_WOMAN = "Wise_Woman"
    FRIENDLY_PERSON = "Friendly_Person"
    INSPIRATIONAL_GIRL = "Inspirational_girl"
    DEEP_VOICE_MAN = "Deep_Voice_Man"
    CALM_WOMAN = "Calm_Woman"
    CASUAL_GUY = "Casual_Guy"
    LIVELY_GIRL = "Lively_Girl"
    PATIENT_MAN = "Patient_Man"
    YOUNG_KNIGHT = "Young_Knight"
    DETERMINED_MAN = "Determined_Man"
    LOVELY_GIRL = "Lovely_Girl"
    DECENT_BOY = "Decent_Boy"
    IMPOSING_MANNER = "Imposing_Manner"
    ELEGANT_MAN = "Elegant_Man"
    ABBESS = "Abbess"
    SWEET_GIRL_2 = "Sweet_Girl_2"
    EXUBERANT_GIRL = "Exuberant_Girl"

    # ===== English voices =====
    # News-broadcast style
    ENGLISH_EXPRESSIVE_NARRATOR = "English_expressive_narrator"
    ENGLISH_CAPTIVATING_FEMALE1 = "English_captivating_female1"
    ENGLISH_COMPELLING_LADY1 = "English_compelling_lady1"
    ENGLISH_MAGNETIC_MALE_2 = "English_Magnetic_Male_2"
    ENGLISH_LIVELY_MALE_11 = "English_Lively_Male_11"
    ENGLISH_FRIENDLY_FEMALE_3 = "English_Friendly_Female_3"
    ENGLISH_STEADY_FEMALE_1 = "English_Steady_Female_1"
    ENGLISH_LIVELY_MALE_10 = "English_Lively_Male_10"

    # Everyday-conversation style
    ENGLISH_RADIANT_GIRL = "English_radiant_girl"
    ENGLISH_AUSSIE_BLOKE = "English_Aussie_Bloke"
    ENGLISH_UPBEAT_WOMAN = "English_Upbeat_Woman"
    ENGLISH_TRUSTWORTH_MAN = "English_Trustworth_Man"
    ENGLISH_CALM_WOMAN = "English_CalmWoman"
    ENGLISH_FRIENDLY_PERSON = "English_FriendlyPerson"
    ENGLISH_SERENE_WOMAN = "English_SereneWoman"
    ENGLISH_CONFIDENT_WOMAN = "English_ConfidentWoman"
    ENGLISH_LOVELY_LADY = "English_LovelyLady"
    ENGLISH_KIND_HEARTED_GIRL = "English_Kind-heartedGirl"
    ENGLISH_FRIENDLY_NEIGHBOR = "English_FriendlyNeighbor"

    # Role-play style
    ENGLISH_MAGNETIC_VOICED_MAN = "English_magnetic_voiced_man"
    ENGLISH_UPSET_GIRL = "English_UpsetGirl"
    ENGLISH_GENTLE_VOICED_MAN = "English_Gentle-voiced_man"
    ENGLISH_DILIGENT_MAN = "English_Diligent_Man"
    ENGLISH_GRACEFUL_LADY = "English_Graceful_Lady"
    ENGLISH_HUSKY_METALHEAD = "English_Husky_MetalHead"
    ENGLISH_RESERVED_YOUNG_MAN = "English_ReservedYoungMan"
    ENGLISH_PLAYFUL_GIRL = "English_PlayfulGirl"
    ENGLISH_MAN_WITH_DEEP_VOICE = "English_ManWithDeepVoice"
    ENGLISH_GENTLE_TEACHER = "English_GentleTeacher"
    ENGLISH_MATURE_PARTNER = "English_MaturePartner"
    ENGLISH_MATURE_BOSS = "English_MatureBoss"
    ENGLISH_DEBATOR = "English_Debator"
    ENGLISH_ABBESS = "English_Abbess"
    ENGLISH_LOVELY_GIRL = "English_LovelyGirl"
    ENGLISH_STEADY_MENTOR = "English_Steadymentor"
    ENGLISH_DEEP_VOICED_GENTLEMAN = "English_Deep-VoicedGentleman"
    ENGLISH_DETERMINED_MAN = "English_DeterminedMan"
    ENGLISH_WISE_LADY = "English_Wiselady"
    ENGLISH_CAPTIVATING_STORYTELLER = "English_CaptivatingStoryteller"
    ENGLISH_ATTRACTIVE_GIRL = "English_AttractiveGirl"
    ENGLISH_DECENT_YOUNG_MAN = "English_DecentYoungMan"
    ENGLISH_SENTIMENTAL_LADY = "English_SentimentalLady"
    ENGLISH_IMPOSING_MANNER = "English_ImposingManner"
    ENGLISH_SAD_TEEN = "English_SadTeen"
    ENGLISH_THOUGHTFUL_MAN = "English_ThoughtfulMan"
    ENGLISH_PASSIONATE_WARRIOR = "English_PassionateWarrior"
    ENGLISH_DECENT_BOY = "English_DecentBoy"
    ENGLISH_WISE_SCHOLAR = "English_WiseScholar"
    ENGLISH_SOFT_SPOKEN_GIRL = "English_Soft-spokenGirl"
    ENGLISH_PATIENT_MAN = "English_PatientMan"
    ENGLISH_COMEDIAN = "English_Comedian"
    ENGLISH_GORGEOUS_LADY = "English_GorgeousLady"
    ENGLISH_BOSSY_LEADER = "English_BossyLeader"
    ENGLISH_STRONG_WILLED_BOY = "English_Strong-WilledBoy"
    ENGLISH_DEEP_TONED_MAN = "English_Deep-tonedMan"
    ENGLISH_STRESSED_LADY = "English_StressedLady"
    ENGLISH_ASSERTIVE_QUEEN = "English_AssertiveQueen"
    ENGLISH_ANIME_CHARACTER = "English_AnimeCharacter"
    ENGLISH_JOVIAL_MAN = "English_Jovialman"
    ENGLISH_WHIMSICAL_GIRL = "English_WhimsicalGirl"
    ENGLISH_CHARMING_QUEEN = "English_CharmingQueen"

    # Professional-host style
    ENGLISH_MAGNETIC_MALE_12 = "English_Magnetic_Male_12"
    ENGLISH_STEADY_FEMALE_5 = "English_Steady_Female_5"
    ENGLISH_INSIGHTFUL_SPEAKER = "English_Insightful_Speaker"
    ENGLISH_PATIENT_MAN_V1 = "English_patient_man_v1"
    ENGLISH_PERSUASIVE_MAN = "English_Persuasive_Man"
    ENGLISH_EXPLANATORY_MAN = "English_Explanatory_Man"
    ENGLISH_INTELLECT_FEMALE_1 = "English_intellect_female_1"
    ENGLISH_ENERGETIC_MALE_1 = "English_energetic_male_1"
    ENGLISH_WITTY_FEMALE_1 = "English_witty_female_1"

    # Special-effect style
    ENGLISH_LUCKY_ROBOT = "English_Lucky_Robot"
    WHISPER_MAN = "whisper_man"
    WHISPER_WOMAN_1 = "whisper_woman_1"
    ENGLISH_WHISPERING_GIRL_V3 = "English_Whispering_girl_v3"
    ANGRY_PIRATE_1 = "angry_pirate_1"
    MASSIVE_KIND_TROLL = "massive_kind_troll"
    MOVIE_TRAILER_DEEP = "movie_trailer_deep"
    PEACE_AND_EASE = "peace_and_ease"

    # Diverse-accent style
    ENGLISH_CUTE_GIRL = "English_Cute_Girl"
    ENGLISH_SHARP_COMMENTATOR = "English_Sharp_Commentator"
    ENGLISH_HONEST_MAN = "English_Honest_Man"

    # Distinctive-character style (Moss Audio)
    MOSS_AUDIO_GRANNY = "moss_audio_6dc281eb-713c-11f0-a447-9613c873494c"
    MOSS_AUDIO_YOUNG_WOMAN = "moss_audio_c12a59b9-7115-11f0-a447-9613c873494c"
    MOSS_AUDIO_SOUTHERN_GUY = "moss_audio_076697ad-7144-11f0-a447-9613c873494c"
    MOSS_AUDIO_SCIENCE_COMMUNICATOR = "moss_audio_737a299c-734a-11f0-918f-4e0486034804"
    MOSS_AUDIO_SASSY_GIRL = "moss_audio_19dbb103-7350-11f0-ad20-f2bc95e89150"
    MOSS_AUDIO_URGENT_WOMAN = "moss_audio_7c7e7ae2-7356-11f0-9540-7ef9b4b62566"
    MOSS_AUDIO_GERMAN_MAN = "moss_audio_570551b1-735c-11f0-b236-0adeeecad052"
    MOSS_AUDIO_SWEET_GIRL = "moss_audio_ad5baf92-735f-11f0-8263-fe5a2fe98ec8"
    MOSS_AUDIO_BORED_HUSBAND = "moss_audio_cedfd4d2-736d-11f0-99be-fe40dd2a5fe8"
    MOSS_AUDIO_WARM_MAN = "moss_audio_a0d611da-737c-11f0-ad20-f2bc95e89150"
    MOSS_AUDIO_QUIET_MAN = "moss_audio_4f4172f4-737b-11f0-9540-7ef9b4b62566"
    MOSS_AUDIO_PRETENTIOUS_WOMAN = "moss_audio_62ca20b0-7380-11f0-99be-fe40dd2a5fe8"

    # Dialogue-content style
    CONVERSATIONAL_FEMALE_1_V1 = "conversational_female_1_v1"
    CONVERSATIONAL_FEMALE_2_V1 = "conversational_female_2_v1"
    SOCIALMEDIA_FEMALE_1_V1 = "socialmedia_female_1_v1"

    # Children's-voice style
    BRITISH_CHILD_MALE_1_V1 = "BritishChild_male_1_v1"
    BRITISH_CHILD_FEMALE_1_V1 = "BritishChild_female_1_v1"

    # High-quality series
    ENGLISH_SWEET_FEMALE_4 = "English_Sweet_Female_4"

    # ===== Chinese Mandarin voices =====
    # Professional-broadcast style
    CHINESE_NEWS_ANCHOR = "Chinese (Mandarin)_News_Anchor"
    CHINESE_MALE_ANNOUNCER = "Chinese (Mandarin)_Male_Announcer"
    CHINESE_RADIO_HOST = "Chinese (Mandarin)_Radio_Host"

    # Business-professional style
    CHINESE_RELIABLE_EXECUTIVE = "Chinese (Mandarin)_Reliable_Executive"
    CHINESE_GENTLEMAN = "Chinese (Mandarin)_Gentleman"
    CHINESE_SINCERE_ADULT = "Chinese (Mandarin)_Sincere_Adult"

    # Everyday-character style
    CHINESE_MATURE_WOMAN = "Chinese (Mandarin)_Mature_Woman"
    CHINESE_KIND_HEARTED_ANTIE = "Chinese (Mandarin)_Kind-hearted_Antie"
    CHINESE_WARM_BESTIE = "Chinese (Mandarin)_Warm_Bestie"
    CHINESE_STUBBORN_FRIEND = "Chinese (Mandarin)_Stubborn_Friend"
    CHINESE_SWEET_LADY = "Chinese (Mandarin)_Sweet_Lady"
    CHINESE_WISE_WOMEN = "Chinese (Mandarin)_Wise_Women"
    CHINESE_GENTLE_YOUTH = "Chinese (Mandarin)_Gentle_Youth"
    CHINESE_WARM_GIRL = "Chinese (Mandarin)_Warm_Girl"
    CHINESE_KIND_HEARTED_ELDER = "Chinese (Mandarin)_Kind-hearted_Elder"
    CHINESE_GENTLE_SENIOR = "Chinese (Mandarin)_Gentle_Senior"
    CHINESE_CRISP_GIRL = "Chinese (Mandarin)_Crisp_Girl"
    CHINESE_STRAIGHTFORWARD_BOY = "Chinese (Mandarin)_Straightforward_Boy"
    CHINESE_PURE_HEARTED_BOY = "Chinese (Mandarin)_Pure-hearted_Boy"

    # Distinctive-character style
    CHINESE_UNRESTRAINED_YOUNG_MAN = "Chinese (Mandarin)_Unrestrained_Young_Man"
    ARROGANT_MISS = "Arrogant_Miss"
    ROBOT_ARMOR = "Robot_Armor"
    HUNYIN_6 = "hunyin_6"
    CHINESE_CUTE_SPIRIT = "Chinese (Mandarin)_Cute_Spirit"
    CHINESE_LYRICAL_VOICE = "Chinese (Mandarin)_Lyrical_Voice"

    # Regional-accent style
    CHINESE_HK_FLIGHT_ATTENDANT = "Chinese (Mandarin)_HK_Flight_Attendant"
    CHINESE_HUMOROUS_ELDER = "Chinese (Mandarin)_Humorous_Elder"
    CHINESE_SOUTHERN_YOUNG_MAN = "Chinese (Mandarin)_Southern_Young_Man"
    CHINESE_SOFT_GIRL = "Chinese (Mandarin)_Soft_Girl"

    # Professional-distinctive style
    CHINESE_INTELLECTUAL_GIRL = "Chinese (Mandarin)_IntellectualGirl"
    CHINESE_WARM_HEARTED_GIRL = "Chinese (Mandarin)_Warm_HeartedGirl"
    CHINESE_LAID_BACK_GIRL = "Chinese (Mandarin)_Laid_BackGirl"
    CHINESE_EXPLORATIVE_GIRL = "Chinese (Mandarin)_ExplorativeGirl"
    CHINESE_WARM_HEARTED_AUNT = "Chinese (Mandarin)_Warm-HeartedAunt"
    CHINESE_BASHFUL_GIRL = "Chinese (Mandarin)_BashfulGirl"


class Emotion(str, Enum):
    """WaveSpeed emotion enum."""
    # Based on the emotion parameter in the official WaveSpeed docs
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    DISGUSTED = "disgusted"
    SURPRISED = "surprised"
    NEUTRAL = "neutral"


_ALLOWED_EMOTIONS = frozenset(e.value for e in Emotion)

# Synonyms the LLM often outputs -> WaveSpeed allowed values
_EMOTION_ALIASES: Dict[str, str] = {
    "calm": Emotion.NEUTRAL.value,
    "peaceful": Emotion.NEUTRAL.value,
    "serene": Emotion.NEUTRAL.value,
    "gentle": Emotion.NEUTRAL.value,
    "professional": Emotion.NEUTRAL.value,
    "confident": Emotion.NEUTRAL.value,
    "serious": Emotion.NEUTRAL.value,
    "warm": Emotion.HAPPY.value,
    "cheerful": Emotion.HAPPY.value,
    "uplifting": Emotion.HAPPY.value,
    "excited": Emotion.HAPPY.value,
    "joyful": Emotion.HAPPY.value,
    "melancholic": Emotion.SAD.value,
    "sorrowful": Emotion.SAD.value,
    "fear": Emotion.FEARFUL.value,
    "scared": Emotion.FEARFUL.value,
    "disgust": Emotion.DISGUSTED.value,
    "surprise": Emotion.SURPRISED.value,
}


def normalize_emotion(emotion: Optional[str], *, default: str = Emotion.NEUTRAL.value) -> str:
    """Normalize emotion to one of WaveSpeed's 7 allowed values."""
    if not emotion or not str(emotion).strip():
        return default
    key = str(emotion).strip().lower()
    if key in _ALLOWED_EMOTIONS:
        return key
    return _EMOTION_ALIASES.get(key, default)


# For tool JSON schema / Pydantic strict validation (the LLM may only pick these 7)
SpeechEmotionLiteral = Literal[
    "happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"
]

# Common CN/EN voice gender labels (used to programmatically check whether the LLM picked a wrong-gender voice)
_ZH_FEMALE_VOICES = frozenset({
    VoiceID.CHINESE_NEWS_ANCHOR.value,
    VoiceID.CHINESE_MATURE_WOMAN.value,
    VoiceID.CHINESE_RADIO_HOST.value,
    VoiceID.CHINESE_SWEET_LADY.value,
    VoiceID.CHINESE_WISE_WOMEN.value,
    VoiceID.CHINESE_WARM_GIRL.value,
})
_ZH_MALE_VOICES = frozenset({
    VoiceID.CHINESE_MALE_ANNOUNCER.value,
    VoiceID.CHINESE_GENTLEMAN.value,
    VoiceID.CHINESE_RELIABLE_EXECUTIVE.value,
    VoiceID.CHINESE_SINCERE_ADULT.value,
    VoiceID.CHINESE_GENTLE_YOUTH.value,
    VoiceID.CHINESE_STRAIGHTFORWARD_BOY.value,
})
_EN_FEMALE_VOICES = frozenset({
    VoiceID.ENGLISH_STEADY_FEMALE_1.value,
    VoiceID.ENGLISH_EXPRESSIVE_NARRATOR.value,
})
_EN_MALE_VOICES = frozenset({
    VoiceID.ENGLISH_MAGNETIC_MALE_2.value,
    VoiceID.ENGLISH_PERSUASIVE_MAN.value,
})


def infer_voice_gender(voice_id: str) -> Optional[str]:
    """Infer 'f' / 'm' / None from voice_id."""
    if not voice_id:
        return None
    if voice_id in _ZH_FEMALE_VOICES or voice_id in _EN_FEMALE_VOICES:
        return "f"
    if voice_id in _ZH_MALE_VOICES or voice_id in _EN_MALE_VOICES:
        return "m"
    lowered = voice_id.lower()
    if any(token in lowered for token in ("_woman", "_girl", "_female", "_lady", "_aunt", "_miss", "sweet_lady")):
        return "f"
    if any(token in lowered for token in ("_man", "_male", "_boy", "_gentleman", "announcer", "executive")):
        return "m"
    if "anchor" in lowered or "host" in lowered:
        return "f"
    return None


def default_voice_for_language_and_gender(
    language: Optional[str],
    gender: str,
) -> str:
    """Return the default voice by language + narrator gender."""
    is_zh = (language or "").lower().startswith("zh")
    if gender == "m":
        return (
            VoiceID.CHINESE_MALE_ANNOUNCER.value
            if is_zh
            else VoiceID.ENGLISH_MAGNETIC_MALE_2.value
        )
    return (
        VoiceID.CHINESE_NEWS_ANCHOR.value
        if is_zh
        else VoiceID.ENGLISH_STEADY_FEMALE_1.value
    )


def _pascal_to_snake(name: str) -> str:
    """PascalCase/camelCase -> snake_case (e.g. Success -> success, ImageUrl -> image_url)."""
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


class ImageModelSwitchedMessageKey(str, Enum):
    """Message key shown to the user on image-model downgrade/switch; the frontend or an outer layer localizes it by language."""
    FALLBACK_DEFAULT = "image_model_switched.fallback_default"


class ImageGenerationResult(BaseModel):
    """Unified image-generation result structure."""
    # ==================== Basic fields ====================
    success: bool = Field(description="是否生成成功")
    image_url: Optional[str] = Field(default=None, description="生成的图像URL")
    generated_prompt: Optional[str] = Field(default=None, description="实际使用的生成提示词")

    # ==================== Provider and model info ====================
    provider: Optional[str] = Field(default=None, description="工具提供商（ToolProvider enum value）")
    model: Optional[str] = Field(default=None, description="使用的模型类型（ToolType enum value）")

    # ==================== Status message ====================
    message: Optional[str] = Field(default=None, description="成功时的状态消息")
    error_msg: Optional[str] = Field(
        default=None,
        description="失败时的用户友好错误消息（由LLM生成，不含供应商信息和技术细节）"
    )
    raw_error_msg: Optional[str] = Field(
        default=None,
        description="原始错误信息（仅内部调试用，不返回前端）"
    )

    # ==================== Generation parameters ====================
    reference_image_urls: Optional[List[str]] = Field(default=None, description="参考图片URL列表（用于I2I模式）")
    seed: Optional[int] = Field(default=None, description="随机种子（用于复现相同结果）")
    aspect_ratio: Optional[str] = Field(default=None, description="图片的宽高比，如 '16:9', '9:16', '1:1' 等")
    resolution: Optional[str] = Field(default=None, description="图片的分辨率，如 '480p', '720p', '1080p' 等")

    # ==================== Billing (written by the tool, read directly by the callback) ====================
    billing_cost: Optional[float] = Field(default=None, description="工具调用成本（美元），由 tool 内部计算后写入，callback 直接累加，避免重复计算")

    # ==================== Downgrade/model switch (used by the wrapper) ====================
    model_switched: Optional[bool] = Field(default=None, description="是否发生过模型降级/切换")
    requested_model: Optional[str] = Field(default=None, description="用户/上下文请求的模型（如 Pro）")
    actual_model: Optional[str] = Field(default=None, description="实际完成请求的模型（若降级则为备模型）")
    user_facing_message: Optional[str] = Field(default=None, description="给用户看的短句，如「已自动使用备用模型完成生成」")
    failure_category: Optional[str] = Field(default=None, description="失败的官方类别（FailureCategory value，如 rate_limited/content_moderation），由分类器写入，用于前端展示不泄密的原因")

    # ==================== Tool dimensions (written by the wrapper, used for the persisted version) ====================
    image_tool_metrics: Optional[Dict[str, Any]] = Field(default=None, description="当次 image wrapper metrics，供 create_character_version/create_keyframe_version 写入 DB")
    tool_duration_sec: Optional[float] = Field(default=None, description="当次 image 工具调用耗时（秒）")
    tool_cost: Optional[float] = Field(default=None, description="当次 image 工具调用成本（美元）")
    applied_skill_ids: List[str] = Field(default_factory=list, description="Skills enforced at the final image-tool boundary")
    constraint_coverage: Dict[str, Any] = Field(default_factory=dict, description="Per-constraint validation audit")
    final_prompt: Optional[str] = Field(default=None, description="Prompt after deterministic hard-constraint merge")

    @model_validator(mode='before')
    @classmethod
    def _normalize_keys_for_llm(cls, data: Any) -> Any:
        """Accept LLM/tool output with PascalCase keys (e.g. Success, Image_url) by normalizing to snake_case."""
        if not isinstance(data, dict):
            return data
        return {_pascal_to_snake(k): v for k, v in data.items()}

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        """Convert to a JSON string."""
        # Remove fields with None values
        data = {k: v for k, v in self.model_dump().items() if v is not None}
        return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)

    @classmethod
    def success_result(
        cls,
        image_url: str,
        generated_prompt: str,
        provider: str,
        message: Optional[str] = None,
        reference_image_urls: Optional[list] = None,
        seed: Optional[int] = None,
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        model: Optional[str] = None,
        error_msg: Optional[str] = None,
        raw_error_msg: Optional[str] = None,
        model_switched: Optional[bool] = None,
        requested_model: Optional[str] = None,
        actual_model: Optional[str] = None,
        user_facing_message: Optional[str] = None,
    ) -> "ImageGenerationResult":
        """Create a success result."""
        return cls(
            success=True,
            image_url=image_url,
            generated_prompt=generated_prompt,
            provider=provider,
            message=message or f"✅ 图像生成成功",
            reference_image_urls=reference_image_urls,
            seed=seed,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=model,
            error_msg=error_msg,
            raw_error_msg=raw_error_msg,
            model_switched=model_switched,
            requested_model=requested_model,
            actual_model=actual_model,
            user_facing_message=user_facing_message,
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: str,
        image_url: Optional[str] = None,
        generated_prompt: Optional[str] = None,
        reference_image_urls: Optional[list] = None,
        seed: Optional[int] = None,
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        model: Optional[str] = None,
        raw_error_msg: Optional[str] = None,
        requested_model: Optional[str] = None,
        user_facing_message: Optional[str] = None,
    ) -> "ImageGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            image_url=image_url,
            generated_prompt=generated_prompt,
            provider=provider,
            error_msg=error_message,
            raw_error_msg=raw_error_msg,
            reference_image_urls=reference_image_urls,
            seed=seed,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=model,
            requested_model=requested_model,
            user_facing_message=user_facing_message,
        )


class CharacterImageAnalysis(BaseModel):
    """Character-image analysis result."""
    matches_character_description: bool
    contains_only_character: bool
    analysis_reason: Optional[str] = None

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        """Convert to a JSON string."""
        data = {k: v for k, v in self.model_dump().items() if v is not None}
        return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)


class CharacterImageGenerationResult(ImageGenerationResult):
    """Character-image generation result, including generation and analysis info."""
    character_analysis: Optional[CharacterImageAnalysis] = None



class VideoGenerationResult(BaseModel):
    """Unified video-generation result structure."""
    success: bool
    video_url: Optional[str] = None
    generated_prompt: Optional[str] = None
    provider: Optional[str] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = Field(default=None, description="宽高比，如 '16:9', '9:16'")
    model: Optional[str] = Field(default=None, description="使用的模型，如 'sora-2', 'sora-2-pro'")
    seed: Optional[int] = None
    message: Optional[str] = None
    error_msg: Optional[str] = Field(
        default=None,
        description="失败时的用户友好错误消息（由LLM生成，不含供应商信息和技术细节）"
    )
    raw_error_msg: Optional[str] = Field(
        default=None,
        description="原始错误信息（仅内部调试用，不返回前端）"
    )
    failure_category: Optional[str] = Field(default=None, description="失败的官方类别（FailureCategory value），由分类器写入，用于前端展示不泄密的原因")

    # ==================== Billing (written by the tool, read directly by the callback) ====================
    billing_cost: Optional[float] = None

    # ==================== Wrapper consistency and timing (aligned with Image; for persistence and admin display) ====================
    video_tool_metrics: Optional[Dict[str, Any]] = None
    tool_duration_sec: Optional[float] = None
    tool_cost: Optional[float] = None

    # lipsync: with-audio preview before stripping the audio track (for the frontend to verify lip-sync/audio)
    preview_video_url: Optional[str] = Field(
        default=None, description="去音轨前的视频 URL（仅 lipsync 有值）"
    )

    # Extra video-related fields
    shot_number: Optional[int] = None
    is_bridge: Optional[bool] = None
    keyframe_url: Optional[str] = None

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        """Convert to a JSON string."""
        # Remove fields with None values
        data = {k: v for k, v in self.model_dump().items() if v is not None}
        return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)

    @classmethod
    def success_result(
        cls,
        video_url: str,
        generated_prompt: str,
        provider: str,
        duration: Optional[float] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        model: Optional[str] = None,
        seed: Optional[int] = None,
        shot_number: Optional[int] = None,
        is_bridge: Optional[bool] = None,
        keyframe_url: Optional[str] = None,
        message: Optional[str] = None
    ) -> "VideoGenerationResult":
        """Create a success result."""
        return cls(
            success=True,
            video_url=video_url,
            generated_prompt=generated_prompt,
            provider=provider,
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            model=model,
            seed=seed,
            shot_number=shot_number,
            is_bridge=is_bridge,
            keyframe_url=keyframe_url,
            message=message or f"✅ {provider}视频生成成功"
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: str,
        shot_number: Optional[int] = None,
        is_bridge: Optional[bool] = None
    ) -> "VideoGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            message=error_message,
            provider=provider,
            shot_number=shot_number,
            is_bridge=is_bridge
        )


class MusicClip(BaseModel):
    """Data structure for a single music clip."""
    clip_id: Optional[str] = None  # optional; the LLM may not return this field
    audio_url: str
    video_url: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[str] = None
    lyrics: Optional[str] = None
    duration: int = 0
    image_url: Optional[str] = None
    created_at: Optional[str] = None
    mv: Optional[str] = None  # Model version: chirp-v4-5, chirp-v4-5-plus, etc.


class MusicGenerationResult(BaseModel):
    """
    Unified music-generation result structure.

    Core fields:
    - success: bool - whether it succeeded
    - clips: List[MusicClip] - list of music clips (Suno returns multiple clips)
    - clips_count: int - number of clips
    - provider: str - provider (suno)
    - generated_prompt: str - the prompt used
    - task_id: str - task ID
    - message: str - status message
    - error: str - error message (on failure)
    """
    success: bool = Field(description="Whether the music generation was successful")
    clips: List[MusicClip] = Field(default_factory=list, description="List of music clips")
    clips_count: int = Field(default=0, description="Number of clips generated")

    # Basic info
    provider: Optional[str] = Field(default=None, description="Music generation provider (suno)")
    generated_prompt: Optional[str] = Field(default=None, description="The prompt actually used")
    task_id: Optional[str] = Field(default=None, description="Task ID for tracking")

    # Status message
    message: Optional[str] = Field(default=None, description="Status message")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    # Generation parameters (store raw params for later use)
    generation_params: Optional[dict] = Field(default=None, description="Generation parameters")

    # ==================== Billing (written by the tool, read directly by the callback) ====================
    billing_cost: Optional[float] = Field(default=None, description="工具调用成本（美元）")

    @field_validator('generation_params', mode='before')
    @classmethod
    def parse_generation_params(cls, v):
        """Process generation_params - parse to a dict if it is a string."""
        if v is None:
            return None
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    @classmethod
    def success_result_with_clips(
        cls,
        clips: List[Dict[str, Any]],
        generated_prompt: str,
        provider: str,
        task_id: Optional[str] = None,
        message: Optional[str] = None,
        generation_params: Optional[dict] = None
    ) -> "MusicGenerationResult":
        """Create a success result (list of clips)."""
        # Convert to MusicClip objects
        music_clips = []
        for clip_data in clips:
            music_clips.append(MusicClip(
                clip_id=clip_data.get("clip_id"),  # use .get() since it may be absent
                audio_url=clip_data["audio_url"],
                video_url=clip_data.get("video_url"),
                title=clip_data.get("title"),
                tags=clip_data.get("tags"),
                lyrics=clip_data.get("lyrics"),
                duration=clip_data.get("duration", 0),
                image_url=clip_data.get("image_url"),
                created_at=clip_data.get("created_at"),
                mv=clip_data.get("mv")
            ))

        return cls(
            success=True,
            clips=music_clips,
            clips_count=len(music_clips),
            generated_prompt=generated_prompt,
            provider=provider,
            task_id=task_id,
            message=message or f"✅ {provider}音乐生成成功，共 {len(music_clips)} 个片段",
            generation_params=generation_params
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: str,
        task_id: Optional[str] = None
    ) -> "MusicGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            clips=[],
            clips_count=0,
            provider=provider,
            task_id=task_id,
            error=error_message,
            message=f"❌ {error_message}"
        )


class SpeechGenerationResult(BaseModel):
    """Unified speech-generation result structure."""
    success: bool
    audio_url: Optional[str] = None
    generated_text: Optional[str] = None
    provider: Optional[str] = None
    voice_id: Optional[str] = None
    emotion: Optional[str] = None
    duration: Optional[float] = None
    message: Optional[str] = None

    # Task-related fields
    task_id: Optional[str] = None
    request_id: Optional[str] = None

    # ==================== Billing (written by the tool, read directly by the callback) ====================
    billing_cost: Optional[float] = None

    speech_tool_metrics: Optional[Dict[str, Any]] = Field(default=None, description="当次 speech wrapper metrics")
    tool_duration_sec: Optional[float] = Field(default=None, description="当次 speech 工具调用耗时（秒）")
    tool_cost: Optional[float] = Field(default=None, description="当次 speech 工具累计成本（美元，含重试）")

    @classmethod
    def success_result(
        cls,
        audio_url: str,
        generated_text: str,
        provider: str,
        voice_id: Optional[str] = None,
        emotion: Optional[str] = None,
        duration: Optional[float] = None,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None,
        message: Optional[str] = None
    ) -> "SpeechGenerationResult":
        """Create a success result."""
        return cls(
            success=True,
            audio_url=audio_url,
            generated_text=generated_text,
            provider=provider,
            voice_id=voice_id,
            emotion=emotion,
            duration=duration,
            task_id=task_id,
            request_id=request_id,
            message=message or f"✅ {provider}语音生成成功"
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: str,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> "SpeechGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            message=error_message,
            provider=provider,
            task_id=task_id,
            request_id=request_id
        )


class AudioGenerationResult(BaseModel):
    """Unified sound-effect-generation result structure."""
    success: bool
    audio_url: Optional[str] = None  # audio-only URL
    video_with_audio_url: Optional[str] = None  # combined video+audio URL
    video_url: Optional[str] = None  # input video URL
    generated_prompt: Optional[str] = None
    provider: Optional[str] = None
    duration: Optional[float] = None
    guidance_scale: Optional[float] = None
    num_inference_steps: Optional[int] = None
    message: Optional[str] = None

    # Task-related fields
    task_id: Optional[str] = None
    request_id: Optional[str] = None

    # ==================== Billing (written by the tool, read directly by the callback) ====================
    billing_cost: Optional[float] = None

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        """Convert to a JSON string."""
        data = {k: v for k, v in self.model_dump().items() if v is not None}
        return json.dumps(data, ensure_ascii=False, indent=indent)

    @classmethod
    def success_result(
        cls,
        video_with_audio_url: str,  # WaveSpeed returns a combined video+audio result
        video_url: str,
        generated_prompt: str,
        provider: str,
        duration: Optional[float] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None,
        message: Optional[str] = None,
        audio_url: Optional[str] = None  # extracted audio-only URL
    ) -> "AudioGenerationResult":
        """Create a success result."""
        return cls(
            success=True,
            audio_url=audio_url,
            video_with_audio_url=video_with_audio_url,
            video_url=video_url,
            generated_prompt=generated_prompt,
            provider=provider,
            duration=duration,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            task_id=task_id,
            request_id=request_id,
            message=message or f"✅ {provider}音效生成成功"
        )

    @classmethod
    def error_result(
        cls,
        error_message: str,
        provider: str,
        video_url: Optional[str] = None,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> "AudioGenerationResult":
        """Create an error result."""
        return cls(
            success=False,
            message=error_message,
            provider=provider,
            video_url=video_url,
            task_id=task_id,
            request_id=request_id
        )
