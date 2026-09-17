from __future__ import annotations

import re
from typing import Any


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_EXPLICIT_SKILL_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[$/]([a-z0-9][a-z0-9-]{0,63})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_LANGUAGE_SKILL_ALIASES = {
    "language-zh": "language-zh",
    "zh": "language-zh",
    "language-en": "language-en",
    "eng": "language-en",
    "en": "language-en",
}
_LANGUAGE_SKILL_OUTPUT = {"language-zh": "zh", "language-en": "en"}

_SPOKEN_EN_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:对话|对白|台词|旁白|口播|配音|语音|角色说话).{0,12}(?:保持|使用|采用|说|为|用)?\s*(?:英文|英语)",
    r"(?:英文|英语)(?:的)?(?:对话|对白|台词|旁白|口播|配音|语音)",
    r"(?:dialogue|dialog|narration|voice[ -]?over|spoken language|speech).{0,16}(?:in|use|remain|keep|be)?\s*english",
    r"english.{0,12}(?:dialogue|dialog|narration|voice[ -]?over|speech)",
    r"(?:人物|角色).{0,8}(?:说|对白|台词).{0,8}(?:英文|英语)",
))
_SPOKEN_ZH_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:对话|对白|台词|旁白|口播|配音|语音|角色说话).{0,12}(?:保持|使用|采用|说|为|用)?\s*(?:中文|汉语|普通话)",
    r"(?:中文|汉语|普通话)(?:的)?(?:对话|对白|台词|旁白|口播|配音|语音)",
    r"(?:dialogue|dialog|narration|voice[ -]?over|spoken language|speech).{0,16}(?:in|use|remain|keep|be)?\s*(?:chinese|mandarin)",
    r"(?:chinese|mandarin).{0,12}(?:dialogue|dialog|narration|voice[ -]?over|speech)",
    r"(?:人物|角色).{0,8}(?:说|对白|台词).{0,8}(?:中文|汉语|普通话)",
))

_VISIBLE_EN_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:所有内容|全部内容|整个作品|用户可见内容|展示内容|输出内容|策划|剧本|文案)(?:全部|所有)?(?:使用|采用|写成|保持|为|用)\s*(?:英文|英语)",
    r"(?:用|使用|采用)?(?:英文|英语)(?:来|进行)?(?:展示|输出|撰写|编写)?(?:所有|全部)?(?:内容|策划|剧本|文案|版本)",
    r"(?:all|every|user[- ]visible).{0,18}(?:output|content|plan|script|text).{0,12}(?:in|use|remain|be)\s*english",
    r"(?:respond|write|display|show|output).{0,12}(?:everything|all content|the plan|the script)?\s*(?:in|as)?\s*english",
))
_VISIBLE_ZH_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:所有内容|全部内容|整个作品|用户可见内容|展示内容|输出内容|策划|剧本|文案)(?:全部|所有)?(?:使用|采用|写成|保持|为|用)\s*(?:中文|汉语|简体中文)",
    r"(?:用|使用|采用)?(?:中文|汉语|简体中文)(?:来|进行)?(?:展示|输出|撰写|编写)?(?:所有|全部)?(?:内容|策划|剧本|文案|版本)",
    r"(?:all|every|user[- ]visible).{0,18}(?:output|content|plan|script|text).{0,12}(?:in|use|remain|be)\s*(?:chinese|mandarin)",
    r"(?:respond|write|display|show|output).{0,12}(?:everything|all content|the plan|the script)?\s*(?:in|as)?\s*(?:chinese|mandarin)",
))
_SUBTITLE_EN_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:字幕|屏幕文字)\s*(?:请|要|需要)?\s*(?:使用|采用|保持|设为|改为|换成|翻译成|为|用|是)?\s*(?:英文|英语)",
    r"(?:英文|英语)(?:的)?(?:字幕|屏幕文字)",
    r"(?:subtitles?|captions?|on[- ]screen text)\s*(?:(?:should|must)\s+)?(?:(?:in|use|remain|be)\s+)?english\b",
))
_SUBTITLE_ZH_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?:字幕|屏幕文字)\s*(?:请|要|需要)?\s*(?:使用|采用|保持|设为|改为|换成|翻译成|为|用|是)?\s*(?:中文|汉语|简体中文)",
    r"(?:中文|汉语|简体中文)(?:的)?(?:字幕|屏幕文字)",
    r"(?:subtitles?|captions?|on[- ]screen text)\s*(?:(?:should|must)\s+)?(?:(?:in|use|remain|be)\s+)?(?:chinese|mandarin)\b",
))


