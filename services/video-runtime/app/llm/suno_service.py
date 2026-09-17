"""
SunoAPI music-generation service
"""
import asyncio
import json
import aiohttp
import logging
from typing import Any, Dict, Optional
from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type, retry_if_result
from app.models.image_result import MusicGenerationResult, MusicProvider
from app.utils.s3_utils import s3_utils
from app.services.agent.utils.cancellation import raise_if_cancelled
import os

logger = logging.getLogger(__name__)


class SunoRetryException(Exception):
    """Base exception class for Suno API errors that should be retried."""

    def __init__(self, message: str, retry_after: int = 10, max_retries: int = 30):
        super().__init__(message)
        self.retry_after = retry_after
        self.max_retries = max_retries


class SunoTaskNotReadyException(SunoRetryException):
    """Task-not-ready exception - should be retried."""

    def __init__(self, message: str = "Task not ready, please wait"):
        super().__init__(message, retry_after=10, max_retries=30)


class SunoTaskPendingException(SunoRetryException):
    """Task-pending exception - should be retried."""

    def __init__(self, message: str = "Task is pending"):
        super().__init__(message, retry_after=10, max_retries=30)


class SunoTaskRunningException(SunoRetryException):
    """Task-running exception - should be retried."""

    def __init__(self, message: str = "Task is running"):
        super().__init__(message, retry_after=10, max_retries=30)


class SunoRateLimitException(SunoRetryException):
    """API rate-limit exception - should be retried."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, retry_after=retry_after, max_retries=10)


class SunoServerErrorException(SunoRetryException):
    """Server-error exception - should be retried."""

    def __init__(self, message: str = "Server error", retry_after: int = 30):
        super().__init__(message, retry_after=retry_after, max_retries=5)


class SunoFinalException(Exception):
    """Suno API final-failure exception - should not be retried."""
    pass


def _clip_duration_seconds(raw: Any) -> int:
    """Suno often sends duration:null while audio_url is already ready."""
    if raw is None or raw == "":
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        logger.warning("🎵 无法解析 duration: %s，使用默认值 0", raw)
        return 0


def _suno_wait(retry_state) -> float:
    """Get the wait time from the exception's retry_after field, default 10 seconds."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, SunoRetryException):
        return float(exc.retry_after)
    return 10.0


