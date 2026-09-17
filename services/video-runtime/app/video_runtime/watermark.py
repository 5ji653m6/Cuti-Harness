"""Public delivery copy: same ensure-on-s3 overlay dest used, new object on storage."""
from __future__ import annotations


async def publish_public_watermark(clean_url: str, *, generation_id: str) -> str:
    """Overlay onto the clean ingest and upload a second object.

    Do not use ``ensure_video_on_our_s3`` here: that helper returns first-party
    URLs unchanged. Call Media Service directly so S3 (or local /files) gets a
    new object. No resize/strip — ingest already did that.
    """
    from app.utils import media_service_client as msc

    url = str(clean_url or "").strip()
    if not url:
        raise ValueError("publish_public_watermark requires a clean video URL")
    result = await msc.pipeline_ensure_on_s3(
        video_url=url,
        run_id=generation_id,
        strip_audio=False,
        watermark=True,
        force_watermark=True,
    )
    public = str(result.get("result_url") or "").strip()
    if not public:
        raise RuntimeError("ensure-on-s3 watermark returned no result_url")
    return public
