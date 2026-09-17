"""
WaveSpeed AI image-generation service
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import aiohttp
from datetime import datetime
from tenacity import RetryError, retry, stop_after_delay, wait_fixed, retry_if_exception_type

from app.config import get_settings
from app.models.image_result import (
    SpeechGenerationResult, SpeechProvider, AudioGenerationResult, AudioProvider,
    VideoGenerationResult, VideoProvider, VoiceID, Emotion, normalize_emotion
)
from app.services.agent.utils.cancellation import raise_if_cancelled

if TYPE_CHECKING:
    from app.models.image_result import ImageGenerationResult
from ..utils import media_service_client as msc

logger = logging.getLogger(__name__)


async def _finalize_generated_image(
    image_url: str,
    target_width: Optional[int],
    target_height: Optional[int],
) -> str:
    """Keep a completed provider image when optional post-processing is down."""
    if target_width and target_height and target_width > 0 and target_height > 0:
        try:
            import uuid as _uuid

            resize_result = await asyncio.wait_for(
                msc.image_resize(
                    image_url=image_url,
                    target_width=target_width,
                    target_height=target_height,
                    run_id=_uuid.uuid4().hex[:12],
                ),
                timeout=20,
            )
            result_url = str(resize_result.get("result_url") or "").strip()
            if result_url:
                logger.info("Media service resize+upload: %s", result_url)
                return result_url
            logger.warning("Media service image/resize returned no result_url")
        except Exception as exc:
            logger.warning(
                "Media service image/resize unavailable; preserving provider result: %s",
                exc,
            )

    try:
        from ..utils.s3_utils import s3_utils

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                response.raise_for_status()
                image_data = await response.read()
        return await s3_utils.upload_image(image_data)
    except Exception as exc:
        logger.warning("Direct image persistence unavailable; using provider URL: %s", exc)
        return image_url


def _seedance_poll_limit_seconds() -> int:
    """Seedance 1080p/long videos often exceed 10 minutes; default 30 minutes, overridable via environment variable."""
    raw = (os.getenv("WAVESPEED_SEEDANCE_POLL_SECONDS") or "1800").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1800
    return max(600, value)


async def _validate_generated_video_duration(
    video_url: str,
    requested_duration: float,
    *,
    tolerance_seconds: float = 1.0,
) -> float | None:
    """Probe a persisted provider result and reject material duration drift.

    A probe outage must not discard an otherwise valid, already-paid provider
    result.  A successful probe, however, is authoritative: accepting a 5s
    file for a 15s request corrupts downstream planning and project versions.
    """
    try:
        info = await msc.video_info(video_url)
        actual = float(info.get("duration") or 0.0)
    except Exception as exc:
        logger.warning("Unable to probe generated video duration: %s", exc)
        return None
    if actual <= 0:
        logger.warning("Generated video duration probe returned no usable duration: %s", info)
        return None
    if abs(actual - float(requested_duration)) > tolerance_seconds:
        raise WaveSpeedFinalException(
            "Generated video duration mismatch: "
            f"requested={float(requested_duration):.3f}s, actual={actual:.3f}s"
        )
    return actual


class WaveSpeedRetryException(Exception):
    """Base exception class for WaveSpeed API errors that should be retried."""

    def __init__(self, message: str, retry_after: int = 10, max_retries: int = 30):
        super().__init__(message)
        self.retry_after = retry_after
        self.max_retries = max_retries


class WaveSpeedTaskNotReadyException(WaveSpeedRetryException):
    """Task-not-ready exception - should be retried."""

    def __init__(self, message: str = "Task not ready, please wait"):
        super().__init__(message, retry_after=1, max_retries=60)


class WaveSpeedRateLimitException(WaveSpeedRetryException):
    """API rate-limit exception - should be retried."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, retry_after=retry_after, max_retries=10)


class WaveSpeedServerErrorException(WaveSpeedRetryException):
    """Server-error exception - should be retried."""

    def __init__(self, message: str = "Server error", retry_after: int = 30):
        super().__init__(message, retry_after=retry_after, max_retries=5)


class WaveSpeedFinalException(Exception):
    """WaveSpeed API final-failure exception - should not be retried."""
    pass


