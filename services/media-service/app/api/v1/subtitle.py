import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.models.subtitle import (
    SubtitleBurnRequest,
    SubtitleBurnResponse,
    SubtitleComposeRequest,
    SubtitleComposeResponse,
    HyperframesCaptionRequest,
    HyperframesCaptionResponse,
)
from app.services import ffmpeg_service, hyperframes_service, subtitle_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subtitle", tags=["subtitle"])


@router.post("/compose", response_model=SubtitleComposeResponse)
async def subtitle_compose(req: SubtitleComposeRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    extension = req.format
    out_name = f"captions_{uuid.uuid4().hex[:8]}.{extension}"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    cues, validation = subtitle_service.normalize_cues(
        req.cues,
        max_lines=req.max_lines,
        max_chars_per_line=req.max_chars_per_line,
        max_cps=req.max_cps,
    )
    subtitle_service.write_subtitle(out_path, cues, req.format)
    content_type = {
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "ass": "text/x-ssa",
    }[req.format]
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", content_type)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return SubtitleComposeResponse(
        result_url=url,
        format=req.format,
        cue_count=len(cues),
        validation=validation,
    )


@router.post("/burn", response_model=SubtitleBurnResponse)
async def subtitle_burn(req: SubtitleBurnRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    video_local = await s3.ensure_local(req.video_url, ws)
    subtitle_local = await s3.ensure_local(req.subtitle_url, ws)
    if not video_local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    if not subtitle_local:
        raise HTTPException(400, f"Cannot download subtitle: {req.subtitle_url}")
    out_name = f"captioned_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    style = await ffmpeg_service.burn_subtitles(
        video_local,
        subtitle_local,
        out_path,
        style_preset=req.style_preset,
        position=req.position,
        font_name=req.font_name,
    )
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return SubtitleBurnResponse(
        result_url=url,
        duration=info["duration"],
        source_video_url=req.video_url,
        subtitle_url=req.subtitle_url,
        style=style,
    )


@router.post("/hyperframes", response_model=HyperframesCaptionResponse)
async def hyperframes_caption(req: HyperframesCaptionRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    video_local = await s3.ensure_local(req.video_url, ws)
    if not video_local:
        raise HTTPException(400, f"Cannot download video: {req.video_url}")
    out_name = f"hyperframes_captioned_{uuid.uuid4().hex[:8]}.mp4"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    try:
        style = await hyperframes_service.render_captions(
            video_local,
            out_path,
            words=req.words,
            cues=req.cues,
            style=req.style,
            accent_color=req.accent_color,
            position=req.position,
            playbook=req.playbook,
            layers=[layer.model_dump() for layer in req.layers],
            caption_html=req.caption_html,
            composition_html=req.composition_html,
        )
    except ValueError as exc:
        # the caller sent something unusable, e.g. neither caption_html nor
        # composition_html
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        # The request was fine and the renderer failed: a missing CLI, a browser
        # this image cannot probe, or a HyperFrames render error. Reporting that
        # as 422 made an environment failure look like a bad parameter.
        # 500 rather than 502: these failures are deterministic, and the runtime's
        # media client retries 502/503/504 four times with backoff, which would
        # multiply a broken image into a dozen renders.
        logger.exception("HyperFrames caption render failed for run %s", req.run_id)
        raise HTTPException(500, str(exc)) from exc
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", "video/mp4")
    info = await ffmpeg_service.get_video_info(out_path)
    await ws_svc.cleanup_if_enabled(req.run_id)
    return HyperframesCaptionResponse(
        result_url=url,
        duration=info["duration"],
        source_video_url=req.video_url,
        style=style,
    )