class LanguageSkillConflictError(ValueError):
    """Raised when one message explicitly selects incompatible languages."""


def canonical_language_skill_name(name: str | None) -> str | None:
    return _LANGUAGE_SKILL_ALIASES.get((name or "").strip().lower())


def explicit_language_skill(text: str) -> str | None:
    selected: list[str] = []
    for raw_name in _EXPLICIT_SKILL_RE.findall(text or ""):
        name = canonical_language_skill_name(raw_name)
        if name and name not in selected:
            selected.append(name)
    if len(selected) > 1:
        raise LanguageSkillConflictError(
            "同一条消息只能选择一种语言 Skill；请保留 $language-zh（或 $zh）"
            "与 $language-en（或 $eng）中的一个。"
        )
    return selected[0] if selected else None


def active_language_skill(skills: list[str] | None) -> str | None:
    selected = {
        canonical for name in (skills or [])
        if (canonical := canonical_language_skill_name(name)) is not None
    }
    if len(selected) > 1:
        raise LanguageSkillConflictError("当前任务同时激活了中文和英文语言 Skill。")
    return next(iter(selected), None)


def normalize_output_language(value: str | None) -> str | None:
    """Normalize UI/browser language values to the languages supported by V2."""
    normalized = (value or "").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return None


def canonical_content_language(value: str | None, *, fallback: str = "en-US") -> str:
    """Return the supported BCP-47 content language used by Video Runtime."""
    normalized = normalize_output_language(value)
    if normalized == "zh":
        return "zh-CN"
    if normalized == "en":
        return "en-US"
    return fallback


def explicit_visible_language(text: str) -> str | None:
    """Read an explicit user-visible output request without conflating dialogue."""
    source = text or ""
    english = any(pattern.search(source) for pattern in _VISIBLE_EN_PATTERNS)
    chinese = any(pattern.search(source) for pattern in _VISIBLE_ZH_PATTERNS)
    if english and chinese:
        raise LanguageSkillConflictError("同一条消息不能同时要求全部中文和全部英文输出。")
    if english:
        return "en-US"
    if chinese:
        return "zh-CN"
    return None


def explicit_subtitle_language(text: str) -> str | None:
    """Return an explicitly requested subtitle/on-screen-text language."""
    source = text or ""
    english = any(pattern.search(source) for pattern in _SUBTITLE_EN_PATTERNS)
    chinese = any(pattern.search(source) for pattern in _SUBTITLE_ZH_PATTERNS)
    if english and chinese:
        raise LanguageSkillConflictError("同一条消息不能同时要求中文字幕和英文字幕。")
    if english:
        return "en-US"
    if chinese:
        return "zh-CN"
    return None


def explicit_spoken_language(text: str) -> str | None:
    """Return an explicitly requested dialogue, narration or voice language."""
    source = text or ""
    english_matches = [
        match.group(0) for pattern in _SPOKEN_EN_PATTERNS
        if (match := pattern.search(source)) is not None
    ]
    chinese_matches = [
        match.group(0) for pattern in _SPOKEN_ZH_PATTERNS
        if (match := pattern.search(source)) is not None
    ]
    if english_matches and chinese_matches:
        shortest_english = min(map(len, english_matches))
        shortest_chinese = min(map(len, chinese_matches))
        if shortest_english != shortest_chinese:
            return "en-US" if shortest_english < shortest_chinese else "zh-CN"
        raise LanguageSkillConflictError(
            "同一条消息不能同时要求中文和英文对白或旁白。"
        )
    if english_matches:
        return "en-US"
    if chinese_matches:
        return "zh-CN"
    return None


