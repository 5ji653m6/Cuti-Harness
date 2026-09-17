"""
Google file-upload utility
Uploads large files to Google to get a file_uri, bypassing the LangSmith size limit
"""
import logging
import os
import asyncio
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Google Genai client (lazy initialization)
_genai_client = None


def _get_genai_client():
    """Get or create the Google Genai client."""
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            _genai_client = genai.Client(api_key=api_key) if api_key else genai.Client()
            logger.info("✅ Google GenAI 客户端初始化成功")
        except Exception as e:
            logger.error(f"❌ Google GenAI 客户端初始化失败: {e}")
            raise
    return _genai_client


async def upload_video_to_google(video_path: str, max_wait_time: int = 300) -> tuple[Optional[str], Optional[str]]:
    """
    Upload a video to Google's servers and wait for processing to complete (async version).

    Args:
        video_path: local video file path
        max_wait_time: max wait time (seconds), default 300s (5 minutes)

    Returns:
        a (file_uri, mime_type) tuple.
        - file_uri: the Google file URI
        - mime_type: the MIME type Google actually recognized
        When sending a Gemini request with file_uri, mime_type must match what Google recorded,
        otherwise Gemini returns 400 Invalid argument.
        Returns (None, None) on failure.

    Notes:
        - Using file_uri bypasses the LangSmith size limit (26MB)
        - After upload you must wait for processing to complete before use
        - The wait time auto-adjusts by file size, but never exceeds max_wait_time
    """
    try:
        # get the genai client
        client = _get_genai_client()

        # check the file size and adjust the wait time accordingly
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        logger.info(f"📤 上传视频到 Google: {video_path}, 大小: {file_size_mb:.2f} MB")

        # dynamically adjust the wait time by file size (large files need longer processing)
        # base wait 60s, +30s per additional 10MB, but never exceeding max_wait_time
        base_wait_time = 60
        additional_wait = min(int(file_size_mb / 10) * 30, max_wait_time - base_wait_time)
        adjusted_wait_time = min(base_wait_time + additional_wait, max_wait_time)
        logger.info(f"⏱️ 根据文件大小调整等待时间: {adjusted_wait_time}秒（最大: {max_wait_time}秒）")

        # upload the file (sync operation, run in an executor)
        loop = asyncio.get_event_loop()
        uploaded_file = await loop.run_in_executor(
            None,
            lambda: client.files.upload(file=video_path)
        )
        logger.info(f"✅ 视频已上传，URI: {uploaded_file.uri}")

        # wait for processing to complete (async polling)
        start_time = time.time()
        check_interval = 2  # check every 2 seconds

        while uploaded_file.state.name == "PROCESSING":
            elapsed = time.time() - start_time
            if elapsed > adjusted_wait_time:
                logger.warning(f"⚠️ 视频处理超时（{adjusted_wait_time}秒），但继续等待直到最大时间（{max_wait_time}秒）")
                # if it exceeds the adjusted wait time but not the max, keep waiting
                if elapsed > max_wait_time:
                    logger.error(f"❌ 视频处理超时（{max_wait_time}秒）")
                    return None, None

            await asyncio.sleep(check_interval)

            # get the latest status (sync operation, run in an executor)
            uploaded_file = await loop.run_in_executor(
                None,
                lambda: client.files.get(name=uploaded_file.name)
            )
            logger.debug(f"⏳ 视频处理状态: {uploaded_file.state.name}, 已等待: {elapsed:.0f}秒")

        if uploaded_file.state.name == "ACTIVE":
            elapsed = time.time() - start_time
            actual_mime = getattr(uploaded_file, "mime_type", None)
            logger.info(f"✅ 视频处理完成，URI: {uploaded_file.uri}, mime_type: {actual_mime}, 耗时: {elapsed:.0f}秒")
            return uploaded_file.uri, actual_mime
        else:
            logger.error(f"❌ 视频处理失败，状态: {uploaded_file.state.name}")
            return None, None

    except Exception as e:
        logger.error(f"❌ 上传视频到 Google 失败: {e}", exc_info=True)
        return None, None


async def upload_audio_to_google(audio_path: str, max_wait_time: int = 300) -> tuple[Optional[str], Optional[str]]:
    """
    Upload audio to Google's servers and wait for processing to complete (async version).
    Same flow as upload_video_to_google, for large audio bypassing Gemini's 20MB inline limit.

    Args:
        audio_path: local audio file path
        max_wait_time: max wait time (seconds), default 300s (5 minutes)

    Returns:
        a (file_uri, mime_type) tuple.
        - file_uri: the Google file URI (e.g. https://generativelanguage.googleapis.com/v1beta/files/xxx)
        - mime_type: the MIME type Google actually recognized (e.g. audio/x-wav)
        When sending a Gemini request with file_uri, mime_type must match what Google recorded,
        otherwise Gemini returns 400 Invalid argument.
        Returns (None, None) on failure.

    Notes:
        - Using file_uri bypasses Gemini's 20MB request-body limit
        - After upload you must wait for processing to complete before use
    """
    try:
        client = _get_genai_client()
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        logger.info(f"📤 上传音频到 Google: {audio_path}, 大小: {file_size_mb:.2f} MB")

        base_wait_time = 60
        additional_wait = min(int(file_size_mb / 10) * 30, max_wait_time - base_wait_time)
        adjusted_wait_time = min(base_wait_time + additional_wait, max_wait_time)
        logger.info(f"⏱️ 音频处理等待时间: {adjusted_wait_time}秒（最大: {max_wait_time}秒）")

        loop = asyncio.get_event_loop()
        uploaded_file = await loop.run_in_executor(
            None,
            lambda: client.files.upload(file=audio_path)
        )
        logger.info(f"✅ 音频已上传，URI: {uploaded_file.uri}")

        start_time = time.time()
        check_interval = 2
        while uploaded_file.state.name == "PROCESSING":
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                logger.error(f"❌ 音频处理超时（{max_wait_time}秒）")
                return None, None
            await asyncio.sleep(check_interval)
            uploaded_file = await loop.run_in_executor(
                None,
                lambda: client.files.get(name=uploaded_file.name)
            )
            logger.debug(f"⏳ 音频处理状态: {uploaded_file.state.name}, 已等待: {elapsed:.0f}秒")

        if uploaded_file.state.name == "ACTIVE":
            elapsed = time.time() - start_time
            actual_mime = getattr(uploaded_file, "mime_type", None)
            logger.info(f"✅ 音频处理完成，URI: {uploaded_file.uri}, mime_type: {actual_mime}, 耗时: {elapsed:.0f}秒")
            return uploaded_file.uri, actual_mime
        logger.error(f"❌ 音频处理失败，状态: {uploaded_file.state.name}")
        return None, None
    except Exception as e:
        logger.error(f"❌ 上传音频到 Google 失败: {e}", exc_info=True)
        return None, None
