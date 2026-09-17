"""Config-driven video provider bridge (Ark preferred, WaveSpeed fallback).

Vendor-agnostic: Skills request a normalized generate profile; this module
selects the live provider from env keys + DEEP_AGENT_V2_PROVIDER_FALLBACKS_JSON.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
# Magician-facing `model` chooses H3 vs Seedance. `provider` is only the HTTP
# backend (ark | wavespeed). Vendor strings like "minimax" are not backends.
_HTTP_BACKENDS = {"ark", "wavespeed", "wavespeed-seedance-2", "auto"}
DEFAULT_ARK_MODEL = "doubao-seedance-2-0-260128"
DEFAULT_FALLBACKS = {
    "ark": "wavespeed",
    "doubao-seedance-2-0": "wavespeed",
    # Coordinator-facing vendor shorthand. Seedance executions in this
    # deployment are backed by the configured WaveSpeed account.
    "seedance": "wavespeed",
    # The frontend/legacy UserOption calls this route POLLO_SEEDANCE. Deep
    # Agent V2 executes normalized provider profiles through the WaveSpeed
    # bridge, so preserve the user-facing option while resolving its backend.
    "pollo_seedance": "wavespeed",
}

_REMOTE_TASK_ID_RE = re.compile(r"remote_task_id=([A-Za-z0-9_-]+)")
_I2V_MODES = {"i2v", "image_to_video", "image-to-video"}
_FIRST_FRAME_SLOT_PATTERNS = (
    re.compile(
        r"@(?:图片|image)\s*(\d+)\s*(?:作为|用作|为|as|is)\s*"
        r"(?:the\s+)?(?:严格\s*)?(?:首帧|起始帧|first\s+frame|starting\s+frame|start\s+frame)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:首帧|起始帧|first\s+frame|starting\s+frame|start\s+frame)\s*"
        r"(?:(?:使用|采用|设为|是|为|use|uses|is)|[:：])?\s*@(?:图片|image)\s*(\d+)",
        re.IGNORECASE,
    ),
)


class ProviderGenerateError(RuntimeError):
    """Structured provider failure so callers can decide retry vs fallback."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        retryable: bool = False,
        remote_task_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.remote_task_id = remote_task_id
        self.provider = provider
        self.model = model

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "remote_task_id": self.remote_task_id,
            "provider": self.provider,
            "model": self.model,
            "message": str(self),
        }


