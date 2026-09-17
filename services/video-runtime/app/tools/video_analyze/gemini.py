"""Gemini video understanding for ``media.video_analyze``.

One pass, one schema, result is the videomap Artifact. Director text lives in
``prompts/media/video-analyze/SKILL.md`` (not the Skill catalog).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GeminiVideoCharacter(BaseModel):
    name: str = Field(description="Visible identity or a short label")
    appearance: str = Field(description="What they look like on screen")
    description: str = Field(default="", description="Look, clothing, and distinguishing features")
    role: str = Field(default="", description="Optional role in the clip")
    appearance_time: str = Field(
        default="",
        description="When they appear, e.g. 0.0-12.5s",
    )


class GeminiVideoStoryboardShot(BaseModel):
    start_sec: float = Field(description="Shot start in seconds")
    end_sec: float = Field(description="Shot end in seconds")
    action: str = Field(description="What happens in this window")
    on_screen: str = Field(default="", description="Who/what is visible")
    production_method: str = Field(
        default="",
        description="How the shot looks made: live-action, CGI, composite, stock, …",
    )
    visual_style: str = Field(default="", description="Look of this shot if distinct")
    camera_angle: str = Field(default="", description="Camera angle or move if visible")
    emotion: str = Field(default="", description="Felt tone of this shot")


class GeminiVideoAnalyzeResult(BaseModel):
    duration_sec: float = Field(description="Clip duration in seconds")
    summary: str = Field(description="Subjects, setting, style, mood, speech or captions")
    theme: str = Field(default="", description="What the clip is about")
    overall_style: str = Field(default="")
    mood: str = Field(default="")
    color_palette: str = Field(default="")
    narrative_structure: str = Field(
        default="",
        description="How the clip is told: single scene, montage, match-cut, …",
    )
    production_techniques: list[str] = Field(
        default_factory=list,
        description="Visible craft: handheld, smash cut, superimposition, grade, VFX, captions",
    )
    visual_elements: list[str] = Field(
        default_factory=list,
        description="Recurring props, locations, or motifs a remake should keep",
    )
    characters: list[GeminiVideoCharacter] = Field(default_factory=list)
    storyboard: list[GeminiVideoStoryboardShot] = Field(default_factory=list)
    spoken_or_on_screen_text: str = Field(default="")
    answer: str = Field(default="", description="Set only when the user asked a question")


async def analyze_video_with_gemini(
    *,
    video_url: Optional[str] = None,
    video_path: Optional[str] = None,
    question: str = "",
    filename: str = "",
    user_input: str = "",
    video_duration_sec: Optional[float] = None,
    language_contract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Upload (or reuse) the video via Files API and return a videomap dict."""
    from google import genai
    from google.genai import types

    from app.utils.file_utils import prepare_video_for_llm
    from app.chat.v2.media_prompts import media_system_instruction
    from app.models.tool_enums import ToolProvider, ToolType
    from app.services.account.account_router import get_account_router

    prepared = await prepare_video_for_llm(
        video_path=video_path,
        video_url=video_url,
        max_wait_time=600,
    )
    if prepared.use_file_uri and prepared.file_uri:
        video_part = types.Part.from_uri(
            file_uri=prepared.file_uri,
            mime_type=prepared.mime_type,
        )
    elif prepared.base64_data:
        import base64

        video_part = types.Part.from_bytes(
            data=base64.b64decode(prepared.base64_data),
            mime_type=prepared.mime_type,
        )
    else:
        raise RuntimeError("media.video_analyze: no file_uri or inline video bytes")

    from app.chat.v2.language import (
        apply_media_analysis_language,
        language_contract_payload,
    )

    contract = language_contract_payload(language_contract)
    facts = {
        "filename": (filename or "").strip(),
        "user_input": (user_input or "").strip(),
        "question": (question or "").strip(),
        "video_duration_sec": (
            round(float(video_duration_sec), 2) if video_duration_sec else None
        ),
    }
    if contract is not None:
        facts["content_language"] = contract["content_language"]
    prompt = (
        "Analyze the attached video. Return JSON matching the schema. "
        "Describe only what is visible or audible. Runtime facts:\n"
        + json.dumps(facts, ensure_ascii=False)
    )
    system_instruction = apply_media_analysis_language(
        media_system_instruction("video-analyze"),
        contract,
    )

    async def _request(api_key: str):
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=600_000),
        )
        return await client.aio.models.generate_content(
            model=ToolType.GEMINI_2_5_FLASH.value,
            contents=types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt), video_part],
            ),
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=GeminiVideoAnalyzeResult,
            ),
        )

    router = await get_account_router()
    response = await router.route_tool_request(
        provider=ToolProvider.GOOGLE,
        tool_type=ToolType.GEMINI_2_5_FLASH,
        request_func=_request,
    )
    raw_result = getattr(response, "parsed", None)
    if raw_result is None and getattr(response, "text", None):
        raw_result = json.loads(response.text)
    if raw_result is None:
        raise RuntimeError("media.video_analyze: Gemini returned no parsed result")
    parsed = (
        raw_result
        if isinstance(raw_result, GeminiVideoAnalyzeResult)
        else GeminiVideoAnalyzeResult.model_validate(raw_result)
    )
    payload = parsed.model_dump()
    if not (question or "").strip():
        payload["answer"] = ""
    if video_duration_sec and payload.get("duration_sec") in (None, 0):
        payload["duration_sec"] = float(video_duration_sec)
    logger.info(
        "media.video_analyze done duration=%s storyboard=%s",
        payload.get("duration_sec"),
        len(payload.get("storyboard") or []),
    )
    return payload
