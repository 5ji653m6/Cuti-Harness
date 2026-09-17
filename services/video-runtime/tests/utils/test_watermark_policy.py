import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.s3_utils import S3Utils
from app.video_runtime.watermark import publish_public_watermark


def test_canonical_video_ingest_defaults_to_no_watermark():
    parameter = inspect.signature(S3Utils.ensure_video_on_our_s3).parameters["watermark"]
    assert parameter.default is False


@pytest.mark.asyncio
async def test_public_overlay_uses_ensure_on_s3_not_local_ffmpeg():
    ensure = AsyncMock(return_value={"result_url": "https://cdn.example/public-wm.mp4"})
    with patch("app.utils.media_service_client.pipeline_ensure_on_s3", ensure):
        url = await publish_public_watermark(
            "https://cdn.example/clean.mp4",
            generation_id="build-1",
        )
    assert url == "https://cdn.example/public-wm.mp4"
    ensure.assert_awaited_once()
    kwargs = ensure.await_args.kwargs
    assert kwargs["video_url"] == "https://cdn.example/clean.mp4"
    assert kwargs["watermark"] is True
    assert kwargs["force_watermark"] is True
    assert kwargs["strip_audio"] is False
    assert kwargs.get("target_width") is None
    assert kwargs.get("target_height") is None
