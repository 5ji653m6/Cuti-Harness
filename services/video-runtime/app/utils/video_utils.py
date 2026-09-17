"""Live video helpers used by providers and lipsync upload.

Shot assembly lives in Cuti Media Service (`app.utils.media_service_client`).
This module only wraps the few post-generation steps still called from tools.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid
from typing import Optional, Tuple

from . import media_service_client as msc
from .image_utils import DOWNSCALE_FORCE_EXACT_THRESHOLD

logger = logging.getLogger(__name__)


def normalize_video_to_target_sync(
    input_path: str,
    target_width: int,
    target_height: int,
) -> Tuple[str, dict]:
    """Scale a local file to the standard resolution used by Sora uploads."""
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", input_path,
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            logger.warning("normalize_video_to_target_sync: 无视频流，跳过")
            return input_path, {"orig_w": None, "orig_h": None, "out_w": None, "out_h": None}
        w = int(streams[0].get("width", 0))
        h = int(streams[0].get("height", 0))
        if w <= 0 or h <= 0:
            return input_path, {"orig_w": w, "orig_h": h, "out_w": w, "out_h": h}
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as e:
        logger.warning("normalize_video_to_target_sync: ffprobe 失败 %s，跳过", e)
        return input_path, {}

    tw, th = target_width, target_height
    if w >= tw and h >= th:
        scale = min(tw / w, th / h)
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        diff_w = abs(new_w - tw) / tw if tw else 0
        diff_h = abs(new_h - th) / th if th else 0
        rel_diff = max(diff_w, diff_h)
        if rel_diff < DOWNSCALE_FORCE_EXACT_THRESHOLD:
            out_w, out_h = tw, th
            force_exact = True
        else:
            out_w, out_h = new_w, new_h
            force_exact = False
    else:
        diff_w = abs(w - tw) / tw if tw else 0
        diff_h = abs(h - th) / th if th else 0
        rel_diff = max(diff_w, diff_h)
        if rel_diff < DOWNSCALE_FORCE_EXACT_THRESHOLD:
            out_w, out_h = tw, th
            force_exact = True
        else:
            out_w, out_h = w, h
            force_exact = False

    if (out_w, out_h) == (w, h):
        logger.info(
            "视频归一化: 原图 %dx%d 已为目标 %dx%d，跳过",
            w, h, tw, th,
        )
        return input_path, {"orig_w": w, "orig_h": h, "out_w": w, "out_h": h, "force_exact": False}

    out_w = max(2, out_w & ~1)
    out_h = max(2, out_h & ~1)

    logger.info(
        "视频归一化: 原图 %dx%d → 目标 %dx%d → 输出 %dx%d (force_exact=%s)",
        w, h, tw, th, out_w, out_h, force_exact,
    )
    fd, output_path = tempfile.mkstemp(suffix=".mp4", prefix="video_norm_")
    os.close(fd)
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={out_w}:{out_h}",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
    except subprocess.CalledProcessError as e:
        try:
            os.unlink(output_path)
        except FileNotFoundError:
            pass
        logger.warning("normalize_video_to_target_sync: ffmpeg 失败 %s", e.stderr.decode() if e.stderr else e)
        return input_path, {"orig_w": w, "orig_h": h, "out_w": w, "out_h": h}

    return output_path, {"orig_w": w, "orig_h": h, "out_w": out_w, "out_h": out_h, "force_exact": force_exact}


async def trim_video_to_duration(video_url: str, target_duration: float) -> str:
    """Trim a generated clip to the audio duration (lipsync / Wan)."""
    result = await msc.video_trim(
        video_url,
        target_duration,
        run_id=uuid.uuid4().hex[:12],
        tolerance=0.0,
    )
    logger.info(f"✅ Media service video_trim: {video_url} -> {result['result_url']}")
    return result["result_url"]


async def strip_audio_from_video(video_url: str) -> str:
    """Drop the vendor soundtrack so later mix/concat can add BGM."""
    result = await msc.video_strip_audio(video_url, run_id=uuid.uuid4().hex[:12])
    logger.info(f"✅ Media service strip_audio: {video_url} -> {result['result_url']}")
    return result["result_url"]


async def ensure_lipsync_video_with_preview(
    remote_video_url: str,
    *,
    generation_id: str,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
) -> tuple[str, str]:
    """Upload a lipsync take: preview keeps audio, pipeline clip is muted."""
    from ..utils.s3_utils import s3_utils

    preview_url = await s3_utils.ensure_video_on_our_s3(
        remote_video_url,
        generation_id=f"{generation_id}_preview",
        target_width=target_width,
        target_height=target_height,
        strip_audio=False,
    )
    try:
        muted_url = await strip_audio_from_video(preview_url)
    except Exception as e:
        logger.warning("strip_audio 失败，回退 ensure strip_audio=True: %s", e)
        muted_url = await s3_utils.ensure_video_on_our_s3(
            remote_video_url,
            generation_id=generation_id,
            target_width=target_width,
            target_height=target_height,
            strip_audio=True,
        )
    return preview_url, muted_url


async def finalize_pipeline_video_upload(
    remote_video_url: str,
    *,
    generation_id: str,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
    lipsync_preview: bool = False,
) -> tuple[str, Optional[str]]:
    """Ingest a vendor clip onto our storage. Lipsync also keeps a preview URL."""
    if lipsync_preview:
        preview_url, muted_url = await ensure_lipsync_video_with_preview(
            remote_video_url,
            generation_id=generation_id,
            target_width=target_width,
            target_height=target_height,
        )
        return muted_url, preview_url
    from ..utils.s3_utils import s3_utils

    pipeline_url = await s3_utils.ensure_video_on_our_s3(
        remote_video_url,
        generation_id=generation_id,
        target_width=target_width,
        target_height=target_height,
    )
    return pipeline_url, None


async def get_audio_duration_from_url(audio_input: str) -> Optional[float]:
    """Return the real audio duration from Media Service."""
    result = await msc.audio_info(audio_input)
    return result["duration"]