def _wavespeed_wait(retry_state) -> float:
    """Get the wait time from the exception's retry_after field, default 1 second."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, WaveSpeedRetryException):
        return float(exc.retry_after)
    return 1.0


class WaveSpeedService:
    """WaveSpeed AI image generation, text-to-speech, sound-effect generation, and lip-sync service."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = os.getenv("WAVESPEED_API_KEY")
        self.base_url = "https://api.wavespeed.ai/api/v3"

        if not self.api_key:
            logger.warning("⚠️ WAVESPEED_API_KEY 未设置")

    # media input field names (WaveSpeed models uniformly use these keys to pass image/video/audio)
    _MEDIA_URL_KEYS = ("image", "last_image", "end_image", "video", "audio", "start_image")
    _MEDIA_LIST_KEYS = (
        "images",
        "reference_images",
        "reference_videos",
        "reference_audios",
    )

    async def _resolve_payload_media(self, payload: dict) -> dict:
        """Uniform pre-submit handling: replace local media URLs in the payload with public URLs WaveSpeed can fetch.

        Under local storage (STORAGE_BACKEND=local), localhost files cannot be fetched remotely; object storage/public URLs pass through automatically.
        The rules live in utils.media_egress, see its docstring. Non-media payloads (T2I/T2V/TTS) lack these keys and are unaffected.
        """
        if not isinstance(payload, dict):
            return payload
        from app.utils.media_egress import resolve_outbound_media_url

        for k in self._MEDIA_URL_KEYS:
            v = payload.get(k)
            if isinstance(v, str) and v:
                payload[k] = await resolve_outbound_media_url(v)
        for k in self._MEDIA_LIST_KEYS:
            v = payload.get(k)
            if isinstance(v, list):
                payload[k] = [
                    await resolve_outbound_media_url(x) if isinstance(x, str) and x else x
                    for x in v
                ]
        return payload

    async def _poll_result(self, task_id: str, max_wait_time: int = 300) -> str:
        """Poll for the task result."""
        url = f"{self.base_url}/predictions/{task_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        start_time = asyncio.get_event_loop().time()
        poll_interval = 1.0  # 1s poll interval
        poll_count = 0

        logger.info(f"🔄 开始轮询 WaveSpeed 任务结果: {task_id}")
        logger.info(f"📍 轮询URL: {url}")
        logger.info(f"⏰ 最大等待时间: {max_wait_time}秒, 轮询间隔: {poll_interval}秒")

        async with aiohttp.ClientSession() as session:
            while asyncio.get_event_loop().time() - start_time < max_wait_time:
                # cooperative cancellation: after the user cancels, promptly abandon the running remote generation (at most one poll interval behind), to avoid extra runs and cost
                await raise_if_cancelled()
                poll_count += 1
                elapsed = asyncio.get_event_loop().time() - start_time

                try:
                    logger.info(f"🔍 第 {poll_count} 次轮询 (已等待 {elapsed:.1f}s): {task_id}")

                    async with session.get(url, headers=headers) as response:
                        logger.info(f"📡 轮询响应状态: {response.status}")

                        if response.status == 200:
                            result = await response.json()
                            logger.debug(f"📋 完整响应数据: {result}")

                            data = result.get("data", {})
                            status = data.get("status", "unknown")

                            logger.info(f"📊 WaveSpeed 任务状态: {status}")

                            if status == "completed":
                                outputs = data.get("outputs", [])
                                if outputs and len(outputs) > 0:
                                    image_url = outputs[0]
                                    logger.info(f"🎉 WaveSpeed 任务完成: {task_id} ({elapsed:.1f}s)")
                                    logger.info(f"🖼️ 生成图片URL: {image_url}")
                                    return image_url
                                else:
                                    logger.error(f"❌ 任务完成但无输出结果: {data}")
                                    raise Exception("任务完成但无输出结果")
                            elif status == "failed":
                                error_msg = data.get("error", "未知错误")
                                logger.error(f"❌ WaveSpeed 任务失败: {error_msg}")
                                logger.error(f"📋 失败详情: {data}")
                                raise Exception(f"任务失败: {error_msg}")
                            elif status in ["pending", "processing", "running", "created"]:
                                logger.info(f"⏳ 任务处理中: {status}")
                            else:
                                logger.warning(f"⚠️ 未知任务状态: {status}")
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ 轮询请求失败: HTTP {response.status}")
                            logger.error(f"📋 错误响应: {error_text}")

                            # if it is an auth error, raise immediately
                            if response.status == 401:
                                raise Exception(f"认证失败: 请检查 WAVESPEED_API_KEY")
                            elif response.status == 404:
                                raise Exception(f"任务不存在: {task_id}")

                except Exception as e:
                    logger.error(f"❌ 轮询异常 (第 {poll_count} 次): {e}")

                    # if it is a fatal error, raise immediately
                    if "认证失败" in str(e) or "任务不存在" in str(e) or "任务失败" in str(e):
                        raise e

                # wait, then keep polling
                logger.info(f"⏸️ 等待 {poll_interval}s 后进行下次轮询...")
                await asyncio.sleep(poll_interval)

            # timeout
            logger.error(f"⏰ 任务超时: {task_id}")
            logger.error(f"📊 轮询统计: 共轮询 {poll_count} 次, 总等待时间 {elapsed:.1f}s")
            raise Exception(f"任务超时: {task_id} (等待时间超过 {max_wait_time} 秒)")

    async def edit_image_seedream(
        self,
        prompt: str,
        images: list,
        size: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> "ImageGenerationResult":
        """
        Edit an image using the WaveSpeed Seedream v4.5 model.

        Args:
            prompt: edit instruction
            images: list of input image URLs
            size: API request size (optional), format 'WIDTH*HEIGHT', meeting Seedream's minimum of 3,686,400 pixels
            target_width: downsample target width (aligned with nano_banana to TARGET_PIXELS)
            target_height: downsample target height

        Returns:
            an ImageGenerationResult object
        """
        from ..models.image_result import ImageGenerationResult, ImageProvider

        if not self.api_key:
            return ImageGenerationResult.error_result(
                error_message="WaveSpeed API key 未配置",
                provider=ImageProvider.WAVESPEED
            )

        if not images:
            return ImageGenerationResult.error_result(
                error_message="至少需要提供一张输入图片",
                provider=ImageProvider.WAVESPEED
            )

        try:
            logger.info(f"🖼️ WaveSpeed Seedream 图像编辑开始")
            logger.info(f"📝 编辑指令: {prompt[:50]}...")
            logger.info(f"🖼️ 输入图片: {len(images)} 张")
            if size:
                logger.info(f"📐 API 尺寸: {size}")

            # submit the edit task
            task_id = await self._submit_seedream_edit_task(prompt, images, size)

            # poll for the result
            image_url = await self._poll_result(task_id)

            final_image_url = await _finalize_generated_image(
                image_url, target_width, target_height,
            )
            logger.info(f"✅ 图像编辑成功: {final_image_url}")

            return ImageGenerationResult.success_result(
                image_url=final_image_url,
                generated_prompt=prompt,
                provider=ImageProvider.WAVESPEED,
                reference_image_urls=images
            )

        except Exception as e:
            logger.error(f"❌ WaveSpeed Seedream 图像编辑失败: {e}")
            return ImageGenerationResult.error_result(
                error_message=f"WaveSpeed Seedream 图像编辑失败: {str(e)}",
                provider=ImageProvider.WAVESPEED
            )

    async def _submit_seedream_edit_task(self, prompt: str, images: list, size: Optional[str] = None) -> str:
        """Submit a Seedream image-edit task."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # use WaveSpeed's Seedream v4.5 edit endpoint
        url = f"{self.base_url}/bytedance/seedream-v4.5/edit"
        payload = {
            "enable_base64_output": False,
            "enable_sync_mode": False,
            "images": images,
            "prompt": prompt
        }

        # add the optional size parameter
        if size is not None:
            payload["size"] = size

        logger.info(f"📤 提交 WaveSpeed Seedream 编辑任务: {prompt[:30]}...")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    task_id = result["data"]["id"]
                    logger.info(f"✅ WaveSpeed Seedream 任务提交成功: {task_id}")
                    return task_id
                else:
                    error_text = await response.text()
                    raise Exception(f"Seedream 任务提交失败: {response.status}, {error_text}")

    async def generate_image_seedream_t2i(
        self,
        prompt: str,
        size: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> "ImageGenerationResult":
        """
        Text-to-image (T2I) using the WaveSpeed Seedream v4.5 model.

        Args:
            prompt: image-generation prompt
            size: API request size (optional), format 'WIDTH*HEIGHT', meeting Seedream's minimum of 3,686,400 pixels
            target_width: downsample target width (aligned to TARGET_PIXELS)
            target_height: downsample target height

        Returns:
            an ImageGenerationResult object
        """
        from ..models.image_result import ImageGenerationResult, ImageProvider

        if not self.api_key:
            return ImageGenerationResult.error_result(
                error_message="WaveSpeed API key 未配置",
                provider=ImageProvider.WAVESPEED
            )

        try:
            logger.info(f"🎨 WaveSpeed Seedream T2I 图像生成开始")
            logger.info(f"📝 生成提示词: {prompt[:50]}...")
            if size:
                logger.info(f"📐 API 尺寸: {size}")

            # submit the T2I generation task
            task_id = await self._submit_seedream_t2i_task(prompt, size)

            # poll for the result
            image_url = await self._poll_result(task_id)

            final_image_url = await _finalize_generated_image(
                image_url, target_width, target_height,
            )
            logger.info(f"✅ 图像生成成功: {final_image_url}")

            return ImageGenerationResult.success_result(
                image_url=final_image_url,
                generated_prompt=prompt,
                provider=ImageProvider.WAVESPEED
            )

        except Exception as e:
            logger.error(f"❌ WaveSpeed Seedream T2I 图像生成失败: {e}")
            return ImageGenerationResult.error_result(
                error_message=f"WaveSpeed Seedream T2I 图像生成失败: {str(e)}",
                provider=ImageProvider.WAVESPEED
            )

    async def _submit_seedream_t2i_task(self, prompt: str, size: Optional[str] = None) -> str:
        """Submit a Seedream T2I image-generation task."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # use WaveSpeed's Seedream v4.5 T2I endpoint
        url = f"{self.base_url}/bytedance/seedream-v4.5"
        payload = {
            "enable_base64_output": False,
            "enable_sync_mode": False,
            "prompt": prompt
        }

        # add the optional size parameter
        if size is not None:
            payload["size"] = size

        logger.info(f"📤 提交 WaveSpeed Seedream T2I 生成任务: {prompt[:30]}...")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    task_id = result["data"]["id"]
                    logger.info(f"✅ WaveSpeed Seedream T2I 任务提交成功: {task_id}")
                    return task_id
                else:
                    error_text = await response.text()
                    raise Exception(f"Seedream T2I 任务提交失败: {response.status}, {error_text}")

    @staticmethod
    def _parse_wavespeed_submit_task_id(result: Dict[str, Any]) -> str:
        """A WaveSpeed v3 submit response may be {data:{id}} or a top-level {id}."""
        data = result.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        tid = result.get("id")
        if tid:
            return str(tid)
        raise ValueError(f"WaveSpeed submit response missing task id: {result!r}")

    async def _submit_gpt_image_2_t2i_task(
        self,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        quality: str,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.base_url}/openai/gpt-image-2/text-to-image"
        payload = {
            "enable_base64_output": False,
            "enable_sync_mode": False,
            "prompt": prompt,
            "quality": quality,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }
        logger.info(f"📤 提交 WaveSpeed GPT Image 2 T2I: aspect_ratio={aspect_ratio}, resolution={resolution}, quality={quality}")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    task_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"✅ WaveSpeed GPT Image 2 T2I 任务提交成功: {task_id}")
                    return task_id
                error_text = await response.text()
                raise Exception(f"GPT Image 2 T2I 提交失败: {response.status}, {error_text}")

    async def generate_image_gpt_image_2_t2i(
        self,
        prompt: str,
        aspect_ratio: str,
        gpt_resolution: str,
        quality: str,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> "ImageGenerationResult":
        """OpenAI GPT Image 2 text-to-image (WaveSpeed)."""
        from ..models.image_result import ImageGenerationResult, ImageProvider

        if not self.api_key:
            return ImageGenerationResult.error_result(
                error_message="WaveSpeed API key 未配置",
                provider=ImageProvider.WAVESPEED
            )

        try:
            logger.info(f"🎨 WaveSpeed GPT Image 2 T2I 开始: {prompt[:50]}...")
            task_id = await self._submit_gpt_image_2_t2i_task(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=gpt_resolution,
                quality=quality,
            )
            image_url = await self._poll_result(task_id)

            final_image_url = await _finalize_generated_image(
                image_url, target_width, target_height,
            )

            return ImageGenerationResult.success_result(
                image_url=final_image_url,
                generated_prompt=prompt,
                provider=ImageProvider.WAVESPEED,
            )
        except Exception as e:
            logger.error(f"❌ WaveSpeed GPT Image 2 T2I 失败: {e}")
            return ImageGenerationResult.error_result(
                error_message=f"WaveSpeed GPT Image 2 T2I 失败: {str(e)}",
                provider=ImageProvider.WAVESPEED,
            )

    async def _submit_gpt_image_2_edit_task(
        self,
        prompt: str,
        images: list,
        aspect_ratio: str,
        resolution: str,
        quality: str,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.base_url}/openai/gpt-image-2/edit"
        payload = {
            "enable_base64_output": False,
            "enable_sync_mode": False,
            "prompt": prompt,
            "images": images,
            "quality": quality,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }
        logger.info(f"📤 提交 WaveSpeed GPT Image 2 Edit: {len(images)} 张图, aspect_ratio={aspect_ratio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    task_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"✅ WaveSpeed GPT Image 2 Edit 任务提交成功: {task_id}")
                    return task_id
                error_text = await response.text()
                raise Exception(f"GPT Image 2 Edit 提交失败: {response.status}, {error_text}")

    async def edit_image_gpt_image_2(
        self,
        prompt: str,
        images: list,
        aspect_ratio: str,
        gpt_resolution: str,
        quality: str,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> "ImageGenerationResult":
        """OpenAI GPT Image 2 image-to-image/edit (WaveSpeed)."""
        from ..models.image_result import ImageGenerationResult, ImageProvider

        if not self.api_key:
            return ImageGenerationResult.error_result(
                error_message="WaveSpeed API key 未配置",
                provider=ImageProvider.WAVESPEED
            )
        if not images:
            return ImageGenerationResult.error_result(
                error_message="至少需要提供一张输入图片",
                provider=ImageProvider.WAVESPEED
            )

        try:
            logger.info(f"🖼️ WaveSpeed GPT Image 2 Edit 开始")
            task_id = await self._submit_gpt_image_2_edit_task(
                prompt=prompt,
                images=images,
                aspect_ratio=aspect_ratio,
                resolution=gpt_resolution,
                quality=quality,
            )
            image_url = await self._poll_result(task_id)

            final_image_url = await _finalize_generated_image(
                image_url, target_width, target_height,
            )

            return ImageGenerationResult.success_result(
                image_url=final_image_url,
                generated_prompt=prompt,
                provider=ImageProvider.WAVESPEED,
                reference_image_urls=images,
            )
        except Exception as e:
            logger.error(f"❌ WaveSpeed GPT Image 2 Edit 失败: {e}")
            return ImageGenerationResult.error_result(
                error_message=f"WaveSpeed GPT Image 2 Edit 失败: {str(e)}",
                provider=ImageProvider.WAVESPEED,
            )

    async def generate_speech(
        self,
        text: str,
        voice_id: str = VoiceID.WISE_WOMAN.value,
        emotion: str = Emotion.HAPPY.value,  # per the docs the default is "happy"
        speed: float = 1.0,  # normal speaking rate
        pitch: int = 0,  # normal pitch
        volume: float = 1.0
    ) -> SpeechGenerationResult:
        """Overall speech-generation method - includes creation and polling."""
        try:
            request_id = await self.create_speech_task(text, voice_id, emotion, speed, pitch, volume)
            return await self.poll_speech_task_until_complete(request_id, text, voice_id, emotion)
        except Exception as e:
            logger.error(f"🔊 语音生成失败: {e}")
            return SpeechGenerationResult.error_result(
                error_message=f"语音生成失败: {str(e)}",
                provider=SpeechProvider.WAVESPEED
            )

    async def create_speech_task(
        self,
        text: str,
        voice_id: str = VoiceID.WISE_WOMAN,
        emotion: str = Emotion.HAPPY,  # per the docs the default is "happy"
        speed: float = 1.0,  # normal speaking rate
        pitch: int = 0,  # normal pitch
        volume: float = 1.0
    ) -> str:
        """Create a text-to-speech task."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")

        url = f"{self.base_url}/minimax/speech-2.5-turbo-preview"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "text": text,
            "voice_id": voice_id,
            "emotion": normalize_emotion(emotion if isinstance(emotion, str) else getattr(emotion, "value", emotion)),
            "speed": speed,
            "pitch": pitch,
            "volume": volume,
            "enable_sync_mode": False,
            "english_normalization": False
        }

        logger.info(f"🔊 创建语音合成任务: {text[:50]}...")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    # WaveSpeed uniform response-format check
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🔊 API 返回错误: {error_msg}")
                        raise Exception(f"语音合成任务创建失败: {error_msg}")

                    request_id = result["data"]["id"]
                    logger.info(f"🔊 语音合成任务创建成功: {request_id}")
                    return request_id
                else:
                    error_text = await response.text()
                    logger.error(f"🔊 语音合成任务创建失败: {response.status}, {error_text}")
                    raise Exception(f"语音合成任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(300),
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_speech_task_until_complete(
        self,
        request_id: str,
        original_text: str,
        voice_id: str,
        emotion: str
    ) -> SpeechGenerationResult:
        """Poll the text-to-speech task until completion."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # handle HTTP errors
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"🔊 API 速率限制，{retry_after}秒后重试")
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)

                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            logger.warning(f"🔊 服务器错误 {e.status}，30秒后重试")
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        else:
                            logger.error(f"🔊 请求失败: {e.status}")
                            raise WaveSpeedFinalException(f"Request failed with status {e.status}")

                    result = await response.json()
                    # WaveSpeed uniform response format: {"code": 200, "message": "success", "data": {...}}
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🔊 API 返回错误: {error_msg}")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")

                    data = result.get("data", {})
                    status = data.get("status", "unknown")

                    logger.info(f"🔊 语音合成任务状态: {status} (请求ID: {request_id})")

                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if outputs and len(outputs) > 0:
                            audio_url = outputs[0]
                            logger.info(f"🔊 语音合成成功: {request_id}")

                            # download and save the audio to S3 (with retry)
                            try:
                                from ..utils.s3_utils import s3_utils
                                generation_id = f"wavespeed_speech_{request_id}"
                                local_audio_url = await s3_utils.download_and_upload_audio_to_s3(
                                    audio_url, generation_id=generation_id
                                )
                                logger.info(f"🔊 保存语音文件到S3成功: {local_audio_url}")
                            except Exception as e:
                                logger.error(f"🔊 保存语音文件到S3失败: {e}")
                                # if saving fails, use the original URL
                                local_audio_url = audio_url

                            # get the audio duration
                            duration = None
                            try:
                                duration = await self._get_audio_duration(local_audio_url)
                                if duration:
                                    logger.info(f"🔊 音频时长: {duration:.2f}秒")
                            except Exception as e:
                                logger.warning(f"🔊 获取音频时长失败: {e}")

                            return SpeechGenerationResult.success_result(
                                audio_url=local_audio_url,
                                generated_text=original_text,
                                provider=SpeechProvider.WAVESPEED,
                                voice_id=voice_id,
                                emotion=emotion,
                                request_id=request_id,
                                duration=duration
                            )
                        else:
                            logger.error(f"🔊 任务完成但无输出结果: {data}")
                            raise WaveSpeedFinalException("任务完成但无输出结果")

                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        logger.error(f"🔊 语音合成任务失败: {error_msg}")
                        raise WaveSpeedFinalException(f"语音合成任务失败: {error_msg}")

                    elif status in ["pending", "processing", "running"]:
                        logger.info(f"🔊 任务处理中: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")

                    else:
                        logger.warning(f"🔊 未知任务状态: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")

        except WaveSpeedRetryException:
            # re-raise the retry exception
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🔊 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🔊 JSON 解析错误: {e}")
            raise WaveSpeedServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🔊 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    async def _get_audio_duration(self, audio_url: str) -> Optional[float]:
        """Get the audio file duration (prefer the media service for the real decoded duration, fall back to local ffprobe on failure)."""
        try:
            from ..utils import media_service_client as msc
            info = await msc.audio_info(audio_url)
            dur = info.get("duration")
            if dur is not None and dur > 0:
                return float(dur)
        except Exception:
            pass
        try:
            from ..utils.file_utils import MediaType, MediaFormat
            from ..utils.s3_utils import convert_media_url_to_s3
            import subprocess
            import json
            import os
            import asyncio

            # fallback: download locally and use ffprobe (metadata duration)
            audio_path_str = await convert_media_url_to_s3(audio_url, MediaType.AUDIO, MediaFormat.LOCAL_PATH)

            if not audio_path_str or not os.path.exists(audio_path_str):
                return None

            def _get_duration_sync():
                try:
                    probe_cmd = [
                        'ffprobe',
                        '-v', 'quiet',
                        '-print_format', 'json',
                        '-show_format',
                        audio_path_str
                    ]

                    probe_result = subprocess.run(
                        probe_cmd,
                        capture_output=True,
                        text=True,
                        check=True
                    )

                    probe_data = json.loads(probe_result.stdout)
                    return float(probe_data['format']['duration'])

                except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
                    return None

            loop = asyncio.get_event_loop()
            duration = await loop.run_in_executor(None, _get_duration_sync)
            from ..utils.file_utils import _safe_unlink
            _safe_unlink(audio_path_str)
            return duration

        except Exception as e:
            logger.error(f"❌ 获取音频时长失败: {e}")
            return None

    async def generate_audio(
        self,
        video_url: str,
        prompt: str,
        duration: float = 8.0,
        guidance_scale: float = 4.5,
        num_inference_steps: int = 25,
        negative_prompt: str = "",
        mask_away_clip: bool = False
    ) -> AudioGenerationResult:
        """Overall sound-effect generation method - includes creation and polling."""
        try:
            request_id = await self.create_audio_task(
                video_url, prompt, duration, guidance_scale,
                num_inference_steps, negative_prompt, mask_away_clip
            )
            return await self.poll_audio_task_until_complete(
                request_id, video_url, prompt, duration, guidance_scale, num_inference_steps
            )
        except Exception as e:
            logger.error(f"🎵 音效生成失败: {e}")
            return AudioGenerationResult.error_result(
                error_message=f"音效生成失败: {str(e)}",
                provider=AudioProvider.WAVESPEED,
                video_url=video_url
            )

    async def create_audio_task(
        self,
        video_url: str,
        prompt: str,
        duration: float = 8.0,
        guidance_scale: float = 4.5,
        num_inference_steps: int = 25,
        negative_prompt: str = "",
        mask_away_clip: bool = False
    ) -> str:
        """Create a sound-effect generation task."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")

        url = f"{self.base_url}/wavespeed-ai/mmaudio-v2"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "duration": duration,
            "guidance_scale": guidance_scale,
            "mask_away_clip": mask_away_clip,
            "negative_prompt": negative_prompt,
            "num_inference_steps": num_inference_steps,
            "prompt": prompt,
            "video": video_url
        }

        logger.info(f"🎵 创建音效生成任务: {prompt[:50]}...")
        logger.info(f"🎵 视频URL: {video_url[:50]}...")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    # WaveSpeed uniform response-format check
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🎵 API 返回错误: {error_msg}")
                        raise Exception(f"音效生成任务创建失败: {error_msg}")

                    request_id = result["data"]["id"]
                    logger.info(f"🎵 音效生成任务创建成功: {request_id}")
                    return request_id
                else:
                    error_text = await response.text()
                    logger.error(f"🎵 音效生成任务创建失败: {response.status}, {error_text}")
                    raise Exception(f"音效生成任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(300),
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_audio_task_until_complete(
        self,
        request_id: str,
        original_video_url: str,
        original_prompt: str,
        duration: float,
        guidance_scale: float,
        num_inference_steps: int
    ) -> AudioGenerationResult:
        """Poll the sound-effect generation task until completion."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # handle HTTP errors
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"🎵 API 速率限制，{retry_after}秒后重试")
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)

                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            logger.warning(f"🎵 服务器错误 {e.status}，30秒后重试")
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        else:
                            logger.error(f"🎵 请求失败: {e.status}")
                            raise WaveSpeedFinalException(f"Request failed with status {e.status}")

                    result = await response.json()
                    # WaveSpeed uniform response format: {"code": 200, "message": "success", "data": {...}}
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🎵 API 返回错误: {error_msg}")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")

                    data = result.get("data", {})
                    status = data.get("status", "unknown")

                    logger.info(f"🎵 音效生成任务状态: {status} (请求ID: {request_id})")

                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if outputs and len(outputs) > 0:
                            audio_url = outputs[0]
                            logger.info(f"🎵 音效生成成功: {request_id}")

                            # download and save the video+audio file to S3 (with retry)
                            # keep the audio track (extract_audio later), no watermark (not the final product)
                            from ..utils.s3_utils import s3_utils
                            generation_id = f"wavespeed_video_with_audio_{request_id}"
                            local_video_with_audio_url = await s3_utils.ensure_video_on_our_s3(
                                audio_url, generation_id=generation_id,
                                strip_audio=False, watermark=False,
                            )
                            logger.info(f"🎵 保存video+audio文件到S3成功: {local_video_with_audio_url}")

                            # extract audio only
                            extracted_audio_url = None
                            try:
                                from ..utils.file_utils import extract_audio_from_video
                                extracted_audio_url = await extract_audio_from_video(
                                    local_video_with_audio_url,
                                    f"extracted_audio_{request_id}"
                                )
                                logger.info(f"🎵 提取纯音频成功: {extracted_audio_url}")
                            except Exception as e:
                                logger.error(f"🎵 提取纯音频失败: {e}")

                            return AudioGenerationResult.success_result(
                                video_with_audio_url=local_video_with_audio_url,
                                audio_url=extracted_audio_url,
                                video_url=original_video_url,
                                generated_prompt=original_prompt,
                                provider=AudioProvider.WAVESPEED,
                                duration=duration,
                                guidance_scale=guidance_scale,
                                num_inference_steps=num_inference_steps,
                                request_id=request_id
                            )
                        else:
                            logger.error(f"🎵 任务完成但无输出结果: {data}")
                            raise WaveSpeedFinalException("任务完成但无输出结果")

                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        logger.error(f"🎵 音效生成任务失败: {error_msg}")
                        raise WaveSpeedFinalException(f"音效生成任务失败: {error_msg}")

                    elif status in ["pending", "processing", "running"]:
                        logger.info(f"🎵 任务处理中: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")

                    else:
                        logger.warning(f"🎵 未知任务状态: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")

        except WaveSpeedRetryException:
            # re-raise the retry exception
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎵 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎵 JSON 解析错误: {e}")
            raise WaveSpeedServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎵 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    async def generate_seedance_video(
        self,
        image: str,
        prompt: str,
        camera_fixed: bool = False,
        duration: int = 5,
        resolution: str = "1080p",
        seed: int = -1,
        end_image: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Overall Seedance video-generation method - includes creation and polling.

        Args:
            image: first-frame image URL
            prompt: video-generation prompt
            camera_fixed: whether the camera is fixed
            duration: video duration
            resolution: resolution
            seed: random seed
            end_image: end-frame image URL (optional, for first/last-frame generation)
        """
        try:
            request_id = await self.create_seedance_video_task(
                image, prompt, camera_fixed, duration, resolution, seed, end_image
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image,
                target_width=target_width, target_height=target_height,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_video_task(
        self,
        image: str,
        prompt: str,
        camera_fixed: bool = False,
        duration: int = 5,
        resolution: str = "1080p",
        seed: int = -1,
        end_image: Optional[str] = None
    ) -> str:
        """Create a Seedance video-generation task.

        Args:
            image: first-frame image URL
            prompt: video-generation prompt
            camera_fixed: whether the camera is fixed
            duration: video duration
            resolution: resolution (480p/720p/1080p)
            seed: random seed
            end_image: end-frame image URL (optional, for first/last-frame generation)
        """
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")

        # if end_image is provided, use the lite model, otherwise the pro-fast model
        if end_image:
            # pick the corresponding lite model by resolution
            if resolution not in ["480p", "720p", "1080p"]:
                resolution = "1080p"
                logger.info(f"⚠️ 分辨率不支持，默认使用1080p")
            url = f"{self.base_url}/bytedance/seedance-v1-lite-i2v-{resolution}"
            logger.info(f"🎬 使用Seedance Lite模型支持首尾帧生成: seedance-v1-lite-i2v-{resolution}")
        else:
            url = f"{self.base_url}/bytedance/seedance-v1-pro-fast/image-to-video"
            logger.info(f"🎬 使用Seedance Pro Fast模型生成视频")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "camera_fixed": camera_fixed,
            "duration": duration,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
            "seed": seed
        }

        # if there is an end_image, add it to the payload's last_image field
        if end_image:
            payload["last_image"] = end_image
            logger.info(f"🎬 添加尾帧图片: {end_image[:50]}...")

        logger.info(f"🎬 创建Seedance视频生成任务: {prompt[:50]}...")
        logger.info(f"🎬 图片URL: {image[:50]}...")
        logger.info(f"🎬 分辨率: {resolution}, 时长: {duration}s, 固定相机: {camera_fixed}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    # WaveSpeed uniform response-format check
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🎬 API 返回错误: {error_msg}")
                        raise Exception(f"Seedance视频生成任务创建失败: {error_msg}")

                    request_id = result["data"]["id"]
                    logger.info(f"🎬 Seedance视频生成任务创建成功: {request_id}")
                    return request_id
                else:
                    error_text = await response.text()
                    logger.error(f"🎬 Seedance视频生成任务创建失败: {response.status}, {error_text}")
                    raise Exception(f"Seedance视频生成任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_v1_5_video(
        self,
        image: str,
        prompt: str,
        camera_fixed: bool = False,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Seedance v1.5 Pro (image-to-video-fast): create + poll, 720p/1080p only, no audio by default."""
        request_id = None
        try:
            request_id = await self.create_seedance_v1_5_video_task(
                image, prompt, camera_fixed, duration, resolution, seed
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
            )
        except RetryError:
            logger.error(
                "🎬 Seedance v1.5 仍在 processing，本地轮询超时 remote_task_id=%s",
                request_id,
            )
            return VideoGenerationResult.error_result(
                error_message=(
                    "provider_pending_timeout: Seedance v1.5 still processing "
                    f"after poll limit; remote_task_id={request_id}; retryable=true"
                ),
                provider=VideoProvider.WAVESPEED,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance v1.5 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance v1.5 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_v1_5_video_task(
        self,
        image: str,
        prompt: str,
        camera_fixed: bool = False,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1
    ) -> str:
        """Create a Seedance v1.5 Pro (image-to-video-fast) task. 720p/1080p only, generate_audio=False."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info(f"⚠️ v1.5 仅支持 720p/1080p，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-v1.5-pro/image-to-video-fast"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "duration": duration,
            "resolution": resolution,
            "generate_audio": False,
            "camera_fixed": camera_fixed,
            "seed": seed,
            "image": image,
            "prompt": prompt,
        }
        logger.info(f"🎬 Seedance v1.5 Pro Fast 创建任务: {prompt[:50]}...")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 Seedance v1.5 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"Seedance v1.5 任务创建失败: {response.status}, {error_text}")

    async def create_seedance_2_i2v_turbo_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = False,
    ) -> str:
        """Create a Seedance 2.0 Image-to-Video Turbo task. API 720p/1080p only; duration 4-15s; generate_audio=False by default."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 Turbo 仅支持 720p/1080p，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0/image-to-video-turbo"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
        }
        if last_image:
            payload["last_image"] = last_image
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        logger.info(f"🎬 Seedance 2.0 Turbo 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 Turbo 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 Turbo 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 Turbo 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_i2v_turbo(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        generate_audio: bool = False,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Image-to-Video Turbo: create + poll."""
        try:
            request_id = await self.create_seedance_2_i2v_turbo_task(
                image=image,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                last_image=last_image,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 Turbo 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 Turbo 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_fast_i2v_turbo_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = False,
    ) -> str:
        """Create a Seedance 2.0 Fast Image-to-Video Turbo task. API 720p/1080p only; duration 4-15s; generate_audio=False by default."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 Fast Turbo 仅支持 720p/1080p，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0-fast/image-to-video-turbo"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
        }
        if last_image:
            payload["last_image"] = last_image
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        logger.info(f"🎬 Seedance 2.0 Fast Turbo 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 Fast Turbo 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 Fast Turbo 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 Fast Turbo 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_fast_i2v_turbo(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        generate_audio: bool = False,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Fast Image-to-Video Turbo: create + poll; shares the polling logic with v1.5."""
        try:
            request_id = await self.create_seedance_2_fast_i2v_turbo_task(
                image=image,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                last_image=last_image,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 Fast Turbo 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 Fast Turbo 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_5_i2v_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        generate_audio: bool = True,
    ) -> str:
        """Create a Seedance 2.5 image-to-video prediction (4–30s)."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(30, duration))
        if resolution not in ("480p", "720p", "1080p", "4k"):
            resolution = "720p"
        url = f"{self.base_url}/bytedance/seedance-2.5/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "generate_audio": generate_audio,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
        }
        if last_image:
            payload["last_image"] = last_image
        payload = await self._resolve_payload_media(payload)
        logger.info(
            "🎬 Seedance 2.5 I2V 创建任务: %s..., duration=%ss, res=%s, audio=%s",
            prompt[:50], duration, resolution, generate_audio,
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    return self._parse_wavespeed_submit_task_id(result)
                error_text = await response.text()
                raise Exception(
                    f"Seedance 2.5 I2V 任务创建失败: {response.status}, {error_text}"
                )

    async def create_seedance_2_5_t2v_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a Seedance 2.5 text-to-video prediction with references."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(30, duration))
        if resolution not in ("480p", "720p", "1080p", "4k"):
            resolution = "720p"
        url = f"{self.base_url}/bytedance/seedance-2.5/text-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "generate_audio": generate_audio,
            "prompt": prompt,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if reference_images:
            payload["reference_images"] = reference_images
        if reference_videos:
            payload["reference_videos"] = reference_videos
        if reference_audios:
            payload["reference_audios"] = reference_audios
        payload = await self._resolve_payload_media(payload)
        logger.info(
            "🎬 Seedance 2.5 T2V 创建任务: %s..., duration=%ss, res=%s, audio=%s",
            prompt[:50], duration, resolution, generate_audio,
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    return self._parse_wavespeed_submit_task_id(result)
                error_text = await response.text()
                raise Exception(
                    f"Seedance 2.5 T2V 任务创建失败: {response.status}, {error_text}"
                )

    async def create_seedance_2_i2v_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = False,
    ) -> str:
        """Create a Seedance 2.0 Image-to-Video task. API 480p/720p/1080p; duration 4-15s; generate_audio=False by default."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("480p", "720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 I2V 分辨率不支持，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
        }
        if last_image:
            payload["last_image"] = last_image
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        logger.info(f"🎬 Seedance 2.0 I2V 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 I2V 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 I2V 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 I2V 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_i2v(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        generate_audio: bool = False,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Image-to-Video: create + poll; shares the polling logic with Fast."""
        request_id = None
        try:
            request_id = await self.create_seedance_2_i2v_task(
                image=image,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                last_image=last_image,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except RetryError:
            logger.error(
                "🎬 Seedance 2.0 I2V 仍在 processing，本地轮询超时 remote_task_id=%s",
                request_id,
            )
            return VideoGenerationResult.error_result(
                error_message=(
                    "provider_pending_timeout: Seedance 2.0 I2V still processing "
                    f"after poll limit; remote_task_id={request_id}; retryable=true"
                ),
                provider=VideoProvider.WAVESPEED,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 I2V 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 I2V 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_t2v_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a Seedance 2.0 Text-to-Video task. API 480p/720p/1080p; duration 4-15s; generate_audio defaults to True; supports reference_images/videos/audios."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("480p", "720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 T2V 分辨率不支持，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0/text-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "prompt": prompt,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if reference_images:
            payload["reference_images"] = reference_images
        if reference_videos:
            payload["reference_videos"] = reference_videos
        if reference_audios:
            payload["reference_audios"] = reference_audios
        logger.info(f"🎬 Seedance 2.0 T2V 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 T2V 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 T2V 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 T2V 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_t2v(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Text-to-Video: create + poll; shares the polling logic with I2V."""
        request_id = None
        try:
            request_id = await self.create_seedance_2_t2v_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                reference_audios=reference_audios,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except RetryError:
            logger.error(
                "🎬 Seedance 2.0 T2V 仍在 processing，本地轮询超时 remote_task_id=%s",
                request_id,
            )
            return VideoGenerationResult.error_result(
                error_message=(
                    "provider_pending_timeout: Seedance 2.0 T2V still processing "
                    f"after poll limit; remote_task_id={request_id}; retryable=true"
                ),
                provider=VideoProvider.WAVESPEED,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 T2V 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 T2V 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_fast_t2v_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a Seedance 2.0 Fast Text-to-Video task. API 480p/720p/1080p; duration 4-15s; generate_audio defaults to True; supports reference_images/videos/audios."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("480p", "720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 Fast T2V 分辨率不支持，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0-fast/text-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "prompt": prompt,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if reference_images:
            payload["reference_images"] = reference_images
        if reference_videos:
            payload["reference_videos"] = reference_videos
        if reference_audios:
            payload["reference_audios"] = reference_audios
        logger.info(f"🎬 Seedance 2.0 Fast T2V 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 Fast T2V 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 Fast T2V 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 Fast T2V 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_fast_t2v(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Fast Text-to-Video: create + poll; shares the polling logic with T2V/I2V."""
        try:
            request_id = await self.create_seedance_2_fast_t2v_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                reference_audios=reference_audios,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 Fast T2V 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 Fast T2V 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_t2v_turbo_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a Seedance 2.0 Text-to-Video Turbo task. API 720p/1080p only; duration 4-15s; generate_audio defaults to True; supports reference_images/videos/audios."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 T2V Turbo 仅支持 720p/1080p，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0/text-to-video-turbo"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "prompt": prompt,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if reference_images:
            payload["reference_images"] = reference_images
        if reference_videos:
            payload["reference_videos"] = reference_videos
        if reference_audios:
            payload["reference_audios"] = reference_audios
        logger.info(f"🎬 Seedance 2.0 T2V Turbo 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 T2V Turbo 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 T2V Turbo 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 T2V Turbo 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_t2v_turbo(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Text-to-Video Turbo: create + poll; shares the polling logic with T2V/I2V."""
        try:
            request_id = await self.create_seedance_2_t2v_turbo_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                reference_audios=reference_audios,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 T2V Turbo 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 T2V Turbo 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_fast_t2v_turbo_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a Seedance 2.0 Fast Text-to-Video Turbo task. API 720p/1080p only; duration 4-15s; generate_audio defaults to True; supports reference_images/videos/audios."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 Fast T2V Turbo 仅支持 720p/1080p，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0-fast/text-to-video-turbo"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "prompt": prompt,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if reference_images:
            payload["reference_images"] = reference_images
        if reference_videos:
            payload["reference_videos"] = reference_videos
        if reference_audios:
            payload["reference_audios"] = reference_audios
        logger.info(f"🎬 Seedance 2.0 Fast T2V Turbo 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 Fast T2V Turbo 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 Fast T2V Turbo 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 Fast T2V Turbo 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_fast_t2v_turbo(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = True,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Fast Text-to-Video Turbo: create + poll; shares the polling logic with T2V/I2V."""
        try:
            request_id = await self.create_seedance_2_fast_t2v_turbo_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                reference_audios=reference_audios,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 Fast T2V Turbo 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 Fast T2V Turbo 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_seedance_2_fast_i2v_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        generate_audio: bool = False,
    ) -> str:
        """Create a Seedance 2.0 Fast Image-to-Video task. API 480p/720p/1080p; duration 4-15s; generate_audio=False by default."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, duration))
        if resolution not in ("480p", "720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ Seedance 2.0 Fast I2V 分辨率不支持，使用 720p")
        url = f"{self.base_url}/bytedance/seedance-2.0-fast/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "duration": duration,
            "enable_web_search": False,
            "generate_audio": generate_audio,
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
        }
        if last_image:
            payload["last_image"] = last_image
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        logger.info(f"🎬 Seedance 2.0 Fast I2V 创建任务: {prompt[:50]}..., duration={duration}s, res={resolution}, audio={generate_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 Seedance 2.0 Fast I2V 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 Seedance 2.0 Fast I2V 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"Seedance 2.0 Fast I2V 任务创建失败: {response.status}, {error_text}")

    async def generate_seedance_2_fast_i2v(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        last_image: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        generate_audio: bool = False,
    ) -> VideoGenerationResult:
        """Seedance 2.0 Fast Image-to-Video: create + poll; shares the polling logic with Turbo."""
        try:
            request_id = await self.create_seedance_2_fast_i2v_task(
                image=image,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                last_image=last_image,
                aspect_ratio=aspect_ratio,
                generate_audio=generate_audio,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=not generate_audio,
            )
        except Exception as e:
            logger.error(f"🎬 Seedance 2.0 Fast I2V 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Seedance 2.0 Fast I2V 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(_seedance_poll_limit_seconds()),
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_seedance_video_task_until_complete(
        self,
        request_id: str,
        original_image: str,
        original_prompt: str,
        duration: int,
        resolution: str,
        seed: int,
        end_image: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        strip_audio: bool = True,
    ) -> VideoGenerationResult:
        """Poll the Seedance video-generation task until completion.

        Args:
            request_id: task ID
            original_image: first-frame image URL
            original_prompt: video-generation prompt
            duration: video duration
            resolution: resolution
            seed: random seed
            end_image: end-frame image URL (optional, for first/last-frame generation)
            strip_audio: whether to strip the audio track during S3-normalization upload. Default True (I2V multi-shot concat workflow needs a uniform no-audio track);
                native-audio T2V (generate_audio=True) direct-generation should pass False to keep audio.
        """
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # handle HTTP errors
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"🎬 API 速率限制，{retry_after}秒后重试")
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)

                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            logger.warning(f"🎬 服务器错误 {e.status}，30秒后重试")
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        else:
                            logger.error(f"🎬 请求失败: {e.status}")
                            raise WaveSpeedFinalException(f"Request failed with status {e.status}")

                    result = await response.json()
                    # WaveSpeed uniform response format: {"code": 200, "message": "success", "data": {...}}
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        logger.error(f"🎬 API 返回错误: {error_msg}")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")

                    data = result.get("data", {})
                    status = data.get("status", "unknown")

                    logger.info(f"🎬 视频生成任务状态: {status} (请求ID: {request_id})")

                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if outputs and len(outputs) > 0:
                            video_url = outputs[0]
                            logger.info(f"🎬 视频生成成功: {request_id}")
                            from ..utils.s3_utils import s3_utils
                            import uuid
                            generation_id = f"seedance_{request_id}_{uuid.uuid4().hex[:8]}"
                            local_video_url = await s3_utils.ensure_video_on_our_s3(
                                video_url,
                                generation_id=generation_id,
                                target_width=target_width,
                                target_height=target_height,
                                strip_audio=strip_audio,
                            )
                            logger.info(f"✅ 视频已上传到S3: {local_video_url}")
                            actual_duration = await _validate_generated_video_duration(
                                local_video_url,
                                float(duration),
                            )
                            return VideoGenerationResult.success_result(
                                video_url=local_video_url,
                                generated_prompt=original_prompt,
                                provider=VideoProvider.WAVESPEED,
                                duration=actual_duration or float(duration),
                                resolution=resolution,
                                seed=seed,
                                message=f"✅ WaveSpeed 视频生成成功"
                            )
                        else:
                            logger.error(f"🎬 任务完成但无输出结果: {data}")
                            raise WaveSpeedFinalException("任务完成但无输出结果")

                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        logger.error(f"🎬 视频生成任务失败: {error_msg}")
                        raise WaveSpeedFinalException(f"视频生成任务失败: {error_msg}")

                    elif status in ["pending", "processing", "running"]:
                        logger.info(f"🎬 任务处理中: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")

                    else:
                        logger.warning(f"🎬 未知任务状态: {status}")
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")

        except WaveSpeedRetryException:
            # re-raise the retry exception
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎬 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎬 JSON 解析错误: {e}")
            raise WaveSpeedServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎬 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    # ==================== MiniMax H3 Reference-to-Video (WaveSpeed) ====================
    # API: minimax/h3/reference-to-video
    # Docs: https://wavespeed.ai/models/minimax/h3/reference-to-video
    # Resolution 768p|2k; duration 4–15s; ≥1 image or video;
    # reference_audios 2–15s each, cannot be alone. Aspect default 16:9 if omitted.

    @staticmethod
    def normalize_h3_resolution(resolution: Optional[str]) -> str:
        raw = (resolution or "").strip().lower()
        if raw in {"2k", "1080p", "1440p", "2160p", "4k"}:
            return "2k"
        return "768p"

    async def create_minimax_h3_r2v_task(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "768p",
        aspect_ratio: Optional[str] = None,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
    ) -> str:
        """Create a MiniMax H3 reference-to-video task."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(4, min(15, int(duration)))
        resolution = self.normalize_h3_resolution(resolution)
        images = [u for u in (reference_images or []) if isinstance(u, str) and u.strip()]
        videos = [u for u in (reference_videos or []) if isinstance(u, str) and u.strip()]
        audios = [u for u in (reference_audios or []) if isinstance(u, str) and u.strip()]
        if not images and not videos:
            raise ValueError(
                "MiniMax H3 reference-to-video requires at least one reference image or video"
            )
        if len(images) > 9:
            images = images[:9]
        if len(videos) > 3:
            videos = videos[:3]
        if len(audios) > 3:
            audios = audios[:3]
        url = f"{self.base_url}/minimax/h3/reference-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if images:
            payload["reference_images"] = images
        if videos:
            payload["reference_videos"] = videos
        if audios:
            payload["reference_audios"] = audios
        logger.info(
            "🎬 MiniMax H3 R2V 创建任务: %s..., duration=%ss, res=%s, images=%s videos=%s audios=%s",
            prompt[:50], duration, resolution, len(images), len(videos), len(audios),
        )
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") is not None and result.get("code") != 200:
                        raise Exception(result.get("message", "Unknown error"))
                    request_id = self._parse_wavespeed_submit_task_id(result)
                    logger.info(f"🎬 MiniMax H3 R2V 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                logger.error(f"🎬 MiniMax H3 R2V 任务创建失败: {response.status}, {error_text}")
                raise Exception(f"MiniMax H3 R2V 任务创建失败: {response.status}, {error_text}")

    async def generate_minimax_h3_r2v(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "768p",
        aspect_ratio: Optional[str] = None,
        reference_images: Optional[List[str]] = None,
        reference_videos: Optional[List[str]] = None,
        reference_audios: Optional[List[str]] = None,
        seed: int = 0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        strip_audio: bool = False,
    ) -> VideoGenerationResult:
        """MiniMax H3 R2V: create + poll (reuses WaveSpeed predictions polling)."""
        request_id = None
        try:
            request_id = await self.create_minimax_h3_r2v_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                reference_audios=reference_audios,
            )
            return await self.poll_seedance_video_task_until_complete(
                request_id, "", prompt, duration, self.normalize_h3_resolution(resolution),
                seed, end_image=None,
                target_width=target_width, target_height=target_height,
                strip_audio=strip_audio,
            )
        except RetryError:
            logger.error(
                "🎬 MiniMax H3 R2V 仍在 processing，本地轮询超时 remote_task_id=%s",
                request_id,
            )
            return VideoGenerationResult.error_result(
                error_message=(
                    "provider_pending_timeout: MiniMax H3 R2V still processing "
                    f"after poll limit; remote_task_id={request_id}; retryable=true"
                ),
                provider=VideoProvider.WAVESPEED,
            )
        except Exception as e:
            logger.error(f"🎬 MiniMax H3 R2V 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"MiniMax H3 R2V 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED,
            )

    # ==================== Kling v3.0 Std Image-to-Video (WaveSpeed) ====================
    # API: kwaivgi/kling-v3.0-std/image-to-video; Cost: $0.90/5s, sound 1.5x

    async def generate_kling_v3_video(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        cfg_scale: float = 0.5,
        negative_prompt: Optional[str] = None,
        end_image: Optional[str] = None,
        sound: bool = False,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Kling v3.0 Std image-to-video: create task + poll until completion. duration 3-15s, cost $0.90/5s, sound 1.5x."""
        try:
            request_id = await self.create_kling_v3_video_task(
                image=image,
                prompt=prompt,
                duration=duration,
                cfg_scale=cfg_scale,
                negative_prompt=negative_prompt,
                end_image=end_image,
                sound=sound,
            )
            return await self.poll_kling_v3_video_task_until_complete(
                request_id=request_id,
                original_prompt=prompt,
                duration=duration,
                sound=sound,
                target_width=target_width,
                target_height=target_height,
            )
        except Exception as e:
            logger.error(f"🎬 Kling v3 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Kling v3 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_kling_v3_video_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        cfg_scale: float = 0.5,
        negative_prompt: Optional[str] = None,
        end_image: Optional[str] = None,
        sound: bool = False,
    ) -> str:
        """Create a Kling v3.0 Std image-to-video task. duration 3-15, image needs 300px+, aspect ratio 1:2.5~2.5:1."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(3, min(15, duration))
        url = f"{self.base_url}/kwaivgi/kling-v3.0-std/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "image": image,
            "duration": duration,
            "cfg_scale": cfg_scale,
            "sound": sound,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if end_image:
            payload["end_image"] = end_image
        logger.info(f"🎬 创建 Kling v3 视频任务: {prompt[:50]}..., duration={duration}s, sound={sound}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise Exception(f"Kling v3 任务创建失败: {error_msg}")
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 Kling v3 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"Kling v3 任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(600),  # Kling v3.0 std needs ~10 minutes, poll up to 10 minutes
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_kling_v3_video_task_until_complete(
        self,
        request_id: str,
        original_prompt: str,
        duration: int,
        sound: bool = False,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll the Kling v3 video task until completion; on success download and upload to S3, returning VideoGenerationResult fields consistent with Seedance (for persistence/regenerate)."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        raise WaveSpeedFinalException(f"Request failed with status {e.status}")
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")
                    data = result.get("data", {})
                    status = data.get("status", "unknown")
                    logger.info(f"🎬 Kling v3 任务状态: {status} (request_id={request_id})")
                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if not outputs:
                            raise WaveSpeedFinalException("任务完成但无输出结果")
                        video_url = outputs[0]
                        logger.info(f"🎬 Kling v3 视频生成成功: {request_id}")
                        from ..utils.s3_utils import s3_utils
                        import uuid
                        generation_id = f"kling_v3_{request_id}_{uuid.uuid4().hex[:8]}"
                        local_video_url = await s3_utils.ensure_video_on_our_s3(
                            video_url,
                            generation_id=generation_id,
                            target_width=target_width,
                            target_height=target_height,
                        )
                        logger.info(f"✅ Kling v3 视频已上传到 S3: {local_video_url}")
                        return VideoGenerationResult.success_result(
                            video_url=local_video_url,
                            generated_prompt=original_prompt,
                            provider=VideoProvider.WAVESPEED,
                            duration=float(duration),
                            resolution=None,
                            aspect_ratio=None,
                            model="kling-v3.0-std",
                            seed=None,
                            message="✅ WaveSpeed Kling v3 视频生成成功"
                        )
                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        raise WaveSpeedFinalException(f"Kling v3 视频生成任务失败: {error_msg}")
                    elif status in ("pending", "processing", "running"):
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")
                    else:
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")
        except WaveSpeedRetryException:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎬 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎬 JSON 解析错误: {e}")
            raise WaveSpeedServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎬 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    # ==================== Alibaba HappyHorse 1.0 Image-to-Video ====================

    async def generate_happyhorse_1_0_i2v(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: Optional[int] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Alibaba HappyHorse 1.0 image-to-video (720p/1080p, 3-15s)."""
        try:
            request_id = await self.create_happyhorse_1_0_i2v_task(
                image, prompt, duration, resolution, seed
            )
            return await self.poll_happyhorse_1_0_i2v_task_until_complete(
                request_id, prompt, duration,
                target_width=target_width, target_height=target_height,
            )
        except Exception as e:
            logger.error(f"🎬 HappyHorse 1.0 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"HappyHorse 1.0 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_happyhorse_1_0_i2v_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: Optional[int] = None,
    ) -> str:
        """Create a HappyHorse 1.0 image-to-video task. duration 3-15, image needs 300px+, aspect ratio 1:2.5~2.5:1."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(3, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ HappyHorse 1.0 分辨率不支持，默认使用 720p")
        url = f"{self.base_url}/alibaba/happyhorse-1.0/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "image": image,
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
        }
        if seed is not None:
            payload["seed"] = seed
        logger.info(f"🎬 创建 HappyHorse 1.0 视频任务: {prompt[:50]}..., duration={duration}s, resolution={resolution}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise Exception(f"HappyHorse 1.0 任务创建失败: {error_msg}")
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 HappyHorse 1.0 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"HappyHorse 1.0 任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(900),
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_happyhorse_1_0_i2v_task_until_complete(
        self,
        request_id: str,
        original_prompt: str,
        duration: int,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll the HappyHorse 1.0 video task until completion; on success download and upload to S3."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        raise WaveSpeedFinalException(f"Request failed with status {e.status}")
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")
                    data = result.get("data", {})
                    status = data.get("status", "unknown")
                    logger.info(f"🎬 HappyHorse 1.0 任务状态: {status} (request_id={request_id})")
                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if not outputs:
                            raise WaveSpeedFinalException("任务完成但无输出结果")
                        video_url = outputs[0]
                        logger.info(f"🎬 HappyHorse 1.0 视频生成成功: {request_id}")
                        from ..utils.s3_utils import s3_utils
                        import uuid
                        generation_id = f"happyhorse_1_0_{request_id}_{uuid.uuid4().hex[:8]}"
                        local_video_url = await s3_utils.ensure_video_on_our_s3(
                            video_url,
                            generation_id=generation_id,
                            target_width=target_width,
                            target_height=target_height,
                        )
                        logger.info(f"✅ HappyHorse 1.0 视频已上传到 S3: {local_video_url}")
                        return VideoGenerationResult.success_result(
                            video_url=local_video_url,
                            generated_prompt=original_prompt,
                            provider=VideoProvider.WAVESPEED,
                            duration=float(duration),
                            resolution=None,
                            aspect_ratio=None,
                            model="happyhorse-1.0-i2v",
                            seed=None,
                            message="✅ WaveSpeed HappyHorse 1.0 视频生成成功"
                        )
                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        raise WaveSpeedFinalException(f"HappyHorse 1.0 视频生成任务失败: {error_msg}")
                    elif status in ("pending", "processing", "running"):
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")
                    else:
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")
        except WaveSpeedRetryException:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎬 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎬 JSON 解析错误: {e}")
            raise WaveSpeedFinalException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎬 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    # ==================== Alibaba HappyHorse 1.1 Image-to-Video ====================

    async def generate_happyhorse_1_1_i2v(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: Optional[int] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Alibaba HappyHorse 1.1 image-to-video (720p/1080p, 3-15s)."""
        try:
            request_id = await self.create_happyhorse_1_1_i2v_task(
                image, prompt, duration, resolution, seed
            )
            return await self.poll_happyhorse_1_1_i2v_task_until_complete(
                request_id, prompt, duration,
                target_width=target_width, target_height=target_height,
            )
        except Exception as e:
            logger.error(f"🎬 HappyHorse 1.1 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"HappyHorse 1.1 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_happyhorse_1_1_i2v_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: Optional[int] = None,
    ) -> str:
        """Create a HappyHorse 1.1 image-to-video task. duration 3-15, image needs 300px+, aspect ratio 1:2.5~2.5:1."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        duration = max(3, min(15, duration))
        if resolution not in ("720p", "1080p"):
            resolution = "720p"
            logger.info("⚠️ HappyHorse 1.1 分辨率不支持，默认使用 720p")
        url = f"{self.base_url}/alibaba/happyhorse-1.1/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "image": image,
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
        }
        if seed is not None:
            payload["seed"] = seed
        logger.info(f"🎬 创建 HappyHorse 1.1 视频任务: {prompt[:50]}..., duration={duration}s, resolution={resolution}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise Exception(f"HappyHorse 1.1 任务创建失败: {error_msg}")
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 HappyHorse 1.1 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"HappyHorse 1.1 任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(900),  # 15s 1080p measured can exceed 10min
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_happyhorse_1_1_i2v_task_until_complete(
        self,
        request_id: str,
        original_prompt: str,
        duration: int,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll the HappyHorse 1.1 video task until completion; on success download and upload to S3."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        raise WaveSpeedFinalException(f"Request failed with status {e.status}")
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise WaveSpeedFinalException(f"API error: {error_msg}")
                    data = result.get("data", {})
                    status = data.get("status", "unknown")
                    logger.info(f"🎬 HappyHorse 1.1 任务状态: {status} (request_id={request_id})")
                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if not outputs:
                            raise WaveSpeedFinalException("任务完成但无输出结果")
                        video_url = outputs[0]
                        logger.info(f"🎬 HappyHorse 1.1 视频生成成功: {request_id}")
                        from ..utils.s3_utils import s3_utils
                        import uuid
                        generation_id = f"happyhorse_1_1_{request_id}_{uuid.uuid4().hex[:8]}"
                        local_video_url = await s3_utils.ensure_video_on_our_s3(
                            video_url,
                            generation_id=generation_id,
                            target_width=target_width,
                            target_height=target_height,
                        )
                        logger.info(f"✅ HappyHorse 1.1 视频已上传到 S3: {local_video_url}")
                        return VideoGenerationResult.success_result(
                            video_url=local_video_url,
                            generated_prompt=original_prompt,
                            provider=VideoProvider.WAVESPEED,
                            duration=float(duration),
                            resolution=None,
                            aspect_ratio=None,
                            model="happyhorse-1.1-i2v",
                            seed=None,
                            message="✅ WaveSpeed HappyHorse 1.1 视频生成成功"
                        )
                    elif status == "failed":
                        error_msg = data.get("error", "未知错误")
                        raise WaveSpeedFinalException(f"HappyHorse 1.1 视频生成任务失败: {error_msg}")
                    elif status in ("pending", "processing", "running"):
                        raise WaveSpeedTaskNotReadyException(f"Task is {status}")
                    else:
                        raise WaveSpeedTaskNotReadyException(f"Unknown status: {status}")
        except WaveSpeedRetryException:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎬 网络请求错误: {e}")
            raise WaveSpeedServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎬 JSON 解析错误: {e}")
            raise WaveSpeedServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎬 未预期的错误: {e}")
            raise WaveSpeedFinalException(f"Unexpected error: {e}")

    # ==================== Alibaba Wan 2.5 Image-to-Video (optional audio, no end image) ====================

    async def generate_wan25_video(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1,
        enable_prompt_expansion: bool = False,
        audio_url: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Alibaba Wan 2.5 image-to-video (supports optional audio, no end frame)."""
        try:
            request_id = await self.create_wan25_video_task(
                image, prompt, duration, resolution, seed, enable_prompt_expansion, audio_url
            )
            return await self.poll_wan25_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed,
                target_width=target_width, target_height=target_height,
                lipsync_preview=bool(audio_url),
            )
        except Exception as e:
            logger.error(f"🎬 Wan 2.5 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Wan 2.5 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_wan25_video_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1,
        enable_prompt_expansion: bool = False,
        audio_url: Optional[str] = None
    ) -> str:
        """Create a Wan 2.5 image-to-video task (alibaba/wan-2.5/image-to-video)."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        if resolution not in ["480p", "720p", "1080p"]:
            resolution = "720p"
            logger.info("⚠️ Wan 2.5 分辨率不支持，默认使用 720p")
        url = f"{self.base_url}/alibaba/wan-2.5/image-to-video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
            "duration": duration,
            "enable_prompt_expansion": enable_prompt_expansion,
            "seed": seed,
        }
        if audio_url:
            payload["audio"] = audio_url
        logger.info(f"🎬 创建 Wan 2.5 视频任务: {prompt[:50]}..., resolution={resolution}, duration={duration}s")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise Exception(f"Wan 2.5 任务创建失败: {error_msg}")
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 Wan 2.5 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"Wan 2.5 任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(600),  # wan2.5 is slow, give 2x the time (300s -> 600s)
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_wan25_video_task_until_complete(
        self,
        request_id: str,
        original_image: str,
        original_prompt: str,
        duration: int,
        resolution: str,
        seed: int,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        lipsync_preview: bool = False,
    ) -> VideoGenerationResult:
        """Poll the Wan 2.5 video task until completion."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        raise WaveSpeedFinalException(f"Request failed with status {e.status}")
                    result = await response.json()
                    if result.get("code") != 200:
                        raise WaveSpeedFinalException(result.get("message", "API error"))
                    data = result.get("data", {})
                    status = data.get("status", "unknown")
                    logger.info(f"🎬 Wan 2.5 任务状态: {status} (request_id={request_id})")
                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if not outputs:
                            raise WaveSpeedFinalException("任务完成但无输出结果")
                        video_url = outputs[0]
                        import uuid
                        from ..utils.video_utils import finalize_pipeline_video_upload

                        generation_id = f"wan25_{request_id}_{uuid.uuid4().hex[:8]}"
                        local_video_url, preview_url = await finalize_pipeline_video_upload(
                            video_url,
                            generation_id=generation_id,
                            target_width=target_width,
                            target_height=target_height,
                            lipsync_preview=lipsync_preview,
                        )
                        if preview_url:
                            logger.info(
                                "✅ Wan 2.5 lipsync 已上传: preview=%s... muted=%s...",
                                preview_url[:60],
                                local_video_url[:60],
                            )
                        else:
                            logger.info(f"✅ Wan 2.5 视频已上传到 S3: {local_video_url}")
                        result_kw: Dict[str, Any] = {}
                        if preview_url:
                            result_kw["preview_video_url"] = preview_url
                        return VideoGenerationResult.success_result(
                            video_url=local_video_url,
                            generated_prompt=original_prompt,
                            provider=VideoProvider.WAVESPEED,
                            duration=float(duration),
                            resolution=resolution,
                            seed=seed,
                            message="✅ WaveSpeed Wan 2.5 视频生成成功",
                        ).model_copy(update=result_kw)
                    elif status == "failed":
                        raise WaveSpeedFinalException(data.get("error", "任务失败"))
                    raise WaveSpeedTaskNotReadyException(f"Task is {status}")
        except WaveSpeedRetryException:
            raise
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            logger.error(f"🎬 Wan 2.5 轮询错误: {e}")
            raise WaveSpeedServerErrorException(str(e))
        except Exception as e:
            logger.error(f"🎬 Wan 2.5 未预期错误: {e}")
            raise WaveSpeedFinalException(str(e))

    # ==================== Alibaba Wan 2.6 Image-to-Video-Flash (720p/1080p, 3-15s, enable_audio) ====================

    async def generate_wan26_video(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1,
        shot_type: str = "single",
        enable_prompt_expansion: bool = False,
        enable_audio: bool = True,
        audio_url: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Alibaba Wan 2.6 image-to-video Flash (720p/1080p, 3-15s, enable_audio controls whether audio is included)."""
        try:
            request_id = await self.create_wan26_video_task(
                image, prompt, duration, resolution, seed, shot_type, enable_prompt_expansion, enable_audio, audio_url
            )
            return await self.poll_wan26_video_task_until_complete(
                request_id, image, prompt, duration, resolution, seed,
                target_width=target_width, target_height=target_height,
                lipsync_preview=bool(audio_url),
            )
        except Exception as e:
            logger.error(f"🎬 Wan 2.6 视频生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"Wan 2.6 视频生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED
            )

    async def create_wan26_video_task(
        self,
        image: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        seed: int = -1,
        shot_type: str = "single",
        enable_prompt_expansion: bool = False,
        enable_audio: bool = True,
        audio_url: Optional[str] = None
    ) -> str:
        """Create a Wan 2.6 image-to-video task (alibaba/wan-2.6/image-to-video-flash)."""
        if not self.api_key:
            raise Exception("WaveSpeed API key 未配置")
        if resolution not in ["720p", "1080p"]:
            resolution = "720p"
            logger.info("⚠️ Wan 2.6 仅支持 720p/1080p，默认 720p")
        duration = max(3, min(15, duration))
        url = f"{self.base_url}/alibaba/wan-2.6/image-to-video-flash"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "image": image,
            "prompt": prompt,
            "resolution": resolution,
            "duration": duration,
            "shot_type": shot_type,
            "enable_prompt_expansion": enable_prompt_expansion,
            "enable_audio": enable_audio,
            "seed": seed,
        }
        if audio_url:
            payload["audio"] = audio_url
        logger.info(f"🎬 创建 Wan 2.6 视频任务: {prompt[:50]}..., resolution={resolution}, duration={duration}s, enable_audio={enable_audio}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") != 200:
                        error_msg = result.get("message", "Unknown error")
                        raise Exception(f"Wan 2.6 任务创建失败: {error_msg}")
                    request_id = result["data"]["id"]
                    logger.info(f"🎬 Wan 2.6 任务创建成功: {request_id}")
                    return request_id
                error_text = await response.text()
                raise Exception(f"Wan 2.6 任务创建失败: {response.status}, {error_text}")

    @retry(
        retry=retry_if_exception_type(WaveSpeedRetryException),
        stop=stop_after_delay(400),
        wait=_wavespeed_wait,
        sleep=asyncio.sleep,
    )
    async def poll_wan26_video_task_until_complete(
        self,
        request_id: str,
        original_image: str,
        original_prompt: str,
        duration: int,
        resolution: str,
        seed: int,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        lipsync_preview: bool = False,
    ) -> VideoGenerationResult:
        """Poll the Wan 2.6 video task until completion."""
        try:
            url = f"{self.base_url}/predictions/{request_id}/result"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        raise WaveSpeedRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            raise WaveSpeedServerErrorException(f"Server error: {e.status}")
                        raise WaveSpeedFinalException(f"Request failed with status {e.status}")
                    result = await response.json()
                    if result.get("code") != 200:
                        raise WaveSpeedFinalException(result.get("message", "API error"))
                    data = result.get("data", {})
                    status = data.get("status", "unknown")
                    logger.info(f"🎬 Wan 2.6 任务状态: {status} (request_id={request_id})")
                    if status == "completed":
                        outputs = data.get("outputs", [])
                        if not outputs:
                            raise WaveSpeedFinalException("任务完成但无输出结果")
                        video_url = outputs[0]
                        import uuid
                        from ..utils.video_utils import finalize_pipeline_video_upload

                        generation_id = f"wan26_{request_id}_{uuid.uuid4().hex[:8]}"
                        local_video_url, preview_url = await finalize_pipeline_video_upload(
                            video_url,
                            generation_id=generation_id,
                            target_width=target_width,
                            target_height=target_height,
                            lipsync_preview=lipsync_preview,
                        )
                        if preview_url:
                            logger.info(
                                "✅ Wan 2.6 lipsync 已上传: preview=%s... muted=%s...",
                                preview_url[:60],
                                local_video_url[:60],
                            )
                        else:
                            logger.info(f"✅ Wan 2.6 视频已上传到 S3: {local_video_url}")
                        result_kw: Dict[str, Any] = {}
                        if preview_url:
                            result_kw["preview_video_url"] = preview_url
                        return VideoGenerationResult.success_result(
                            video_url=local_video_url,
                            generated_prompt=original_prompt,
                            provider=VideoProvider.WAVESPEED,
                            duration=float(duration),
                            resolution=resolution,
                            seed=seed,
                            message="✅ WaveSpeed Wan 2.6 视频生成成功",
                        ).model_copy(update=result_kw)
                    elif status == "failed":
                        raise WaveSpeedFinalException(data.get("error", "任务失败"))
                    raise WaveSpeedTaskNotReadyException(f"Task is {status}")
        except WaveSpeedRetryException:
            raise
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            logger.error(f"🎬 Wan 2.6 轮询错误: {e}")
            raise WaveSpeedServerErrorException(str(e))
        except Exception as e:
            logger.error(f"🎬 Wan 2.6 未预期错误: {e}")
            raise WaveSpeedFinalException(str(e))

    async def generate_lipsync(
        self,
        audio_url: str,
        video_url: str,
        model: str = "sync/lipsync-2-pro"
    ) -> VideoGenerationResult:
        """
        Generate a lip-sync video.

        Args:
            audio_url: audio file URL
            video_url: video file URL
            model: model to use, default sync/lipsync-2-pro

        Returns:
            a VideoGenerationResult object
        """
        if not self.api_key:
            return VideoGenerationResult.error_result(
                error_message="WaveSpeed API key 未配置",
                provider=VideoProvider.WAVESPEED.value
            )

        logger.info(f"🎭 WaveSpeed Lipsync 开始生成: audio={audio_url[:50]}..., video={video_url[:50]}...")

        try:
            # submit the lip-sync task
            request_id = await self.create_lipsync_task(audio_url, video_url, model)

            # poll for the result
            return await self.poll_lipsync_task_until_complete(request_id, audio_url, video_url, model)

        except Exception as e:
            logger.error(f"🎭 唇形同步生成失败: {e}")
            return VideoGenerationResult.error_result(
                error_message=f"唇形同步生成失败: {str(e)}",
                provider=VideoProvider.WAVESPEED.value
            )

    async def create_lipsync_task(
        self,
        audio_url: str,
        video_url: str,
        model: str = "sync/lipsync-2-pro"
    ) -> str:
        """Create a lip-sync task (WaveSpeed sync/lipsync-2-pro)."""
        url = f"{self.base_url}/{model}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "audio": audio_url,
            "video": video_url,
            "sync_mode": "cut_off",
        }
        logger.info(f"🎭 提交唇形同步任务: {model}")
        logger.debug(f"📝 请求参数: {json.dumps(payload, indent=2)}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"📥 API响应状态: {response.status}")
                logger.debug(f"📥 API响应内容: {response_text}")

                if response.status == 200:
                    result = json.loads(response_text)
                    request_id = result["data"]["id"]
                    logger.info(f"✅ 唇形同步任务提交成功，Request ID: {request_id}")
                    return request_id
                else:
                    error_msg = f"API请求失败: {response.status}, {response_text}"
                    logger.error(f"❌ {error_msg}")
                    raise WaveSpeedFinalException(error_msg)

    @retry(
        stop=stop_after_delay(300),  # wait up to 5 minutes
        wait=wait_fixed(2),  # check every 2 seconds
        retry=retry_if_exception_type(WaveSpeedTaskNotReadyException),
        sleep=asyncio.sleep,
    )
    async def poll_lipsync_task_until_complete(
        self,
        request_id: str,
        audio_url: str,
        video_url: str,
        model: str
    ) -> VideoGenerationResult:
        """Poll the lip-sync task until completion."""
        url = f"{self.base_url}/predictions/{request_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response_text = await response.text()

                if response.status != 200:
                    error_msg = f"查询任务状态失败: {response.status}, {response_text}"
                    logger.error(f"❌ {error_msg}")
                    raise WaveSpeedFinalException(error_msg)

                result = json.loads(response_text)
                data = result["data"]
                status = data["status"]

                logger.info(f"🔄 唇形同步任务状态: {status}")

                if status == "completed":
                    output_url = data["outputs"][0]
                    logger.info(f"✅ 唇形同步生成完成: {output_url}")
                    from ..utils.video_utils import finalize_pipeline_video_upload
                    local_video_url, preview_url = await finalize_pipeline_video_upload(
                        output_url,
                        generation_id=f"lipsync_{request_id}",
                        lipsync_preview=True,
                    )
                    logger.info(
                        f"✅ 唇形同步视频已上传: preview={preview_url[:60] if preview_url else 'n/a'}... "
                        f"muted={local_video_url[:60]}..."
                    )
                    return VideoGenerationResult.success_result(
                        video_url=local_video_url,
                        generated_prompt=f"Lipsync: {audio_url} + {video_url}",
                        provider=VideoProvider.WAVESPEED.value,
                        duration=None,
                    ).model_copy(update={"preview_video_url": preview_url} if preview_url else {})

                elif status == "failed":
                    error_msg = f"唇形同步任务失败: {data.get('error', 'Unknown error')}"
                    logger.error(f"❌ {error_msg}")
                    raise WaveSpeedFinalException(error_msg)

                else:
                    # the task is still processing
                    logger.info(f"⏳ 唇形同步任务处理中，状态: {status}")
                    raise WaveSpeedTaskNotReadyException(f"Task still processing: {status}")

    # ==================== LTX 2.3 Lipsync (audio+image→video) ====================

    LTX23_LIPSYNC_PATH = "wavespeed-ai/ltx-2.3/lipsync"

    async def create_ltx23_lipsync_task(
        self,
        audio_url: str,
        image_url: Optional[str] = None,
        resolution: str = "720p",
        seed: int = -1,
        prompt: Optional[str] = None,
    ) -> str:
        """Submit an LTX 2.3 lipsync task (audio + optional image + optional prompt -> video), returns request_id."""
        url = f"{self.base_url}/{self.LTX23_LIPSYNC_PATH}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "audio": audio_url,
            "resolution": resolution,
            "seed": seed,
        }
        if image_url:
            payload["image"] = image_url
        if prompt:
            payload["prompt"] = prompt
        logger.info(f"🎭 提交 LTX 2.3 Lipsync 任务: resolution={resolution}, prompt={bool(prompt)}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"LTX 2.3 Lipsync 提交失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                request_id = result["data"]["id"]
                logger.info(f"✅ LTX 2.3 Lipsync 任务已提交: {request_id}")
                return request_id

    @retry(
        stop=stop_after_delay(300),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(WaveSpeedTaskNotReadyException),
        sleep=asyncio.sleep,
    )
    async def poll_ltx23_lipsync_until_complete(
        self,
        request_id: str,
        audio_url: str,
        *,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll the LTX 2.3 Lipsync task until completion, returns a VideoGenerationResult."""
        url = f"{self.base_url}/predictions/{request_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"查询 LTX 2.3 任务状态失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                data = result.get("data", {})
                status = data.get("status", "")
                if status == "completed":
                    outputs = data.get("outputs") or []
                    if not outputs:
                        raise WaveSpeedFinalException("LTX 2.3 Lipsync 完成但无输出")
                    output_url = outputs[0]
                    logger.info(f"✅ LTX 2.3 Lipsync 生成完成: {output_url}")
                    from ..utils.video_utils import finalize_pipeline_video_upload
                    local_video_url, preview_url = await finalize_pipeline_video_upload(
                        output_url,
                        generation_id=f"ltx23_{request_id}",
                        target_width=target_width,
                        target_height=target_height,
                        lipsync_preview=True,
                    )
                    logger.info(f"✅ LTX 2.3 视频已上传: preview={preview_url[:60]}... muted={local_video_url[:60]}...")
                    return VideoGenerationResult.success_result(
                        video_url=local_video_url,
                        generated_prompt=f"LTX 2.3 Lipsync: {audio_url[:50]}...",
                        provider=VideoProvider.WAVESPEED.value,
                        duration=None,
                        message="✅ LTX 2.3 Lipsync success",
                    ).model_copy(update={"preview_video_url": preview_url})
                if status == "failed":
                    raise WaveSpeedFinalException(f"LTX 2.3 Lipsync 任务失败: {data.get('error', 'Unknown error')}")
                raise WaveSpeedTaskNotReadyException(f"Task still processing: {status}")

    # ==================== Kling V2 AI Avatar Pro (image+audio→video, WaveSpeed) ====================

    KLING_V2_AI_AVATAR_PRO_PATH = "kwaivgi/kling-v2-ai-avatar-pro"

    async def create_kling_v2_ai_avatar_pro_task(
        self,
        audio_url: str,
        image_url: str,
        prompt: Optional[str] = None,
    ) -> str:
        """Submit Kling V2 AI Avatar Pro (image + audio + optional prompt), returns request_id."""
        url = f"{self.base_url}/{self.KLING_V2_AI_AVATAR_PRO_PATH}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict = {"audio": audio_url, "image": image_url}
        if prompt:
            payload["prompt"] = prompt
        logger.info(f"🎭 提交 Kling V2 AI Avatar Pro 任务: prompt={bool(prompt)}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"Kling V2 AI Avatar Pro 提交失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                request_id = result["data"]["id"]
                logger.info(f"✅ Kling V2 AI Avatar Pro 任务已提交: {request_id}")
                return request_id

    @retry(
        stop=stop_after_delay(600),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(WaveSpeedTaskNotReadyException),
        sleep=asyncio.sleep,
    )
    async def poll_kling_v2_ai_avatar_pro_until_complete(
        self,
        request_id: str,
        audio_url: str,
        *,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll Kling V2 AI Avatar Pro until completion, returns a VideoGenerationResult."""
        url = f"{self.base_url}/predictions/{request_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"查询 Kling V2 AI Avatar Pro 状态失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                data = result.get("data", {})
                status = data.get("status", "")
                if status == "completed":
                    outputs = data.get("outputs") or []
                    if not outputs:
                        raise WaveSpeedFinalException("Kling V2 AI Avatar Pro 完成但无输出")
                    output_url = outputs[0]
                    logger.info(f"✅ Kling V2 AI Avatar Pro 生成完成: {output_url}")
                    from ..utils.video_utils import finalize_pipeline_video_upload
                    local_video_url, preview_url = await finalize_pipeline_video_upload(
                        output_url,
                        generation_id=f"kling_avatar_{request_id}",
                        target_width=target_width,
                        target_height=target_height,
                        lipsync_preview=True,
                    )
                    logger.info(f"✅ Kling Avatar 已上传: preview={preview_url[:60]}... muted={local_video_url[:60]}...")
                    return VideoGenerationResult.success_result(
                        video_url=local_video_url,
                        generated_prompt=f"Kling V2 AI Avatar Pro: {audio_url[:50]}...",
                        provider=VideoProvider.WAVESPEED.value,
                        duration=None,
                    ).model_copy(update={"preview_video_url": preview_url})
                if status == "failed":
                    raise WaveSpeedFinalException(f"Kling V2 AI Avatar Pro 任务失败: {data.get('error', 'Unknown error')}")
                raise WaveSpeedTaskNotReadyException(f"Task still processing: {status}")

    # ==================== WAN 2.2 Speech-to-Video (image+audio, WaveSpeed) ====================

    WAN_22_SPEECH_TO_VIDEO_PATH = "wavespeed-ai/wan-2.2/speech-to-video"

    async def create_wan22_speech_to_video_task(
        self,
        audio_url: str,
        image_url: str,
        resolution: str = "720p",
        prompt: Optional[str] = None,
        seed: int = -1,
    ) -> str:
        """Submit WAN 2.2 Speech-to-Video (image + audio + resolution 480p|720p), returns request_id."""
        url = f"{self.base_url}/{self.WAN_22_SPEECH_TO_VIDEO_PATH}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        res = resolution if resolution in ("480p", "720p") else "720p"
        payload: dict = {"audio": audio_url, "image": image_url, "resolution": res, "seed": seed}
        if prompt:
            payload["prompt"] = prompt
        logger.info(f"🎭 提交 WAN 2.2 Speech-to-Video: resolution={res}, prompt={bool(prompt)}")
        payload = await self._resolve_payload_media(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"WAN 2.2 Speech-to-Video 提交失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                request_id = result["data"]["id"]
                logger.info(f"✅ WAN 2.2 Speech-to-Video 任务已提交: {request_id}")
                return request_id

    @retry(
        stop=stop_after_delay(600),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(WaveSpeedTaskNotReadyException),
        sleep=asyncio.sleep,
    )
    async def poll_wan22_speech_to_video_until_complete(
        self,
        request_id: str,
        audio_url: str,
        *,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> VideoGenerationResult:
        """Poll WAN 2.2 Speech-to-Video until completion."""
        url = f"{self.base_url}/predictions/{request_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise WaveSpeedFinalException(f"查询 WAN 2.2 Speech-to-Video 状态失败: {response.status}, {response_text}")
                result = json.loads(response_text)
                data = result.get("data", {})
                status = data.get("status", "")
                if status == "completed":
                    outputs = data.get("outputs") or []
                    if not outputs:
                        raise WaveSpeedFinalException("WAN 2.2 Speech-to-Video 完成但无输出")
                    output_url = outputs[0]
                    logger.info(f"✅ WAN 2.2 Speech-to-Video 生成完成: {output_url}")
                    from ..utils.video_utils import finalize_pipeline_video_upload
                    local_video_url, preview_url = await finalize_pipeline_video_upload(
                        output_url,
                        generation_id=f"wan22_s2v_{request_id}",
                        target_width=target_width,
                        target_height=target_height,
                        lipsync_preview=True,
                    )
                    logger.info(f"✅ WAN 2.2 S2V 已上传: preview={preview_url[:60]}... muted={local_video_url[:60]}...")
                    return VideoGenerationResult.success_result(
                        video_url=local_video_url,
                        generated_prompt=f"WAN 2.2 S2V: {audio_url[:50]}...",
                        provider=VideoProvider.WAVESPEED.value,
                        duration=None,
                    ).model_copy(update={"preview_video_url": preview_url})
                if status == "failed":
                    raise WaveSpeedFinalException(f"WAN 2.2 Speech-to-Video 任务失败: {data.get('error', 'Unknown error')}")
                raise WaveSpeedTaskNotReadyException(f"Task still processing: {status}")


_wavespeed_service = None

def get_wavespeed_service() -> WaveSpeedService:
    global _wavespeed_service
    if _wavespeed_service is None:
        _wavespeed_service = WaveSpeedService()
    return _wavespeed_service
