"""finalize_pipeline_video_upload：lipsync 双 URL vs 普通单 URL。"""
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.video_utils import finalize_pipeline_video_upload


@pytest.mark.asyncio
async def test_lipsync_preview_returns_muted_and_preview():
    with patch(
        "app.utils.video_utils.ensure_lipsync_video_with_preview",
        new_callable=AsyncMock,
        return_value=("https://cdn/preview.mp4", "https://cdn/muted.mp4"),
    ) as mock_lipsync:
        pipeline, preview = await finalize_pipeline_video_upload(
            "https://vendor/out.mp4",
            generation_id="shot_1",
            lipsync_preview=True,
        )
    mock_lipsync.assert_awaited_once()
    assert pipeline == "https://cdn/muted.mp4"
    assert preview == "https://cdn/preview.mp4"


@pytest.mark.asyncio
async def test_normal_i2v_returns_only_pipeline():
    with patch(
        "app.utils.s3_utils.s3_utils.ensure_video_on_our_s3",
        new_callable=AsyncMock,
        return_value="https://cdn/silent.mp4",
    ) as mock_ensure:
        pipeline, preview = await finalize_pipeline_video_upload(
            "https://vendor/out.mp4",
            generation_id="shot_2",
            lipsync_preview=False,
        )
    mock_ensure.assert_awaited_once()
    assert pipeline == "https://cdn/silent.mp4"
    assert preview is None
