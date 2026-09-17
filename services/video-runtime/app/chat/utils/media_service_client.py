"""
Cuti-Media-Service HTTP client.

Calls the Media Processing microservice.
All methods are async, take a URL input and return an S3 CDN URL output.
"""

import logging
import time
from typing import Optional

import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception, before_sleep_log,
)

from app.chat.config import settings

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        logger.info(f"🔌 Media service client 初始化: {settings.MEDIA_SERVICE_URL}")
        _client = httpx.AsyncClient(
            base_url=settings.MEDIA_SERVICE_URL,
            timeout=httpx.Timeout(connect=10, read=1200, write=30, pool=10),
        )
    return _client


async def close():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


_RETRYABLE_STATUS = {502, 503, 504}


class _RetryableMediaServiceError(Exception):
    """Wrapper for retryable errors from Media Service."""
    def __init__(self, original: Exception):
        self.original = original
        super().__init__(str(original))


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableMediaServiceError)


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _post(endpoint: str, payload: dict) -> dict:
    client = _get_client()
    url = f"/api/v1/{endpoint}"
    t0 = time.monotonic()
    logger.info(f"📡 MSC >> POST {endpoint}  payload_keys={list(payload.keys())}")
    try:
        resp = await client.post(url, json=payload)
        elapsed_ms = (time.monotonic() - t0) * 1000
        if resp.status_code in _RETRYABLE_STATUS:
            logger.warning(f"📡 MSC !! {endpoint}  {resp.status_code}  {elapsed_ms:.0f}ms (retryable)")
            raise _RetryableMediaServiceError(
                httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
            )
        resp.raise_for_status()
        data = resp.json()
        result_url = data.get("result_url", "")
        summary = f"result_url={result_url[:80]}..." if result_url else f"keys={list(data.keys())}"
        logger.info(f"📡 MSC << {endpoint}  {resp.status_code}  {elapsed_ms:.0f}ms  {summary}")
        return data
    except _RetryableMediaServiceError:
        raise
    except httpx.HTTPStatusError as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.error(f"📡 MSC !! {endpoint}  {e.response.status_code}  {elapsed_ms:.0f}ms  body={e.response.text[:200]}")
        raise
    except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout) as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.warning(f"📡 MSC !! {endpoint}  {elapsed_ms:.0f}ms  {type(e).__name__} (retryable)")
        raise _RetryableMediaServiceError(e)
    except Exception as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.error(f"📡 MSC !! {endpoint}  {elapsed_ms:.0f}ms  {type(e).__name__}: {e}")
        raise


# ─── Image ───────────────────────────────────────────────

async def image_resize(
    image_url: str,
    target_width: int,
    target_height: int,
    run_id: str,
    fmt: str = "webp",
    quality: int = 85,
) -> dict:
    """
    Call the Media Service to downsample/resize an image, returning an S3 CDN URL.
    Returns: {"result_url": "https://cdn.example.test/...", "width": 1344, "height": 768}
    """
    return await _post("image/resize", {
        "image_url": image_url,
        "target_width": target_width,
        "target_height": target_height,
        "format": fmt,
        "quality": quality,
        "run_id": run_id,
    })


async def image_info(image_url: str) -> dict:
    """Get image metadata (width, height)."""
    return await _post("image/info", {"image_url": image_url})


# ─── Video ───────────────────────────────────────────────

async def video_info(video_url: str) -> dict:
    return await _post("video/info", {"video_url": video_url})


async def video_concat(video_urls: list[str], run_id: str, normalize: bool = True) -> dict:
    return await _post("video/concat", {
        "video_urls": video_urls,
        "run_id": run_id,
        "normalize": normalize,
    })


async def video_trim(
    video_url: str,
    target_duration: float,
    run_id: str,
    mode: str = "trim_only",
    tolerance: Optional[float] = None,
) -> dict:
    body: dict = {
        "video_url": video_url,
        "target_duration": target_duration,
        "run_id": run_id,
        "mode": mode,
    }
    if tolerance is not None:
        body["tolerance"] = tolerance
    return await _post("video/trim", body)


async def video_speed_adjust(video_url: str, target_duration: float, run_id: str) -> dict:
    return await _post("video/speed-adjust", {
        "video_url": video_url,
        "target_duration": target_duration,
        "run_id": run_id,
    })


async def video_strip_audio(video_url: str, run_id: str) -> dict:
    return await _post("video/strip-audio", {
        "video_url": video_url,
        "run_id": run_id,
    })


async def video_mix_audio(
    video_url: str, audio_url: str, run_id: str,
    video_volume: float = 0.3, audio_volume: float = 1.0,
    loop_audio: bool = False,
) -> dict:
    payload = {
        "video_url": video_url,
        "audio_url": audio_url,
        "run_id": run_id,
        "video_volume": video_volume,
        "audio_volume": audio_volume,
    }
    if loop_audio:
        payload["loop_audio"] = True
    return await _post("video/mix-audio", payload)


async def video_add_audio(video_url: str, audio_segments: list[dict], run_id: str) -> dict:
    return await _post("video/add-audio", {
        "video_url": video_url,
        "audio_segments": audio_segments,
        "run_id": run_id,
    })


# ─── Audio ───────────────────────────────────────────────

async def audio_info(audio_url: str) -> dict:
    return await _post("audio/info", {"audio_url": audio_url})


async def audio_trim(audio_url: str, start: float, duration: float, run_id: str) -> dict:
    return await _post("audio/trim", {
        "audio_url": audio_url,
        "start": start,
        "duration": duration,
        "run_id": run_id,
    })


async def audio_extract(video_url: str, run_id: str, fmt: str = "wav") -> dict:
    return await _post("audio/extract-from-video", {
        "video_url": video_url,
        "run_id": run_id,
        "format": fmt,
    })


# ─── Pipeline ────────────────────────────────────────────

async def pipeline_segment_process(
    video_urls: list[str],
    target_durations: list[float],
    run_id: str,
    normalize: bool = True,
) -> dict:
    videos = [
        {"url": url, "target_duration": dur}
        for url, dur in zip(video_urls, target_durations)
    ]
    return await _post("pipeline/segment-process", {
        "videos": videos,
        "total_target_duration": sum(target_durations),
        "run_id": run_id,
        "normalize": normalize,
    })


async def pipeline_ensure_on_s3(
    video_url: str,
    run_id: str,
    generation_id: Optional[str] = None,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
    target_fps: Optional[int] = None,
    target_duration: Optional[float] = None,
    strip_audio: bool = False,
    watermark: bool = False,
    force_watermark: bool = False,
) -> dict:
    payload: dict = {
        "external_url": video_url,
        "run_id": run_id,
        "target_width": target_width,
        "target_height": target_height,
    }
    if target_fps:
        payload["target_fps"] = target_fps
    if target_duration is not None and target_duration > 0:
        payload["target_duration"] = target_duration
    if strip_audio:
        payload["strip_audio"] = True
    if watermark:
        payload["watermark"] = True
    if force_watermark:
        payload["force_watermark"] = True
    return await _post("pipeline/ensure-on-s3", payload)


async def workspace_cleanup(run_id: str) -> dict:
    return await _post("pipeline/workspace/cleanup", {"run_id": run_id})
