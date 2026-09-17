"""Native Suno generate — pass-through of API fields, no has_lyrics remapping.

Old path (`generate_music_with_suno` / music agent) is unchanged. This bridge is
used by capability `suno.generate`.
"""
from __future__ import annotations

import logging
from typing import Any

from app.llm.suno_service import SunoService
from app.models.tool_enums import ToolName, ToolProvider, ToolType
from app.services.account.account_router import get_account_router
from app.services.tool_service import ToolService

logger = logging.getLogger(__name__)

_DEFAULT_MV = "chirp-v5-5"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_exclusion(item: str) -> str:
    text = item.strip().strip(",")
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("no ") or lowered.startswith("no,"):
        return text
    return f"no {text}"


def _join_exclusions(tags: str | None, exclude_styles: Any) -> str | None:
    extra: list[str] = []
    if isinstance(exclude_styles, str) and exclude_styles.strip():
        extra.extend(
            part.strip()
            for part in exclude_styles.split(",")
            if part.strip()
        )
    elif isinstance(exclude_styles, list):
        extra.extend(str(item).strip() for item in exclude_styles if str(item).strip())
    normalized = [_normalize_exclusion(item) for item in extra]
    normalized = [item for item in normalized if item]
    if not normalized:
        return tags
    blob = ", ".join(normalized)
    if tags and tags.strip():
        return f"{tags.strip()}, {blob}"
    return blob


def _as_vocal_gender(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in {"f", "female", "女", "女声"}:
        return "f"
    if token in {"m", "male", "男", "男声"}:
        return "m"
    return None


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def generate_suno_native(profile: dict[str, Any]) -> dict[str, Any]:
    """Submit one Suno job with native fields and return a music artifact dict."""
    custom_mode = _as_bool(profile.get("custom_mode"), False)
    if "make_instrumental" in profile:
        make_instrumental = _as_bool(profile.get("make_instrumental"), False)
    else:
        make_instrumental = _as_bool(profile.get("instrumental"), False)
    tags = profile.get("tags") or profile.get("style")
    if not isinstance(tags, str):
        tags = None
    tags = _join_exclusions(tags, profile.get("exclude_styles"))
    mv = str(profile.get("mv") or _DEFAULT_MV).strip() or _DEFAULT_MV
    vocal_gender = _as_vocal_gender(profile.get("vocal_gender"))
    title = profile.get("title")
    title = title.strip() if isinstance(title, str) else None
    target_duration = _as_optional_int(
        profile.get("duration")
        or profile.get("target_duration")
        or profile.get("target_duration_sec")
    )

    lyrics = profile.get("lyrics")
    prompt = profile.get("prompt") or profile.get("gpt_description_prompt")
    if custom_mode:
        lyrics = lyrics or prompt
        gpt_prompt = None
        if not isinstance(lyrics, str) or not lyrics.strip():
            raise ValueError(
                "suno.generate custom_mode=true requires lyrics or prompt "
                "(lyrics box / section tags)"
            )
        lyrics = lyrics.strip()
    else:
        gpt_prompt = prompt if isinstance(prompt, str) else None
        if not gpt_prompt or not gpt_prompt.strip():
            raise ValueError(
                "suno.generate custom_mode=false requires prompt "
                "(gpt_description_prompt / style description)"
            )
        gpt_prompt = gpt_prompt.strip()
        lyrics = None

    generation_params = {
        "custom_mode": custom_mode,
        "make_instrumental": make_instrumental,
        "mv": mv,
        "tags": tags,
        "title": title,
        "target_duration": target_duration,
        # target_duration also goes out as the vendor's `duration`, which only
        # lands near the request — so the poll still picks the closest clip.
        "has_lyrics": (custom_mode and not make_instrumental) or bool(target_duration),
        "auto_lyrics": (not custom_mode) and (not make_instrumental),
    }

    async def _make_suno_request(api_key: str):
        svc = SunoService(api_key=api_key)
        return await svc.generate_music(
            prompt=gpt_prompt,
            custom_mode=custom_mode,
            make_instrumental=make_instrumental,
            lyrics=lyrics,
            mv=mv,
            tags=tags,
            vocal_gender=vocal_gender,
            title=title,
            duration=target_duration,
            generation_params=generation_params,
        )

    router = await get_account_router()
    result = await router.route_tool_request(
        provider=ToolProvider.SUNO,
        tool_type=ToolType.CHIRP_V4_5,
        request_func=_make_suno_request,
    )
    if not getattr(result, "success", False):
        err = getattr(result, "error", None) or getattr(result, "error_message", None) or "Suno generate failed"
        raise RuntimeError(str(err))

    clips = [
        clip
        for clip in (getattr(result, "clips", None) or [])
        if (getattr(clip, "audio_url", "") or "").strip()
    ]
    if not clips:
        raise RuntimeError("Suno returned success but no audio_url")
    first = clips[0]
    audio_url = _clip_field(first, "audio_url")
    clip_title = _clip_field(first, "title")
    clip_id = _clip_field(first, "clip_id")
    clip_lyrics = _clip_field(first, "lyrics") or lyrics
    clip_duration = _clip_field(first, "duration")

    cost = ToolService.calculate_cost(ToolType.CHIRP_V4_5)
    if cost > 0:
        ToolService.log_cost(cost)
        cb = ToolService.get_credit_callback()
        if cb:
            cb.add_tool_cost(cost, tool_name=ToolName.SUNO.value, tool_type=ToolType.CHIRP_V4_5)

    logger.info("suno.generate ok mv=%s custom_mode=%s instrumental=%s", mv, custom_mode, make_instrumental)
    return {
        "audio_url": audio_url,
        "uri": audio_url,
        "title": title or (clip_title.strip() if isinstance(clip_title, str) and clip_title.strip() else "suno.generate"),
        "provider_used": "suno",
        "model": mv,
        "custom_mode": custom_mode,
        "make_instrumental": make_instrumental,
        "tags": tags,
        "clip_id": clip_id,
        "lyrics": clip_lyrics,
        "duration": clip_duration,
        "raw_task_id": getattr(result, "task_id", None),
        "clips_count": len(clips) or getattr(result, "clips_count", None),
        "summary": f"Suno generated music via {mv}",
    }


def _clip_field(clip: Any, key: str) -> Any:
    if isinstance(clip, dict):
        return clip.get(key)
    return getattr(clip, key, None)
