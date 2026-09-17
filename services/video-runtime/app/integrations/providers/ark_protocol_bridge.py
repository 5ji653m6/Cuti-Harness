"""Ark Seedance protocol ↔ WaveSpeed adapter (platform-side).

Unmodified Skills (e.g. seedance2/scripts/seedance.py) speak Volcengine Ark
create/status JSON. When ARK_API_KEY is absent (or bridge is forced), HTTP is
redirected to this adapter, which calls WaveSpeed and returns Ark-shaped JSON.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = asyncio.Lock()


def ark_create_body_to_profile(body: dict[str, Any]) -> dict[str, Any]:
    """Map Ark /contents/generations/tasks create payload → provider profile."""
    content = body.get("content") or []
    prompt = ""
    images: list[str] = []
    videos: list[str] = []
    audios: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "text":
                prompt = str(item.get("text") or prompt)
            elif typ == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if isinstance(url, str) and url.strip():
                    images.append(url.strip())
            elif typ == "video_url":
                url = (item.get("video_url") or {}).get("url")
                if isinstance(url, str) and url.strip():
                    videos.append(url.strip())
            elif typ == "audio_url":
                url = (item.get("audio_url") or {}).get("url")
                if isinstance(url, str) and url.strip():
                    audios.append(url.strip())
    duration = body.get("duration")
    if duration is None or int(duration) < 0:
        duration = 5
    return {
        "provider": "ark",
        "model": body.get("model") or "doubao-seedance-2-0-260128",
        "prompt": prompt,
        "duration": int(duration),
        "resolution": body.get("resolution") or "1080p",
        "aspect_ratio": body.get("ratio") or body.get("aspect_ratio") or "16:9",
        "generate_audio": bool(body.get("generate_audio", True)),
        "images": images,
        "videos": videos,
        "audios": audios,
    }


def wavespeed_result_to_ark_status(
    *,
    task_id: str,
    video_url: str,
    profile: dict[str, Any],
    provider_used: str,
    raw_task_id: Any = None,
) -> dict[str, Any]:
    """Shape a WaveSpeed success into Ark Seedance status JSON."""
    return {
        "id": task_id,
        "model": profile.get("model") or "doubao-seedance-2-0-260128",
        "status": "succeeded",
        "duration": profile.get("duration"),
        "resolution": profile.get("resolution"),
        "ratio": profile.get("aspect_ratio") or profile.get("ratio"),
        "content": {
            "video_url": video_url,
        },
        "usage": {},
        "created_at": int(time.time()),
        # Non-Ark extension for debugging; seedance.py ignores unknown fields.
        "cuti_bridge": {
            "provider_used": provider_used,
            "upstream_task_id": raw_task_id,
        },
    }


def ark_failed(task_id: str, message: str, *, code: str = "bridge_error") -> dict[str, Any]:
    return {
        "id": task_id,
        "status": "failed",
        "error": {"code": code, "message": message},
    }


async def create_ark_task_via_wavespeed(
    body: dict[str, Any],
    *,
    fallbacks_json: str | None = None,
) -> dict[str, Any]:
    """Create an Ark-shaped task and run WaveSpeed in the background."""
    from app.chat.v2.provider_bridge import generate_video

    task_id = f"cuti_bridge_{uuid4().hex[:16]}"
    profile = ark_create_body_to_profile(body)
    if not str(profile.get("prompt") or "").strip():
        raise ValueError("Ark create body missing text prompt in content[]")

    async with _TASKS_LOCK:
        _TASKS[task_id] = {
            "id": task_id,
            "status": "running",
            "profile": profile,
            "created_at": int(time.time()),
        }

    async def _run() -> None:
        try:
            # Force WaveSpeed path for protocol bridge (Ark key may be a placeholder).
            bridged = dict(profile)
            bridged["provider"] = "wavespeed"
            result = await generate_video(bridged, fallbacks_json=fallbacks_json)
            video_url = result.get("video_url") or result.get("uri")
            if not video_url:
                raise RuntimeError("WaveSpeed bridge returned no video_url")
            status = wavespeed_result_to_ark_status(
                task_id=task_id,
                video_url=video_url,
                profile=profile,
                provider_used=str(result.get("provider_used") or "wavespeed"),
                raw_task_id=result.get("raw_task_id"),
            )
            async with _TASKS_LOCK:
                _TASKS[task_id] = status
        except Exception as exc:
            logger.exception("ark protocol bridge task %s failed", task_id)
            async with _TASKS_LOCK:
                _TASKS[task_id] = ark_failed(task_id, str(exc))

    asyncio.create_task(_run())
    return {
        "id": task_id,
        "model": profile.get("model"),
        "status": "running",
        "created_at": int(time.time()),
    }


async def get_ark_task(task_id: str) -> dict[str, Any]:
    async with _TASKS_LOCK:
        task = _TASKS.get(task_id)
    if not task:
        return ark_failed(task_id, f"unknown task id: {task_id}", code="not_found")
    return dict(task)


async def delete_ark_task(task_id: str) -> dict[str, Any]:
    async with _TASKS_LOCK:
        _TASKS.pop(task_id, None)
    return {"id": task_id, "status": "cancelled"}


def should_enable_ark_http_bridge(
    *,
    skill_name: str,
    script_path: str,
    force: bool = False,
) -> bool:
    """When True, inject Ark→host redirect for unmodified Skill scripts."""
    if force:
        return True
    if os.environ.get("DEEP_AGENT_V2_ARK_PROTOCOL_BRIDGE", "").lower() in {
        "0", "false", "no", "off",
    }:
        return False
    # Default on when WaveSpeed is available and real Ark key is missing,
    # or when a placeholder bridge key is in use.
    has_ws = bool(os.environ.get("WAVESPEED_API_KEY"))
    ark = os.environ.get("ARK_API_KEY") or ""
    real_ark = bool(ark) and not ark.startswith("cuti-ark-bridge")
    if real_ark and not force:
        return False
    if not has_ws:
        return False
    if skill_name == "seedance2" and script_path.replace("\\", "/").endswith(
        "scripts/seedance.py"
    ):
        return True
    # Any Skill script that targets Ark Seedance CLI naming.
    return script_path.replace("\\", "/").endswith("scripts/seedance.py")


def ark_redirect_sitecustomize() -> bytes:
    """Injected into sandbox PYTHONPATH to rewrite Ark host → host bridge."""
    return textwrap_dedent(
        '''\
        import os
        import urllib.request

        _BRIDGE = os.environ.get("CUTI_ARK_PROTOCOL_BRIDGE_BASE", "").rstrip("/")
        _ARK_PREFIXES = (
            "https://ark.cn-beijing.volces.com",
            "http://ark.cn-beijing.volces.com",
        )
        if _BRIDGE:
            _orig_urlopen = urllib.request.urlopen
            _orig_urlretrieve = urllib.request.urlretrieve

            def _rewrite(url: str) -> str:
                for host in _ARK_PREFIXES:
                    if url.startswith(host):
                        return _BRIDGE + url[len(host):]
                return url

            def urlopen(url, data=None, timeout=None, *args, **kwargs):
                if isinstance(url, urllib.request.Request):
                    original = url.get_full_url()
                    rewritten = _rewrite(original)
                    if rewritten != original:
                        headers = {k: v for k, v in url.header_items()}
                        url = urllib.request.Request(
                            rewritten,
                            data=url.data,
                            headers=headers,
                            method=url.get_method(),
                        )
                else:
                    url = _rewrite(str(url))
                return _orig_urlopen(url, data=data, timeout=timeout, *args, **kwargs)

            def urlretrieve(url, filename=None, reporthook=None, data=None):
                return _orig_urlretrieve(
                    _rewrite(str(url)),
                    filename=filename,
                    reporthook=reporthook,
                    data=data,
                )

            urllib.request.urlopen = urlopen
            urllib.request.urlretrieve = urlretrieve
        '''
    ).encode("utf-8")


def textwrap_dedent(value: str) -> str:
    import textwrap

    return textwrap.dedent(value)
