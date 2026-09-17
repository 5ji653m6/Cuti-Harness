from unittest.mock import AsyncMock, patch
import time

import pytest

from app.chat.utils.file_utils import (
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    assert_upload_size,
    process_uploaded_files,
    read_uploaded_file_capped,
)
from app.chat.exceptions import BusinessException
from app.exceptions import BusinessExceptionCode
from app.chat.v2.host_gateway import HostGateway, HostGatewayError
from app.video_runtime.builtin_plugins.media_core import MediaCorePlugin
from app.video_runtime.security import CapabilityExecutionEnvelope, CapabilityGrant


class _FakeUpload:
    def __init__(self, filename, content_type, data=b"", size=None, fail_on_read=False):
        self.filename = filename
        self.content_type = content_type
        self._data = data
        self.size = size
        self.fail_on_read = fail_on_read
        self._offset = 0

    async def read(self, n=-1):
        if self.fail_on_read:
            raise AssertionError("upload body should not be read when declared size exceeds the cap")
        if n is None or n < 0:
            chunk = self._data[self._offset:]
            self._offset = len(self._data)
            return chunk
        chunk = self._data[self._offset:self._offset + n]
        self._offset += len(chunk)
        return chunk


def test_upload_limits_reject_oversized_image_and_allow_2gb_video():
    with pytest.raises(BusinessException) as oversized:
        assert_upload_size("image", MAX_IMAGE_UPLOAD_BYTES + 1, "hero.png")
    assert oversized.value.error_code == BusinessExceptionCode.FILE_TOO_LARGE
    assert_upload_size("image", MAX_IMAGE_UPLOAD_BYTES, "hero.png")
    assert_upload_size("video", MAX_VIDEO_UPLOAD_BYTES, "clip.mp4")
    with pytest.raises(BusinessException) as video:
        assert_upload_size("video", MAX_VIDEO_UPLOAD_BYTES + 1, "clip.mp4")
    assert video.value.error_code == BusinessExceptionCode.FILE_TOO_LARGE


@pytest.mark.asyncio
async def test_declared_size_rejects_before_reading_body():
    upload = _FakeUpload(
        "huge.png",
        "image/png",
        data=b"not-read",
        size=MAX_IMAGE_UPLOAD_BYTES + 1,
        fail_on_read=True,
    )
    with pytest.raises(BusinessException) as exc:
        await read_uploaded_file_capped(upload, file_type="image", filename="huge.png")
    assert exc.value.error_code == BusinessExceptionCode.FILE_TOO_LARGE


@pytest.mark.asyncio
async def test_stream_read_stops_after_crossing_cap():
    payload = b"\x89PNG" + b"\x00" * (MAX_IMAGE_UPLOAD_BYTES + 64)
    upload = _FakeUpload("huge.png", "image/png", data=payload, size=None)
    with pytest.raises(BusinessException) as exc:
        await read_uploaded_file_capped(upload, file_type="image", filename="huge.png")
    assert exc.value.error_code == BusinessExceptionCode.FILE_TOO_LARGE
    assert upload._offset <= MAX_IMAGE_UPLOAD_BYTES + 1024 * 1024


@pytest.mark.asyncio
async def test_unknown_type_rejected_without_reading():
    upload = _FakeUpload(
        "notes.txt",
        "text/plain",
        data=b"x" * 100,
        fail_on_read=True,
    )
    with pytest.raises(BusinessException) as exc:
        await process_uploaded_files([upload])
    assert exc.value.error_code == BusinessExceptionCode.UNSUPPORTED_FILE_FORMAT


@pytest.mark.asyncio
async def test_media_video_analyze_requires_url():
    with pytest.raises(HostGatewayError, match="requires video_url"):
        await HostGateway().media_video_analyze({})


