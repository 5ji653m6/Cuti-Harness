import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException

from app.models.video import (
    VideoInfoRequest, VideoInfoResponse,
    VideoTrimRequest, VideoTrimResponse,
    VideoConcatRequest, VideoConcatResponse,
    VideoSpeedRequest, VideoSpeedResponse,
    VideoNormalizeRequest, VideoNormalizeResponse,
    VideoWatermarkRequest, VideoStripAudioRequest,
    VideoMixAudioRequest, VideoAddAudioRequest,
    VideoPlaceholderRequest,
    VideoExtractFrameRequest, VideoExtractFrameResponse,
    HyperframesRenderRequest, HyperframesRenderResponse,
)
from app.models.common import MediaResult
from app.services import ffmpeg_service, hyperframes_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/video", tags=["video"])


@router.post("/hyperframes/render", response_model=HyperframesRenderResponse)
async def hyperframes_render(req: HyperframesRenderRequest, request: Request):
    """Render an Agent-authored deterministic HTML composition without a source video."""
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    out_name = f"hyperframes_rendered_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    try:
        metadata = await hyperframes_service.render_composition(
            out_path,
            composition_html=req.composition_html,
            width=req.width,
            height=req.height,
            duration=req.duration,
            fps=req.fps,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("HyperFrames composition render failed for run %s", req.run_id)
        raise HTTPException(500, str(exc)) from exc
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return HyperframesRenderResponse(
        result_url=url,
        duration=info["duration"],
        width=int(info.get("width") or req.width),
        height=int(info.get("height") or req.height),
        fps=float(info.get("fps") or req.fps),
        render_metadata=metadata,
    )


@router.post("/info", response_model=VideoInfoResponse)
async def video_info(req: VideoInfoRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace("_probe")
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    info = await ffmpeg_service.get_video_info(local)
    if ws_svc.auto_cleanup:
        try:
            Path(local).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Probe file cleanup failed %s: %s", local, e)
    return VideoInfoResponse(**info)


@router.post("/trim", response_model=VideoTrimResponse)
async def video_trim(req: VideoTrimRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"trimmed_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.trim_video(
        local,
        out_path,
        req.target_duration,
        req.mode,
        skip_if_within_sec=req.tolerance,
    )
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return VideoTrimResponse(result_url=url, duration=info["duration"])


@router.post("/concat", response_model=VideoConcatResponse)
async def video_concat(req: VideoConcatRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    async def _download(vu: str):
        lp = await s3.ensure_local(vu, ws)
        if not lp:
            raise HTTPException(400, f"Cannot download: {vu}")
        return lp

    locals_ = await asyncio.gather(*[_download(vu) for vu in req.video_urls])
    out_name = f"concat_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.concat_videos(
        locals_,
        out_path,
        normalize=req.normalize,
        transition_duration=req.transition_duration,
    )
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return VideoConcatResponse(result_url=url, duration=info["duration"])


@router.post("/speed-adjust", response_model=VideoSpeedResponse)
async def video_speed(req: VideoSpeedRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"speed_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.speed_adjust(local, out_path, req.target_duration)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return VideoSpeedResponse(result_url=url, duration=info["duration"])


@router.post("/normalize", response_model=VideoNormalizeResponse)
async def video_normalize(req: VideoNormalizeRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"norm_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    meta = await ffmpeg_service.normalize_video(local, out_path, req.target_width, req.target_height)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    await ws_svc.cleanup_if_enabled(req.run_id)
    return VideoNormalizeResponse(result_url=url, metadata=meta)


@router.post("/strip-audio", response_model=MediaResult)
async def video_strip_audio(req: VideoStripAudioRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"muted_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.strip_audio(local, out_path)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    await ws_svc.cleanup_if_enabled(req.run_id)
    return MediaResult(result_url=url)


@router.post("/mix-audio", response_model=MediaResult)
async def video_mix_audio(req: VideoMixAudioRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    v_local = await s3.ensure_local(req.video_url, ws)
    a_local = await s3.ensure_local(req.audio_url, ws)
    if not v_local or not a_local:
        raise HTTPException(400, "Cannot download video or audio")
    out_name = f"mixed_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.mix_audio(v_local, a_local, out_path, req.audio_volume, req.loop_audio)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    await ws_svc.cleanup_if_enabled(req.run_id)
    return MediaResult(result_url=url)


@router.post("/add-audio", response_model=MediaResult)
async def video_add_audio(req: VideoAddAudioRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    v_local = await s3.ensure_local(req.video_url, ws)
    if not v_local:
        raise HTTPException(400, "Cannot download video")
    if not req.audio_segments:
        raise HTTPException(400, "No audio segments")
    a_url = req.audio_segments[0].get("audio_url", "")
    a_local = await s3.ensure_local(a_url, ws)
    if not a_local:
        raise HTTPException(400, "Cannot download audio")
    out_name = f"with_audio_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.add_audio_track(v_local, a_local, out_path)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    await ws_svc.cleanup_if_enabled(req.run_id)
    return MediaResult(result_url=url)


@router.post("/create-placeholder", response_model=MediaResult)
async def video_placeholder(req: VideoPlaceholderRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    out_name = f"black_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    await ffmpeg_service.create_placeholder(out_path, req.duration, req.width, req.height, req.fps)
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    await ws_svc.cleanup_if_enabled(req.run_id)
    return MediaResult(result_url=url)


@router.post("/extract-frame", response_model=VideoExtractFrameResponse)
async def video_extract_frame(req: VideoExtractFrameRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.video_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    image_format = (req.format or "jpeg").strip().lower()
    if image_format in {"jpg", "jpeg"}:
        image_format = "jpeg"
        ext = "jpg"
        content_type = "image/jpeg"
    elif image_format == "png":
        ext = "png"
        content_type = "image/png"
    else:
        raise HTTPException(400, f"Unsupported format: {req.format}")
    out_name = f"frame_{uuid.uuid4().hex[:8]}.{ext}"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    meta = await ffmpeg_service.extract_frame(
        local,
        out_path,
        req.timestamp,
        position=req.position,
        image_format=image_format,
    )
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", content_type)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return VideoExtractFrameResponse(
        result_url=url,
        timestamp=meta["timestamp"],
        width=meta.get("width"),
        height=meta.get("height"),
        format=meta.get("format") or image_format,
    )