def _load_fallbacks(raw: str | None) -> dict[str, str]:
    if not raw or not raw.strip():
        return dict(DEFAULT_FALLBACKS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid DEEP_AGENT_V2_PROVIDER_FALLBACKS_JSON; using defaults")
        return dict(DEFAULT_FALLBACKS)
    if not isinstance(data, dict):
        return dict(DEFAULT_FALLBACKS)
    return {str(k).lower(): str(v).lower() for k, v in data.items()}


def resolve_provider(
    requested: str,
    *,
    fallbacks_json: str | None = None,
    ark_key: str | None = None,
    wavespeed_key: str | None = None,
) -> str:
    requested = (requested or "ark").strip().lower()
    # POLLO_SEEDANCE is a legacy frontend/tool selection, not a provider that
    # this bridge can call directly. Canonicalize aliases before applying a
    # deployment-specific fallback map (which may intentionally replace the
    # defaults and therefore omit this compatibility alias).
    requested = {
        "seedance": "wavespeed",
        "pollo_seedance": "wavespeed",
        "wavespeed-seedance-2": "wavespeed",
    }.get(requested, requested)
    ark_key = ark_key if ark_key is not None else os.environ.get("ARK_API_KEY")
    wavespeed_key = (
        wavespeed_key if wavespeed_key is not None else os.environ.get("WAVESPEED_API_KEY")
    )
    fallbacks = _load_fallbacks(fallbacks_json)

    def has_key(provider: str) -> bool:
        if provider == "ark":
            return bool(ark_key)
        if provider in {"wavespeed", "wavespeed-seedance-2"}:
            return bool(wavespeed_key)
        return False

    if requested == "auto":
        if has_key("ark"):
            return "ark"
        if has_key("wavespeed"):
            return "wavespeed"

    if has_key(requested):
        return requested
    # model-prefix match then provider-level fallback
    for key, target in fallbacks.items():
        if requested == key or requested.startswith(key):
            if has_key(target):
                return target
    if requested == "ark" and has_key("wavespeed"):
        return "wavespeed"
    if has_key(requested):
        return requested
    raise RuntimeError(
        f"no API key for provider {requested!r} and no usable fallback "
        f"(need ARK_API_KEY and/or WAVESPEED_API_KEY)"
    )


def _model_family(model: str | None) -> str:
    """Map profile.model → wavespeed handler family."""
    raw = (model or "").strip().lower()
    if not raw or raw in {"ark", "wavespeed", "wavespeed-seedance-2"}:
        return "seedance_2"
    if (
        raw in {"h3", "minimax-h3", "minimax_h3", "minimax-h3-r2v"}
        or "minimax/h3" in raw
        or "h3/reference-to-video" in raw
        or ("minimax" in raw and "h3" in raw)
    ):
        return "minimax_h3"
    if any(token in raw for token in ("2.5", "2-5", "seedance_2_5")):
        return "seedance_2_5"
    if any(token in raw for token in ("1.5", "1-5", "v1.5", "seedance-v1.5", "seedance_v1_5")):
        return "seedance_1_5"
    if any(token in raw for token in ("seedance-2", "seedance_2", "seedance2", "doubao-seedance-2")):
        return "seedance_2"
    if "doubao-seedance" in raw or "seedance" in raw:
        # Unknown seedance variant — refuse silent 2.0 remap.
        raise ValueError(
            f"unsupported Seedance model for WaveSpeed bridge: {model!r}; "
            "use doubao-seedance-2-0 / seedance-2.0 or doubao-seedance-1-5 / seedance-1.5"
        )
    # Non-Seedance labels still default to Seedance 2.0 T2V (legacy profiles).
    return "seedance_2"


def _explicit_video_model_family(value: str | None) -> str | None:
    """Recognize model identifiers that older planners placed in ``provider``."""
    raw = (value or "").strip().lower()
    if raw in {"", "auto", "ark", "wavespeed", "wavespeed-seedance-2", "seedance", "pollo_seedance"}:
        return None
    if "seedance" in raw or raw in {"h3", "minimax-h3", "minimax_h3", "minimax-h3-r2v"}:
        return _model_family(raw)
    if "minimax/h3" in raw or "h3/reference-to-video" in raw:
        return "minimax_h3"
    return None


def _first_media_value(profile: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _prompt_first_frame_slot(prompt: str) -> int | None:
    for pattern in _FIRST_FRAME_SLOT_PATTERNS:
        for match in pattern.finditer(prompt):
            # A substring such as "first-frame:@image1" can belong to "not-first-frame:@image1".
            # Only affirmative frame assignments may promote an identity reference.
            prefix = re.split(r"[。！？.!?;；\n]", prompt[:match.start()])[-1]
            if re.search(
                r"(?:不|非|勿|禁止|不要)[^，,。；;]{0,24}$|"
                r"\b(?:not|never|without|don't|do not)\b[^,;.!?]{0,48}$",
                prefix, re.IGNORECASE,
            ):
                continue
            return int(match.group(1))
    return None


def normalize_video_frame_inputs(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep references separate from a caller's explicit strict first frame."""
    normalized = dict(profile)
    if normalized.get("reference_mode") == "multi_reference":
        if any(normalized.get(key) for key in (
            "start_image_url", "start_image", "first_frame_url", "first_frame",
            "continuity_frame_url", "end_image_url", "end_image", "last_image_url", "last_image",
        )):
            raise ValueError("multi_reference does not accept strict first/last frames; put all images in references")
        normalized["generation_mode"] = "reference_to_video"
        return normalized
    explicit_start = _first_media_value(
        normalized,
        "start_image_url",
        "start_image",
        "first_frame_url",
        "first_frame",
        "continuity_frame_url",
    )
    if explicit_start is None:
        images = normalized.get("images") or normalized.get("reference_images") or []
        slot = _prompt_first_frame_slot(str(normalized.get("prompt") or ""))
        if slot is not None and isinstance(images, list) and 1 <= slot <= len(images):
            candidate = images[slot - 1]
            if isinstance(candidate, str) and candidate.strip():
                explicit_start = candidate.strip()
    if explicit_start is not None:
        normalized["start_image_url"] = explicit_start
        normalized["generation_mode"] = "i2v"
        return normalized
    for key in ("mode", "generation_mode", "task_type"):
        if str(normalized.get(key) or "").strip().lower() in _I2V_MODES:
            normalized[key] = "t2v"
    return normalized


def normalize_video_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Normalize the public video profile before selecting a provider.

    ``duration_seconds`` is the Video Runtime/VideoSpec spelling while the
    provider adapters historically consumed ``duration``.  Keep one canonical
    provider field here so a valid requested duration can never silently fall
    back to the provider default.
    """
    normalized = normalize_video_frame_inputs(profile)
    duration = normalized.get("duration")
    duration_seconds = normalized.get("duration_seconds")
    if duration is not None and duration_seconds is not None:
        if float(duration) != float(duration_seconds):
            raise ValueError(
                "conflicting video duration selectors: "
                f"duration={duration!r}, duration_seconds={duration_seconds!r}"
            )
    requested_duration = duration if duration is not None else duration_seconds
    if requested_duration is not None:
        try:
            numeric_duration = float(requested_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid video duration: {requested_duration!r}") from exc
        if numeric_duration <= 0 or not numeric_duration.is_integer():
            raise ValueError(
                f"video duration must be a positive whole number of seconds: {requested_duration!r}"
            )
        normalized["duration"] = int(numeric_duration)

    requested_provider = str(normalized.get("provider") or "").strip()
    provider_family = _explicit_video_model_family(requested_provider)
    requested_model = str(normalized.get("model") or "").strip()
    if provider_family is None:
        return normalized
    if requested_model and _model_family(requested_model) != provider_family:
        raise ValueError(
            f"conflicting video model selectors: provider={requested_provider!r}, "
            f"model={requested_model!r}"
        )
    normalized["model"] = requested_model or requested_provider
    normalized["provider"] = "wavespeed"
    normalized["requested_provider"] = requested_provider
    return normalized


async def _resolve_media_urls(urls: list[str]) -> list[str]:
    from app.utils.media_egress import resolve_outbound_media_url

    resolved: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        resolved.append(await resolve_outbound_media_url(url.strip()))
    return resolved


def _classify_wavespeed_failure(
    err: str,
    *,
    provider: str,
    model: str | None,
) -> ProviderGenerateError:
    text = (err or "").strip() or "WaveSpeed generate failed"
    remote = None
    match = _REMOTE_TASK_ID_RE.search(text)
    if match:
        remote = match.group(1)
    lower = text.lower()
    if "provider_pending_timeout" in lower or "still processing" in lower:
        return ProviderGenerateError(
            text,
            category="provider_pending_timeout",
            retryable=True,
            remote_task_id=remote,
            provider=provider,
            model=model,
        )
    if "invalid" in lower or "invalid_image_url" in lower:
        return ProviderGenerateError(
            text,
            category="invalid_input",
            retryable=False,
            remote_task_id=remote,
            provider=provider,
            model=model,
        )
    if "rate limit" in lower or "429" in lower:
        return ProviderGenerateError(
            text,
            category="rate_limited",
            retryable=True,
            remote_task_id=remote,
            provider=provider,
            model=model,
        )
    if "insufficient credits" in lower or "insufficient balance" in lower:
        # WaveSpeed returns this explicit 400 when the available account
        # balance cannot cover the prediction price. Retrying the same payload
        # cannot change that balance and only creates noisy duplicate attempts;
        # require a top-up/key change before the task is resumed.
        return ProviderGenerateError(
            text,
            category="insufficient_credits",
            retryable=False,
            remote_task_id=remote,
            provider=provider,
            model=model,
        )
    return ProviderGenerateError(
        text,
        category="provider_explicit_failure",
        retryable=False,
        remote_task_id=remote,
        provider=provider,
        model=model,
    )


RemoteSubmittedCallback = Callable[[str, str], Awaitable[None]]


async def _ark_generate(
    profile: dict[str, Any],
    api_key: str,
    on_remote_submitted: RemoteSubmittedCallback | None = None,
) -> dict[str, Any]:
    prompt = str(profile.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("provider generate requires prompt")
    images = await _resolve_media_urls([
        u for u in (profile.get("images") or profile.get("reference_images") or [])
        if isinstance(u, str) and u.strip()
    ])
    videos = await _resolve_media_urls([
        u for u in (profile.get("videos") or profile.get("reference_videos") or [])
        if isinstance(u, str) and u.strip()
    ])
    audios = await _resolve_media_urls([
        u for u in (profile.get("audios") or profile.get("reference_audios") or [])
        if isinstance(u, str) and u.strip()
    ])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for url in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": url},
            "role": "reference_image",
        })
    for url in videos:
        content.append({
            "type": "video_url",
            "video_url": {"url": url},
        })
    for url in audios:
        content.append({
            "type": "audio_url",
            "audio_url": {"url": url},
        })
    body: dict[str, Any] = {
        "model": str(profile.get("model") or DEFAULT_ARK_MODEL),
        "content": content,
    }
    if profile.get("aspect_ratio") or profile.get("ratio"):
        body["ratio"] = profile.get("aspect_ratio") or profile.get("ratio")
    if profile.get("duration") is not None:
        body["duration"] = int(profile["duration"])
    if profile.get("resolution"):
        body["resolution"] = profile["resolution"]
    if profile.get("generate_audio") is not None:
        body["generate_audio"] = bool(profile["generate_audio"])
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        task_id = profile.get("remote_operation_id")
        if not task_id:
            create = await client.post(ARK_BASE_URL, headers=headers, json=body)
            create.raise_for_status()
            created = create.json()
            task_id = created.get("id") or created.get("task_id")
            if not task_id:
                raise RuntimeError(f"Ark create missing task id: {created}")
            if on_remote_submitted:
                await on_remote_submitted(str(task_id), "ark")
        deadline = time.monotonic() + float(profile.get("timeout_seconds") or 600)
        while time.monotonic() < deadline:
            status_resp = await client.get(f"{ARK_BASE_URL}/{task_id}", headers=headers)
            status_resp.raise_for_status()
            status_body = status_resp.json()
            state = str(status_body.get("status") or "").lower()
            if state in {"succeeded", "success", "completed"}:
                video_url = (
                    status_body.get("content", {}).get("video_url")
                    if isinstance(status_body.get("content"), dict)
                    else None
                )
                video_url = video_url or status_body.get("video_url") or status_body.get("result_url")
                if not video_url:
                    raise RuntimeError(f"Ark succeeded without video_url: {status_body}")
                return {
                    "video_url": video_url,
                    "uri": video_url,
                    "provider_used": "ark",
                    "raw_task_id": task_id,
                    "raw": status_body,
                }
            if state in {"failed", "error", "cancelled"}:
                raise ProviderGenerateError(
                    f"Ark task failed: {status_body}",
                    category="provider_explicit_failure",
                    retryable=False,
                    remote_task_id=str(task_id),
                    provider="ark",
                    model=str(profile.get("model") or DEFAULT_ARK_MODEL),
                )
            await __import__("asyncio").sleep(float(profile.get("poll_interval") or 5))
    raise ProviderGenerateError(
        f"provider_pending_timeout: Ark task still processing; remote_task_id={task_id}",
        category="provider_pending_timeout",
        retryable=True,
        remote_task_id=str(task_id),
        provider="ark",
        model=str(profile.get("model") or DEFAULT_ARK_MODEL),
    )


async def _wavespeed_generate(
    profile: dict[str, Any],
    on_remote_submitted: RemoteSubmittedCallback | None = None,
) -> dict[str, Any]:
    from app.llm.wavespeed_service import get_wavespeed_service

    prompt = str(profile.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("provider generate requires prompt")
    duration = int(profile.get("duration") or 5)
    resolution = str(profile.get("resolution") or "1080p")
    aspect_ratio = profile.get("aspect_ratio") or profile.get("ratio")
    generate_audio = bool(profile.get("generate_audio", True))
    model = str(profile.get("model") or "")
    family = _model_family(model)

    images = await _resolve_media_urls([
        u for u in (profile.get("images") or profile.get("reference_images") or [])
        if isinstance(u, str) and u.strip()
    ])
    start_image_values = await _resolve_media_urls([
        value for value in [_first_media_value(
            profile,
            "start_image_url",
            "start_image",
            "first_frame_url",
            "first_frame",
            "continuity_frame_url",
        )]
        if value
    ])
    end_image_values = await _resolve_media_urls([
        value for value in [_first_media_value(
            profile,
            "end_image_url",
            "end_image",
            "last_image_url",
            "last_image",
        )]
        if value
    ])
    explicit_start_image = start_image_values[0] if start_image_values else None
    explicit_end_image = end_image_values[0] if end_image_values else None
    images = [
        url for url in images
        if url not in {explicit_start_image, explicit_end_image}
    ]
    videos = await _resolve_media_urls([
        u for u in (profile.get("videos") or profile.get("reference_videos") or [])
        if isinstance(u, str) and u.strip()
    ])
    audios = await _resolve_media_urls([
        u for u in (profile.get("audios") or profile.get("reference_audios") or [])
        if isinstance(u, str) and u.strip()
    ])

    i2v_requested = bool(explicit_start_image)
    start_image = explicit_start_image
    end_image = explicit_end_image
    if family == "minimax_h3":
        # Dest H3: look-lock / previous-shot are references, never a locked opening frame.
        i2v_requested = False
        start_image = None
        end_image = None
        if explicit_start_image and explicit_start_image not in images:
            images.insert(0, explicit_start_image)
        if explicit_end_image and explicit_end_image not in images:
            images.append(explicit_end_image)

    svc = get_wavespeed_service()
    logger.info(
        "api-provider-bridge wavespeed: family=%s model=%s refs=%s i2v=%s start=%s end=%s",
        family,
        model or "(default)",
        len(images),
        i2v_requested,
        bool(start_image),
        bool(end_image),
    )
    request_id = str(profile.get("remote_operation_id") or "").strip() or None
    if i2v_requested and images and not request_id:
        # The documented WaveSpeed I2V request accepts image/last_image,
        # not reference_images. Never charge for a degraded identity request.
        raise ValueError(
            "unsupported_start_frame_with_references: WaveSpeed Seedance I2V "
            "cannot submit a strict start frame together with ordinary reference images. "
            "Keep the original identity references; do not silently remove them or "
            "switch providers. Inspect the original frame intent: if the task requests "
            "ordinary references only, correct the input to reference_mode=multi_reference "
            "without strict frame fields and submit a replacement task. If a strict first "
            "frame was explicitly required, preserve that requirement and report the "
            "unsupported combination rather than retrying unchanged parameters."
        )
    created_remote = request_id is None
    try:
        if family == "minimax_h3":
            if not images and not videos:
                raise ValueError(
                    "MiniMax H3 reference-to-video requires at least one image or video"
                )
            request_id = request_id or await svc.create_minimax_h3_r2v_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                reference_images=images or None,
                reference_videos=videos or None,
                reference_audios=audios or None,
            )
            if created_remote and on_remote_submitted:
                await on_remote_submitted(request_id, "wavespeed")
            result = await svc.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration,
                svc.normalize_h3_resolution(resolution), 0,
                end_image=None, strip_audio=not generate_audio,
            )
        elif family == "seedance_2_5":
            if i2v_requested:
                request_id = request_id or await svc.create_seedance_2_5_i2v_task(
                    image=start_image,
                    prompt=prompt,
                    duration=duration,
                    resolution=resolution,
                    last_image=end_image,
                    generate_audio=generate_audio,
                )
            else:
                # T2V is intentional for multi-reference workflows: reference
                # images guide identity/style without becoming a forced first frame.
                request_id = request_id or await svc.create_seedance_2_5_t2v_task(
                    prompt=prompt,
                    duration=duration,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio,
                    reference_images=images or None,
                    reference_videos=videos or None,
                    reference_audios=audios or None,
                )
            if created_remote and on_remote_submitted:
                await on_remote_submitted(request_id, "wavespeed")
            result = await svc.poll_seedance_video_task_until_complete(
                request_id, start_image or (images[0] if images else ""), prompt,
                duration, resolution, 0, end_image=None,
                strip_audio=not generate_audio,
            )
        elif family == "seedance_1_5":
            v15_image = start_image or (images[0] if images else None)
            if not v15_image:
                raise ValueError("Seedance 1.5 Pro requires at least one image")
            request_id = request_id or await svc.create_seedance_v1_5_video_task(
                v15_image, prompt, False, duration,
                resolution if resolution in {"720p", "1080p"} else "720p", -1,
            )
            if created_remote and on_remote_submitted:
                await on_remote_submitted(request_id, "wavespeed")
            result = await svc.poll_seedance_video_task_until_complete(
                request_id, v15_image, prompt, duration, resolution, -1,
                end_image=None,
            )
        elif i2v_requested:
            request_id = request_id or await svc.create_seedance_2_i2v_task(
                image=start_image,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                last_image=end_image,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
            )
            if created_remote and on_remote_submitted:
                await on_remote_submitted(request_id, "wavespeed")
            result = await svc.poll_seedance_video_task_until_complete(
                request_id, start_image, prompt, duration, resolution, 0,
                end_image=None, strip_audio=not generate_audio,
            )
        else:
            # Default continuity path: Seedance 2.0 T2V + optional reference media.
            request_id = request_id or await svc.create_seedance_2_t2v_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                reference_images=images or None,
                reference_videos=videos or None,
                reference_audios=audios or None,
            )
            if created_remote and on_remote_submitted:
                await on_remote_submitted(request_id, "wavespeed")
            result = await svc.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, resolution, 0,
                end_image=None, strip_audio=not generate_audio,
            )
    except Exception as exc:
        if isinstance(exc, ProviderGenerateError):
            raise
        if type(exc).__name__ == "RetryError" and request_id:
            raise ProviderGenerateError(
                f"provider_pending_timeout: WaveSpeed task still processing; remote_task_id={request_id}",
                category="provider_pending_timeout",
                retryable=True,
                remote_task_id=request_id,
                provider="wavespeed",
                model=model or family,
            ) from exc
        if isinstance(exc, ValueError):
            raise
        raise _classify_wavespeed_failure(
            str(exc), provider="wavespeed", model=model or family,
        ) from exc

    video_url = getattr(result, "video_url", None) or getattr(result, "url", None)
    if not video_url:
        err = (
            getattr(result, "error_message", None)
            or getattr(result, "message", None)
            or "WaveSpeed generate failed"
        )
        if request_id and "remote_task_id=" not in str(err):
            err = f"{err}; remote_task_id={request_id}"
        raise _classify_wavespeed_failure(
            str(err),
            provider="wavespeed",
            model=model or family,
        )
    return {
        "video_url": video_url,
        "uri": video_url,
        "provider_used": "wavespeed",
        "model": model or family,
        "model_family": family,
        "generation_mode": "i2v" if i2v_requested else "t2v",
        "start_image_url": start_image,
        "end_image_url": end_image,
        "reference_image_count": len(images),
        "raw_task_id": request_id,
        "raw": result.model_dump() if hasattr(result, "model_dump") else {"video_url": video_url},
    }


async def generate_video(
    profile: dict[str, Any],
    *,
    fallbacks_json: str | None = None,
    on_remote_submitted: RemoteSubmittedCallback | None = None,
) -> dict[str, Any]:
    profile = normalize_video_profile(profile)
    model = str(profile.get("model") or "").strip()
    provider_hint = str(profile.get("provider") or "").strip().lower()
    if provider_hint not in _HTTP_BACKENDS:
        provider_hint = ""
    if not provider_hint:
        if model.startswith("doubao"):
            provider_hint = "ark"
        elif model and _model_family(model) == "minimax_h3":
            provider_hint = "wavespeed"
        else:
            provider_hint = "ark"
    provider = resolve_provider(provider_hint, fallbacks_json=fallbacks_json)
    logger.info(
        "api-provider-bridge: requested=%s resolved=%s model=%s",
        provider_hint,
        provider,
        profile.get("model"),
    )
    if provider == "ark":
        key = os.environ.get("ARK_API_KEY") or ""
        return await _ark_generate(profile, key, on_remote_submitted)
    if provider in {"wavespeed", "wavespeed-seedance-2"}:
        return await _wavespeed_generate(profile, on_remote_submitted)
    raise RuntimeError(f"unsupported resolved provider: {provider}")


def public_http_host_allowlist_for_providers() -> tuple[str, ...]:
    """Domains Skills typically need when calling providers via host.http.request."""
    hosts = set()
    for url in (ARK_BASE_URL, "https://api.wavespeed.ai/"):
        host = urlparse(url).hostname
        if host:
            hosts.add(host)
    return tuple(sorted(hosts))