class SunoService:
    """SunoAPI music-generation service - concise version."""

    def __init__(self, api_key: str = None, base_url: str = "https://api.sunoapi.com"):
        self.api_key = api_key or os.getenv("SUNO_API_KEY")
        self.base_url = base_url
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    async def generate_music(
        self,
        prompt: Optional[str] = None,
        custom_mode: bool = False,
        make_instrumental: bool = True,
        lyrics: Optional[str] = None,
        mv: str = "chirp-v5-5",
        tags: Optional[str] = None,
        vocal_gender: Optional[str] = None,
        title: Optional[str] = None,
        duration: Optional[int] = None,
        generation_params: Optional[dict] = None
    ) -> MusicGenerationResult:
        """Overall music-generation method - includes creation and polling.

        Args:
            prompt: GPT description prompt (used when custom_mode=False, up to 400 chars)
            custom_mode: whether to use custom mode
            make_instrumental: whether to generate pure instrumental
            lyrics: lyric content (used when custom_mode=True and make_instrumental=False, must include structure tags, up to 5000 chars)
            mv: model version, default "chirp-v5-5"
            tags: song style tags (e.g. "Fast 160BPM, Brief"), up to 200 chars for v4 and below, up to 1000 chars for v4.5 and above
            vocal_gender: vocal gender (optional, only for v4-5+): 'f' female, 'm' male
            duration: target duration in seconds (10-360). Approximate, not exact
            generation_params: generation parameters (for logging)
        """
        task_id = await self.create_music_task(
            prompt=prompt,
            custom_mode=custom_mode,
            make_instrumental=make_instrumental,
            lyrics=lyrics,
            mv=mv,
            tags=tags,
            vocal_gender=vocal_gender,
            title=title,
            duration=duration,
        )
        original_prompt = prompt or lyrics or "Custom music"
        return await self.poll_task_until_complete(
            task_id,
            original_prompt,
            generation_params=generation_params
        )

    async def create_music_task(
        self,
        prompt: Optional[str] = None,
        custom_mode: bool = False,
        make_instrumental: bool = True,
        lyrics: Optional[str] = None,
        mv: str = "chirp-v5-5",
        tags: Optional[str] = None,
        vocal_gender: Optional[str] = None,
        title: Optional[str] = None,
        duration: Optional[int] = None,
    ) -> str:
        """Create a music task.

        Args:
            prompt: GPT description prompt (used when custom_mode=False, up to 400 chars)
            custom_mode: whether to use custom mode
            make_instrumental: whether to generate pure instrumental
            lyrics: lyric content (used when custom_mode=True and make_instrumental=False, must include structure tags, up to 5000 chars)
            mv: model version, default "chirp-v5-5"
            tags: song style tags (e.g. "Fast 160BPM, Brief"), up to 200 chars for v4 and below, up to 1000 chars for v4.5 and above
            vocal_gender: vocal gender (optional, only for v4-5+): 'f' female, 'm' male
            duration: target duration in seconds (10-360). Approximate, not exact
        """
        # build the request payload (SunoAPI now requires mv in any mode; previously passing mv only in custom_mode caused GPT/auto_lyrics 400)
        payload = {
            "custom_mode": custom_mode,
            "make_instrumental": make_instrumental,
            "mv": mv,
        }
        if vocal_gender in ("f", "m"):
            payload["vocal_gender"] = vocal_gender
        if isinstance(duration, int) and 10 <= duration <= 360:
            payload["duration"] = duration

        if custom_mode:
            # custom mode: the prompt field holds lyrics or structure tags (instrumental tracks can also include [Intro]/[End])
            if lyrics:
                payload["prompt"] = lyrics
            if tags:
                payload["tags"] = tags
            if isinstance(title, str) and title.strip():
                payload["title"] = title.strip()[:80]
        else:
            # GPT description mode: use gpt_description_prompt
            if prompt:
                payload["gpt_description_prompt"] = prompt
            # tags can also be used in GPT mode
            if tags:
                payload["tags"] = tags

        logger.info(f"🎵 Suno API 请求 payload: {json.dumps(payload, ensure_ascii=False)[:2000]}")
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/api/v1/suno/create", json=payload, headers=self.headers) as response:
                text = await response.text()
                if response.status >= 400:
                    logger.error(
                        "🎵 Suno API create 失败 HTTP %s body=%s",
                        response.status,
                        text[:4000],
                    )
                response.raise_for_status()
                result = json.loads(text) if text.strip() else {}
                task_id = result.get("task_id") or result.get("id")
                if not task_id:
                    raise Exception("未获取到任务ID")

                logger.info(f"🎵 创建任务成功: {task_id}")
                return task_id

    @retry(
        retry=retry_if_exception_type(SunoRetryException),
        stop=stop_after_delay(300),
        wait=_suno_wait,
        sleep=asyncio.sleep,
    )
    async def poll_task_until_complete(
        self,
        task_id: str,
        original_prompt: str,
        generation_params: Optional[dict] = None
    ) -> MusicGenerationResult:
        """Poll a single task until completion."""
        # cooperative cancellation: check whether the user has cancelled before each poll, to promptly abandon a running music generation
        await raise_if_cancelled()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/v1/suno/task/{task_id}", headers=self.headers) as response:
                    # use raise_for_status() to handle HTTP errors, but handle special cases first
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"🎵 API 速率限制，{retry_after}秒后重试")
                        raise SunoRateLimitException(f"Rate limit exceeded, retry after {retry_after}s", retry_after)

                    # for other error status codes, let raise_for_status() handle them
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        if e.status >= 500:
                            logger.error(f"🎵 task_id={task_id} 服务器错误 {e.status}，不重试")
                            raise SunoFinalException(f"Server error: {e.status}")
                        else:
                            logger.error(f"🎵 task_id={task_id} 请求失败: {e.status}")
                            raise SunoFinalException(f"Request failed with status {e.status}")

                    result = await response.json()

                    # handle 'not_ready' type responses
                    if result.get("type") == "not_ready":
                        error_msg = result.get("error", "Task not ready")
                        logger.info(f"🎵 任务未准备好: {error_msg}")
                        raise SunoTaskNotReadyException(error_msg)

                    # handle normal task-status responses - supports multiple clips
                    clips_data = result.get("data", [])
                    if not clips_data:
                        logger.info(f"🎵 任务数据为空，等待中...")
                        raise SunoTaskNotReadyException("Task data is empty, waiting...")

                    # check the status of all clips
                    all_states = [clip.get("state", "") for clip in clips_data]
                    logger.info(f"🎵 任务状态: {all_states} (任务ID: {task_id}, {len(clips_data)} clips)")

                    # if any clip failed, the whole task fails
                    failed_clips = [clip for clip in clips_data if clip.get("state") in ["failed", "error"]]
                    if failed_clips:
                        error_msg = failed_clips[0].get('message', 'Unknown error')
                        logger.error(f"🎵 音乐生成失败: {error_msg}")
                        raise SunoFinalException(f"音乐生成失败: {error_msg}")

                    # if any clip is still processing, keep waiting
                    pending_clips = [clip for clip in clips_data if clip.get("state") in ["pending", "running", ""]]
                    if pending_clips:
                        pending_states = [clip.get("state", "unknown") for clip in pending_clips]
                        logger.info(f"🎵 还有 {len(pending_clips)} 个 clips 在处理中: {pending_states}")
                        if "running" in pending_states:
                            raise SunoTaskRunningException("Some clips are still running")
                        else:
                            raise SunoTaskPendingException("Some clips are still pending")

                    # all clips succeeded
                    succeeded_clips = [clip for clip in clips_data if clip.get("state") == "succeeded" and clip.get("audio_url")]
                    if len(succeeded_clips) == len(clips_data) and succeeded_clips:
                        logger.info(f"🎵 音乐生成成功: {len(succeeded_clips)} 个 clips 全部完成")

                        # process all clips' data and save locally
                        processed_clips = []
                        total_duration = 0
                        local_audio_urls = []

                        for i, clip in enumerate(succeeded_clips):
                            if clip.get("duration") is None:
                                logger.warning(
                                    "🎵 clip %s duration 为 null（音频已就绪），先记 0",
                                    clip.get("clip_id"),
                                )
                            duration = _clip_duration_seconds(clip.get("duration"))

                            # download and save the audio to S3 (with retry)
                            clip_id = clip.get("clip_id")
                            original_audio_url = clip["audio_url"]
                            try:
                                generation_id = f"suno_{task_id}_clip_{i}_{clip_id}"
                                local_audio_url = await s3_utils.download_and_upload_audio_to_s3(
                                    original_audio_url, generation_id=generation_id
                                )
                                local_audio_urls.append(local_audio_url)
                                logger.info(f"🎵 保存 clip {i+1} 音频到S3成功: {local_audio_url}")
                            except Exception as e:
                                logger.error(f"🎵 保存 clip {i+1} 音频到S3失败: {e}")
                                # if saving fails, use the original URL
                                local_audio_url = original_audio_url
                                local_audio_urls.append(local_audio_url)

                            processed_clips.append({
                                "clip_id": clip_id,
                                # Keep our storage URL. Internal analyze/Gemini copy
                                # from disk (local) or S3 (dest/prod). Vendor APIs
                                # go through resolve_outbound_media_url at call time.
                                "audio_url": local_audio_url,
                                "video_url": clip.get("video_url"),
                                "title": clip.get("title"),
                                "tags": clip.get("tags"),
                                "lyrics": clip.get("lyrics"),
                                "duration": duration,
                                "image_url": clip.get("image_url"),
                                "created_at": clip.get("created_at"),
                                "mv": clip.get("mv")
                            })
                            total_duration += duration

                        # when there are lyrics / auto_lyrics with target_duration: sort by |duration - target| ascending to pick the best clip,
                        # push the smallest-deviation one to [0], so the upstream generate_single_suno_music that defaults to clips[0] gets the best version.
                        # the remaining clips stay in the list (written to additional_data), so the frontend can show and switch to alternatives.
                        has_lyrics = generation_params.get("has_lyrics") if generation_params else False
                        auto_lyrics = generation_params.get("auto_lyrics") if generation_params else False
                        target_duration = generation_params.get("target_duration") if generation_params else None
                        need_duration_selection = (has_lyrics or auto_lyrics) and target_duration

                        message = None
                        if need_duration_selection and processed_clips:
                            mode_label = "有歌词" if has_lyrics else "auto_lyrics"
                            sorted_clips = sorted(
                                processed_clips,
                                key=lambda c: abs((c.get("duration") or 0) - target_duration),
                            )
                            best = sorted_clips[0]
                            best_err = abs((best.get("duration") or 0) - target_duration)
                            # push best to [0], keep the rest in their original relative order
                            processed_clips = [best] + [c for c in processed_clips if c is not best]
                            parts = []
                            for clip in processed_clips:
                                err = abs((clip.get("duration") or 0) - target_duration)
                                parts.append(f"{clip['duration']}秒(偏差{err}秒)")
                                logger.info(
                                    "🎵 Clip %s: 时长 %ss, 与目标偏差 %ss",
                                    (clip.get("clip_id") or "")[:8],
                                    clip["duration"],
                                    err,
                                )
                            message = (
                                f"✅ 音乐生成成功（目标约{target_duration}秒）。"
                                f"共{len(processed_clips)}条：{', '.join(parts)}。"
                                f"已自动选择偏差最小的版本（{best['duration']}秒，偏差{best_err}秒）作为主结果。"
                            )
                            logger.info(
                                "🎵 %s模式：目标时长约 %s秒，已按偏差升序选 best clip=%ss(偏差%ss)。",
                                mode_label, target_duration, best["duration"], best_err,
                            )
                            logger.info(message)

                        return MusicGenerationResult.success_result_with_clips(
                            clips=processed_clips,
                            generated_prompt=original_prompt,
                            provider=MusicProvider.SUNO,
                            task_id=task_id,
                            message=message,
                            generation_params=generation_params
                        )
                    else:
                        # abnormal status, keep waiting
                        logger.warning(f"🎵 clips 状态异常，继续等待...")
                        raise SunoTaskNotReadyException("Clips state is abnormal, waiting...")

        except SunoRetryException:
            # re-raise the retry exception
            raise
        except aiohttp.ClientError as e:
            logger.error(f"🎵 网络请求错误: {e}")
            raise SunoServerErrorException(f"Network error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🎵 JSON 解析错误: {e}")
            raise SunoServerErrorException(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"🎵 未预期的错误: {e}")
            raise SunoFinalException(f"Unexpected error: {e}")



# global service instance
_suno_service = None

def get_suno_service() -> SunoService:
    """Get the SunoAPI service instance."""
    global _suno_service
    if _suno_service is None:
        _suno_service = SunoService()
    return _suno_service

