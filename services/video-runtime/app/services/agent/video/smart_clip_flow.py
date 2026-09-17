"""Shared flow for Smart Clip and audio transcription (reused by workflow + upload-crop recommend).

Responsibility split:
- ``transcribe_audio_for_analysis``: transcription (workflow uses config; upload recommend uses the gemini fast path)
- ``run_smart_clip_analysis``: calls ``analyze_music_smart_clip``
- ``build_smart_clip_ready_payload``: full payload for workflow interrupt / DB persistence (incl. peaks)
- ``build_upload_crop_recommend_payload``: slim payload for the upload-crop dialog (start/end only)
- ``fetch_smart_clip_peaks``: optional waveform (only needed by the workflow SmartClipPanel)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ....models.video_state import UserOption
from .music_smart_clip_service import SmartClipAnalysis, analyze_music_smart_clip

logger = logging.getLogger(__name__)


async def transcribe_audio_for_analysis(
    audio_url: str,
    *,
    filename: Optional[str] = None,
    suno_clip_id: Optional[str] = None,
    user_option: Optional[UserOption] = None,
    user_input: Optional[str] = None,
    generated_lyrics: Optional[str] = None,
    music_intent: Optional[str] = None,
    music_workflow_mode: Optional[str] = None,
    fast_path: bool = False,
    language_contract: Optional[dict] = None,
):
    """Transcribe audio; when ``fast_path=True``, skip hybrid/Suno and use Gemini only (for upload crop recommend)."""
    from app.agent_config import DefaultValues, get_audio_segment_granularity_for_method

    if fast_path:
        transcription_method = "gemini"
    else:
        transcription_method = DefaultValues.TRANSCRIPTION_METHOD

    transcribe_granularity = get_audio_segment_granularity_for_method(transcription_method)

    if transcription_method == "hybrid":
        from ....tools.transcribe.hybrid import transcribe_audio_with_hybrid

        logger.info(
            "🎵 [transcribe_for_analysis] hybrid | audio_source=%s | clip_id=%s | filename=%s",
            "suno_generated" if suno_clip_id else "user_upload",
            suno_clip_id or "(none)",
            filename,
        )
        return await transcribe_audio_with_hybrid(
            audio_url,
            clip_id=suno_clip_id,
            user_option=user_option,
            user_input=user_input,
            filename=filename,
            generated_lyrics=generated_lyrics,
            granularity=transcribe_granularity,
            music_intent=music_intent,
            music_workflow_mode=music_workflow_mode,
            language_contract=language_contract,
        )

    from ....tools.transcribe.gemini import transcribe_audio_with_gemini

    logger.info(
        "🎵 [transcribe_for_analysis] %s | fast_path=%s | filename=%s",
        transcription_method,
        fast_path,
        filename,
    )
    return await transcribe_audio_with_gemini(
        audio_url,
        user_option=user_option,
        user_input=user_input,
        filename=filename,
        generated_lyrics=generated_lyrics,
        granularity=transcribe_granularity,
        music_intent=music_intent,
        music_workflow_mode=music_workflow_mode,
        language_contract=language_contract,
    )


async def run_smart_clip_analysis(
    audio_url: str,
    target_duration_sec: float,
    transcription: Any,
    *,
    audio_duration_sec: Optional[float] = None,
) -> SmartClipAnalysis:
    return await analyze_music_smart_clip(
        audio_url=audio_url,
        target_duration_sec=float(target_duration_sec),
        transcription=transcription,
        audio_duration_sec=audio_duration_sec,
    )


def build_smart_clip_ready_payload(
    sc_analysis: SmartClipAnalysis,
    audio_url: str,
    *,
    peaks: Optional[dict] = None,
) -> Dict[str, Any]:
    """Full payload for workflow gate_after_music / SmartClipPanel."""
    return {
        "status": "ready",
        "audio_url": audio_url,
        "audio_duration_sec": sc_analysis.audio_duration_sec,
        "target_duration_sec": sc_analysis.target_duration_sec,
        "recommended": sc_analysis.recommended.model_dump(),
        "fallback_used": sc_analysis.fallback_used,
        "method": sc_analysis.method,
        "peaks": peaks,
        "user_confirmed": None,
    }


def build_upload_crop_recommend_payload(sc_analysis: SmartClipAnalysis) -> Dict[str, Any]:
    """Upload-crop dialog: returns only start/end seconds, without reasoning/method/peaks."""
    return {
        "status": "ready",
        "recommended": {
            "start_sec": sc_analysis.recommended.start_sec,
            "end_sec": sc_analysis.recommended.end_sec,
        },
    }


async def fetch_smart_clip_peaks(audio_url: str, run_id: str) -> Optional[dict]:
    try:
        from ....utils import media_service_client as msc

        return await msc.audio_peaks(
            audio_url=audio_url,
            sample_count=512,
            run_id=run_id,
        )
    except Exception as e:
        logger.warning("🎵 [smart_clip] peaks 失败（前端可退化为本地波形）：%s", e)
        return None


def log_step_timing(step: str, started_at: float, **extra: Any) -> None:
    elapsed = time.monotonic() - started_at
    parts = " ".join(f"{k}={v}" for k, v in extra.items())
    logger.info("🎵 [smart_clip_timing] %s %.2fs %s", step, elapsed, parts)