@pytest.mark.asyncio
async def test_media_video_analyze_returns_videomap(monkeypatch):
    async def _info(_url):
        return {"duration": 12.5}

    async def _analyze(**kwargs):
        assert kwargs["video_url"] == "http://localhost/files/ref.mp4"
        assert kwargs["question"] == "who is on screen?"
        assert kwargs["language_contract"] is None
        return {
            "duration_sec": 12.5,
            "summary": "A red product on a table",
            "characters": [],
            "storyboard": [{"start_sec": 0, "end_sec": 12.5, "action": "hold", "on_screen": "product"}],
            "overall_style": "studio",
            "mood": "calm",
            "color_palette": "red/white",
            "spoken_or_on_screen_text": "",
            "answer": "one product",
        }

    monkeypatch.setattr("app.utils.media_service_client.video_info", _info)
    monkeypatch.setattr("app.tools.video_analyze.gemini.analyze_video_with_gemini", _analyze)
    result = await HostGateway().media_video_analyze({
        "video_url": "http://localhost/files/ref.mp4",
        "question": "who is on screen?",
    })
    assert result["title"] == "videomap"
    assert "red product" in result["summary"]
    assert result["answer"] == "one product"


@pytest.mark.asyncio
async def test_media_video_analyze_forwards_content_language_contract(monkeypatch):
    captured = {}

    async def _info(_url):
        return {"duration": 8.0}

    async def _analyze(**kwargs):
        captured.update(kwargs)
        return {
            "duration_sec": 8.0,
            "summary": "A dancer",
            "characters": [],
            "storyboard": [],
        }

    monkeypatch.setattr("app.utils.media_service_client.video_info", _info)
    monkeypatch.setattr("app.tools.video_analyze.gemini.analyze_video_with_gemini", _analyze)
    contract = {
        "ui_locale": "zh-CN",
        "content_language": "en-US",
        "spoken_language": "zh-CN",
        "subtitle_language": "en-US",
        "provider_prompt_language": "auto",
    }
    result = await HostGateway().media_video_analyze({
        "video_url": "http://localhost/files/ref.mp4",
        "language_contract": contract,
    })
    assert captured["language_contract"]["content_language"] == "en-US"
    assert captured["language_contract"]["ui_locale"] == "zh-CN"
    assert "dancer" in result["summary"]


@pytest.mark.asyncio
async def test_media_core_forwards_plan_language_contract_to_video_analyze():
    grant = CapabilityGrant(
        project_id="project-1",
        session_id="session-1",
        user_id="user-1",
        plugin_id="cuti.media-core",
        capability="media.video_analyze",
        allowed_capabilities=["media.video_analyze"],
        max_cost_usd=1,
        timeout_seconds=30,
        idempotency_key="key-video-analyze",
        audit_id="audit-1",
        nonce="nonce-1",
        expires_at=int(time.time()) + 60,
    )
    envelope = CapabilityExecutionEnvelope(grant)
    gateway = AsyncMock(return_value={
        "summary": "A dancer",
        "duration_sec": 8,
        "title": "videomap",
    })
    plugin = MediaCorePlugin()
    with patch("app.chat.v2.host_gateway.HostGateway.media_video_analyze", gateway):
        artifact = await plugin.capability_handlers()["media.video_analyze"](
            envelope,
            {
                "build": {"id": "build-1"},
                "step": {
                    "step_id": "video-analysis",
                    "capability": "media.video_analyze",
                    "output_artifact_id": "videomap-1",
                    "output_artifact_type": "videomap",
                    "language_contract": {
                        "ui_locale": "zh-CN",
                        "content_language": "zh-CN",
                        "spoken_language": "zh-CN",
                        "subtitle_language": "zh-CN",
                        "provider_prompt_language": "auto",
                    },
                    "parameters": {"video_url": "https://cdn.example/v.mp4"},
                },
                "completed_artifacts": {},
            },
        )
    gateway.assert_awaited_once()
    forwarded = gateway.await_args.args[-1]
    assert forwarded["language_contract"]["content_language"] == "zh-CN"
    assert forwarded["language_contract"]["ui_locale"] == "zh-CN"
    assert artifact.type == "videomap"
    assert artifact.metadata["summary"] == "A dancer"