def resolve_video_language_contract(
    text: str,
    *,
    ui_locale: str | None = None,
    current: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
    language_skill: str | None = None,
) -> dict[str, str]:
    """Resolve independent UI, visible-content, speech, subtitle and provider languages."""
    current = current or {}
    overrides = overrides or {}
    canonical_skill = canonical_language_skill_name(language_skill)
    skill_language = (
        "zh-CN" if canonical_skill == "language-zh" else
        "en-US" if canonical_skill == "language-en" else None
    )
    resolved_ui = canonical_content_language(
        overrides.get("ui_locale") or ui_locale or current.get("ui_locale"),
    )
    explicit_content = explicit_visible_language(text)
    if current:
        inferred_content = canonical_content_language(
            current.get("content_language"), fallback=resolved_ui,
        )
    else:
        inferred_content = canonical_content_language(
            resolve_output_language(text, requested=resolved_ui),
            fallback=resolved_ui,
        )
    content = canonical_content_language(
        overrides.get("content_language") or skill_language or explicit_content or inferred_content,
        fallback=resolved_ui,
    )
    spoken = canonical_content_language(
        overrides.get("spoken_language")
        or skill_language
        or explicit_spoken_language(text)
        or current.get("spoken_language")
        or content,
        fallback=content,
    )
    subtitle = canonical_content_language(
        overrides.get("subtitle_language")
        or explicit_subtitle_language(text)
        or spoken,
        fallback=spoken,
    )
    provider_prompt = str(
        overrides.get("provider_prompt_language")
        or current.get("provider_prompt_language")
        or "auto"
    ).strip() or "auto"
    return {
        "ui_locale": resolved_ui,
        "content_language": content,
        "spoken_language": spoken,
        "subtitle_language": subtitle,
        "provider_prompt_language": provider_prompt,
    }


def video_language_instruction(contract: dict[str, str]) -> str:
    """Render the durable Video Runtime language obligations for the Agent."""
    content = canonical_content_language(contract.get("content_language"))
    visible = "Simplified Chinese" if content == "zh-CN" else "English"
    ui = contract.get("ui_locale", content)
    spoken = contract.get("spoken_language", content)
    subtitle = contract.get("subtitle_language", content)
    provider = contract.get("provider_prompt_language", "auto")
    return (
        "<video_language_contract>\n"
        f"ui_locale={ui}\n"
        f"content_language={content}\n"
        f"spoken_language={spoken}\n"
        f"subtitle_language={subtitle}\n"
        f"provider_prompt_language={provider}\n"
        "</video_language_contract>\n"
        f"Write every user-visible title, summary, plan, script, character/scene/shot description, "
        f"review and final response in {visible}. Keep machine identifiers unchanged. "
        "Dialogue/narration and subtitles follow their independent fields. Provider prompts may "
        "use provider_prompt_language but are internal and must not replace the user-visible artifact. "
        "Preserve this exact contract in ProjectIntent, VideoSpec and every PlanPatch. "
        f"ui_locale is chrome only; do not write user-visible plans in the UI language when it differs from {visible}."
    )


def language_contract_payload(value: Any) -> dict[str, str] | None:
    """Normalize a PlanItem / payload language_contract for host Gemini calls.

    Missing or empty content_language means the caller did not resolve a
    contract; Gemini keeps its previous default (English prose).
    """
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return None
    raw_content = value.get("content_language")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return None
    content = canonical_content_language(raw_content)
    return {
        "ui_locale": canonical_content_language(
            str(value.get("ui_locale") or "") or None, fallback=content,
        ),
        "content_language": content,
        "spoken_language": canonical_content_language(
            str(value.get("spoken_language") or "") or None, fallback=content,
        ),
        "subtitle_language": canonical_content_language(
            str(value.get("subtitle_language") or "") or None, fallback=content,
        ),
        "provider_prompt_language": str(
            value.get("provider_prompt_language") or "auto"
        ).strip() or "auto",
    }


def media_analysis_language_instruction(contract: dict[str, str] | None) -> str:
    """Gemini-only: user-visible analysis prose follows content_language.

    Do not reuse video_language_instruction here; that text is for Terra
    (PlanPatch / identifiers) and would confuse a structured media schema.
    """
    payload = language_contract_payload(contract)
    if payload is None:
        return ""
    content = payload["content_language"]
    visible = "Simplified Chinese" if content == "zh-CN" else "English"
    return (
        f"facts.content_language={content}. "
        f"Write user-visible analysis prose in {visible}: summary, theme, overall_style, "
        "mood, color_palette, narrative_structure, production_techniques, visual_elements, "
        "character name/appearance/description/role, storyboard action/on_screen/"
        "visual_style/camera_angle/emotion, genre, global_emotion, suggested_global_theme, "
        "suggested_color_palette, section musical_features/section_emotion/"
        "suggested_visual_theme/suggested_context, and segment emotion/tempo. "
        "Keep JSON keys and numeric fields unchanged. "
        "Copy sung lyrics, spoken dialogue, and on-screen text exactly as heard or seen; "
        "do not translate them. ui_locale is chrome only and must not choose the "
        "description language."
    )


