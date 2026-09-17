import logging
import uuid

from fastapi import APIRouter, Request, HTTPException

from app.models.image import (
    ImageInfoRequest, ImageInfoResponse,
    ImageResizeRequest, ImageResizeResponse,
)
from app.services import image_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/image", tags=["image"])


@router.post("/info", response_model=ImageInfoResponse)
async def image_info(req: ImageInfoRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace("_probe")
    local = await s3.ensure_local(req.image_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download image: {req.image_url}")
    info = await image_service.get_image_info(local)
    return ImageInfoResponse(**info)


@router.post("/resize", response_model=ImageResizeResponse)
async def image_resize(req: ImageResizeRequest, request: Request):
    s3 = get_s3_service()
    ws_svc = request.app.state.workspace_service
    ws = ws_svc.get_workspace(req.run_id)
    local = await s3.ensure_local(req.image_url, ws)
    if not local:
        raise HTTPException(400, f"Cannot download image: {req.image_url}")
    out_name = f"resized_{uuid.uuid4().hex[:8]}.{req.format}"
    out_path = str(ws_svc.get_output_path(req.run_id, out_name))
    info = await image_service.resize_image(local, out_path, req.target_width, req.target_height, req.format, req.quality)
    ct = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}.get(req.format, "image/webp")
    url = await s3.upload(out_path, f"media/{req.run_id}/{out_name}", ct)
    return ImageResizeResponse(result_url=url, **info)
