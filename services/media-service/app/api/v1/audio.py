import logging
import uuid

from fastapi import APIRouter, Request, HTTPException

from app.models.audio import (
    AudioInfoRequest, AudioInfoResponse,
    AudioTrimRequest, AudioTrimWithFadeRequest,
    AudioExtractRequest, AudioConvertRequest,
    AudioPeaksRequest, AudioPeaksResponse,
)
from app.models.common import MediaResult
from app.services import ffmpeg_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audio", tags=["audio"])


@router.post("/info", response_model=AudioInfoResponse)
async def audio_info(req: AudioInfoRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace("_probe")
    local = await s3.ensure_local(req.audio_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download audio: {req.audio_url}")
    dur = await ffmpeg_service.get_audio_duration(local)
    return AudioInfoResponse(duration=dur)


@router.post("/trim", response_model=MediaResult)
async def audio_trim(req: AudioTrimRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.audio_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download audio: {req.audio_url}")
    out_name = f"trimmed_{uuid.uuid4().hex[:8]}.mp3"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    # Re-encode (not -c copy) so duration stays within the requested window.
    await ffmpeg_service.trim_audio(local, out_path, req.start, req.duration)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "audio/mpeg")
    return MediaResult(result_url=url)


@router.post("/trim-with-fade", response_model=MediaResult)
async def audio_trim_with_fade(req: AudioTrimWithFadeRequest, request: Request):
    """Trim + fade in/out (for music smart clipping).

    Difference from /audio/trim:
    - cannot -c copy (uses the -af filter)
    - output is uniformly mp3
    - fade time is within the trimmed segment (0..duration)
    """
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.audio_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download audio: {req.audio_url}")
    out_name = f"trimfade_{uuid.uuid4().hex[:8]}.mp3"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.trim_audio_with_fade(
        local, out_path, req.start, req.duration,
        fade_in_sec=req.fade_in_sec, fade_out_sec=req.fade_out_sec,
    )
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "audio/mpeg")
    return MediaResult(result_url=url)


@router.post("/peaks", response_model=AudioPeaksResponse)
async def audio_peaks(req: AudioPeaksRequest, request: Request):
    """Extract a normalized peak array (frontend canvas waveform)."""
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.audio_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download audio: {req.audio_url}")
    duration, values = await ffmpeg_service.extract_audio_peaks(local, req.sample_count)
    return AudioPeaksResponse(
        sample_count=req.sample_count,
        duration=duration,
        values=values,
    )


@router.post("/extract-from-video", response_model=MediaResult)
async def audio_extract(req: AudioExtractRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"extracted_{uuid.uuid4().hex[:8]}.{req.format}"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    extracted = await ffmpeg_service.extract_audio(local, out_path, req.format, req.quality)
    if not extracted:
        logger.info("audio_extract: video has no audio stream, result_url=null run_id=%s", req.run_id)
        return MediaResult(result_url=None)
    content_type = "audio/mpeg" if req.format == "mp3" else f"audio/{req.format}"
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", content_type)
    return MediaResult(result_url=url)


@router.post("/convert", response_model=MediaResult)
async def audio_convert(req: AudioConvertRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.audio_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download audio: {req.audio_url}")
    out_name = f"converted_{uuid.uuid4().hex[:8]}.{req.target_format}"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.convert_audio(local, out_path)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", f"audio/{req.target_format}")
    return MediaResult(result_url=url)
