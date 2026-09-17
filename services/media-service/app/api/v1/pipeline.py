import logging
import uuid

from fastapi import APIRouter, Request, HTTPException

from app.config import get_settings
from app.models.pipeline import (
    SegmentProcessRequest, SegmentProcessResponse,
    EnsureOnS3Request,
    WorkspaceCleanupRequest, WorkspaceCleanupResponse,
)
from app.models.common import MediaResult
from app.services import ffmpeg_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def should_apply_watermark(
    *,
    requested: bool,
    source_is_first_party: bool,
    force: bool = False,
) -> bool:
    """Ingest is one-shot. A delivery copy from a clean canonical may force one overlay."""
    if not requested:
        return False
    if force:
        return True
    return not source_is_first_party


@router.post("/segment-process", response_model=SegmentProcessResponse)
async def segment_process(req: SegmentProcessRequest, request: Request):
    """Download multiple videos → align durations → concat → normalize → trim → upload.

    When normalize=True, each segment output is re-encoded to uniform h264/1920x1080/24fps
    so the final cross-segment concat can safely use -c copy without timestamp drift.
    """
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)

    aligned_paths = []
    for i, seg in enumerate(req.videos):
        local = await s3.ensure_local(seg.url, ws)
        if not local:
            raise HTTPException(400, f"Cannot download: {seg.url}")
        aligned_name = f"aligned_{i}_{uuid.uuid4().hex[:8]}.mp4"
        aligned_path = str(ws_svc.get_intermediate_path(req.run_id, aligned_name))
        await ffmpeg_service.trim_video(local, aligned_path, seg.target_duration, "pad_or_trim")
        aligned_paths.append(aligned_path)

    if len(aligned_paths) > 1:
        concat_name = f"concat_{uuid.uuid4().hex[:8]}.mp4"
        concat_path = str(ws_svc.get_intermediate_path(req.run_id, concat_name))
        await ffmpeg_service.concat_videos(aligned_paths, concat_path, normalize=False)
    else:
        concat_path = aligned_paths[0]

    if req.total_target_duration > 0:
        info = await ffmpeg_service.get_video_info(concat_path)
        if abs(info["duration"] - req.total_target_duration) > 0.02:
            trimmed_name = f"trimmed_{uuid.uuid4().hex[:8]}.mp4"
            trimmed_path = str(ws_svc.get_output_path(req.run_id, trimmed_name))
            await ffmpeg_service.trim_video(concat_path, trimmed_path, req.total_target_duration)
            concat_path = trimmed_path

    if req.normalize:
        infos = [await ffmpeg_service.get_video_info(p) for p in aligned_paths]
        tw, th, target_fps = ffmpeg_service._pick_reference_params(infos)
        uniform_name = f"uniform_{uuid.uuid4().hex[:8]}.mp4"
        uniform_path = str(ws_svc.get_output_path(req.run_id, uniform_name))
        await ffmpeg_service.ensure_uniform_encoding(
            concat_path, uniform_path,
            target_width=tw, target_height=th, target_fps=target_fps,
        )
        concat_path = uniform_path

    url = await s3.upload(concat_path, f"media/{req.run_id}/segment_{uuid.uuid4().hex[:8]}.mp4", "video/mp4")
    info = await ffmpeg_service.get_video_info(concat_path)
    return SegmentProcessResponse(result_url=url, duration=info["duration"])


@router.post("/ensure-on-s3", response_model=MediaResult)
async def ensure_on_s3(req: EnsureOnS3Request, request: Request):
    """Download external URL and normalize it without compounding watermarks.

    A first-party URL may be submitted again during retry, recovery, or an
    incremental edit.  It is already a persisted artifact, so applying the
    delivery watermark again would permanently stack another copy into the
    pixels.  Normalization may still run, but watermarking is one-shot.
    """
    import time as _time
    _req_t0 = _time.monotonic()
    logger.info(
        "ensure_on_s3 START run_id=%s url=%.80s target=%sx%s fps=%s dur=%s strip=%s wm=%s",
        req.run_id, req.external_url,
        req.target_width, req.target_height, req.target_fps,
        req.target_duration, req.strip_audio, req.watermark,
    )
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.external_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download: {req.external_url}")
    _dl_elapsed = _time.monotonic() - _req_t0
    logger.info("ensure_on_s3 DOWNLOAD done in %.1fs: %s", _dl_elapsed, local)

    info = await ffmpeg_service.get_video_info(local)
    logger.info(
        "ensure_on_s3 PROBE: %dx%d fps=%.1f dur=%.2f codec=%s pix_fmt=%s audio=%s "
        "| target=%sx%s fps=%s dur=%s strip_audio=%s watermark=%s",
        info.get("width", 0), info.get("height", 0), info.get("fps", 0),
        info.get("duration", 0),
        info.get("codec"), info.get("pix_fmt"), info.get("has_audio"),
        req.target_width, req.target_height, req.target_fps,
        req.target_duration, req.strip_audio, req.watermark,
    )

    wm_path = None
    apply_watermark = should_apply_watermark(
        requested=req.watermark,
        source_is_first_party=s3.is_our_url(req.external_url),
        force=req.force_watermark,
    )
    if req.watermark and not apply_watermark:
        logger.info(
            "ensure_on_s3: skip repeated watermark for first-party artifact: %.120s",
            req.external_url,
        )
    if apply_watermark:
        from ...config import resolve_watermark_image_path
        cfg = get_settings()
        wm_path = resolve_watermark_image_path(cfg.watermark_image_path)
        if not wm_path:
            logger.warning(
                "ensure_on_s3: watermark=True but no valid image (watermark_image_path=%r)",
                cfg.watermark_image_path,
            )

    final_path = local
    need_normalize = req.target_width and req.target_height
    need_fps = req.target_fps and req.target_fps > 0
    need_strip = req.strip_audio
    need_trim = req.target_duration is not None and req.target_duration > 0
    need_watermark = wm_path is not None

    if need_normalize or need_fps or need_strip or need_trim or need_watermark:
        norm_name = f"norm_{uuid.uuid4().hex[:8]}.mp4"
        norm_path = str(ws_svc.get_intermediate_path(req.run_id, norm_name))
        await ffmpeg_service.ensure_uniform_encoding(
            local, norm_path,
            target_width=req.target_width,
            target_height=req.target_height,
            target_fps=float(req.target_fps) if req.target_fps else None,
            target_duration=req.target_duration,
            watermark_path=wm_path,
            strip_audio=req.strip_audio,
        )
        final_path = norm_path

    out_name = f"ensured_{uuid.uuid4().hex[:8]}.mp4"
    _upload_t0 = _time.monotonic()
    url = await s3.upload(final_path, f"videos/{out_name}", "video/mp4")
    _total = _time.monotonic() - _req_t0
    logger.info(
        "ensure_on_s3 DONE run_id=%s total=%.1fs (dl=%.1fs upload=%.1fs) → %s",
        req.run_id, _total, _dl_elapsed, _time.monotonic() - _upload_t0, url,
    )
    return MediaResult(result_url=url)


@router.post("/workspace/cleanup", response_model=WorkspaceCleanupResponse)
async def workspace_cleanup(req: WorkspaceCleanupRequest, request: Request):
    ws_svc = request.app.state.workspace_service
    count, freed = await ws_svc.cleanup(req.run_id)
    return WorkspaceCleanupResponse(cleaned_files=count, freed_mb=freed)