def apply_media_analysis_language(
    system_instruction: str, contract: dict[str, str] | None,
) -> str:
    extra = media_analysis_language_instruction(contract)
    if not extra:
        return system_instruction
    return f"{system_instruction}\n\n## Output language\n\n{extra}"


def resolve_output_language(
    text: str,
    *,
    requested: str | None = None,
    current: str | None = None,
    language_skill: str | None = None,
) -> str:
    """Resolve visible language from the user message, then UI locale.

    An explicit run-level language Skill wins. Otherwise Chinese script selects
    Chinese and a real English word selects English. Short acknowledgements,
    numbers, and empty text still fall back to current / requested / English.
    """
    canonical = canonical_language_skill_name(language_skill)
    if canonical:
        return _LANGUAGE_SKILL_OUTPUT[canonical]
    source = text or ""
    if _CJK_RE.search(source):
        return "zh"
    if _LATIN_WORD_RE.search(source):
        return "en"
    return (
        normalize_output_language(requested)
        or normalize_output_language(current)
        or "en"
    )


def resolve_spoken_language(
    text: str,
    *,
    output_language: str | None = None,
    language_skill: str | None = None,
) -> str:
    """Resolve dialogue/narration language independently from the UI language.

    A language Skill controls the whole run. Without one, an explicit spoken-language
    request wins over the language inferred for user-visible planning output.
    """
    canonical = canonical_language_skill_name(language_skill)
    if canonical:
        return "zh-CN" if _LANGUAGE_SKILL_OUTPUT[canonical] == "zh" else "en-US"
    explicit = explicit_spoken_language(text)
    if explicit:
        return explicit
    return "zh-CN" if normalize_output_language(output_language) == "zh" else "en-US"


def language_contract(
    language: str | None,
    *,
    provider_prompt_language: str = "auto",
    spoken_language: str | None = None,
) -> dict[str, str]:
    if normalize_output_language(language) == "zh":
        visible = on_screen = "zh-CN"
    else:
        visible = on_screen = "en-US"
    spoken = spoken_language or visible
    return {
        "user_visible_language": visible,
        "spoken_language": spoken,
        "on_screen_text_language": on_screen,
        "provider_prompt_language": provider_prompt_language,
    }


def output_language_instruction(
    language: str | None,
    *,
    provider_prompt_language: str = "auto",
    user_request: str = "",
    language_skill: str | None = None,
) -> str:
    spoken_language = resolve_spoken_language(
        user_request,
        output_language=language,
        language_skill=language_skill,
    )
    contract = language_contract(
        language,
        provider_prompt_language=provider_prompt_language,
        spoken_language=spoken_language,
    )
    spoken_override = (
        " The user's explicit dialogue/narration language is authoritative and "
        "independent from the UI and planning-output language. Preserve it in every "
        "stage, provider prompt, and capability parameter; never translate spoken lines "
        "to the user-visible language."
        if user_request and spoken_language != contract["user_visible_language"]
        else ""
    )
    if normalize_output_language(language) == "zh":
        return (
            "Output language contract: write all user-visible responses, plans, task "
            "titles, artifact titles, summaries, briefs, scripts, shot plans, and review "
            "reports in Simplified Chinese. Keep JSON keys, capability IDs, model IDs, "
            "and other machine-readable identifiers unchanged. A vendor generation prompt "
            "may use another language only when the active Skill or model explicitly requires it. "
            f"Spoken narration/dialogue language: {contract['spoken_language']}."
            f"{spoken_override} "
            f"Requested on-screen copy language: {contract['on_screen_text_language']}. "
            "Do not add narration, dialogue, captions, or on-screen text unless the task calls for them."
        )
    return (
        "Output language contract: write all user-visible responses, plans, task titles, "
        "artifact titles, summaries, briefs, scripts, shot plans, and review reports in "
        "English. Keep JSON keys, capability IDs, model IDs, and other machine-readable "
        "identifiers unchanged. A vendor generation prompt may use another language only "
        "when the active Skill or model explicitly requires it. "
        f"Spoken narration/dialogue language: {contract['spoken_language']}."
        f"{spoken_override} "
        f"Requested on-screen copy language: {contract['on_screen_text_language']}. "
        "Do not add narration, dialogue, captions, or on-screen text unless the task calls for them."
    )
