"""Unified storage contract: local (no S3) vs dest/prod (S3).

Fetch is one API (``download_file``):
  - our URL / key → copy disk (local) or S3 (dest/prod)
  - any other http(s) → real HTTP GET

Ingest (``download_and_upload_audio_to_s3``) uses that fetch, then upload.
Callers (Gemini, temp files, convert_media_url) must go through the same API.

These tests start a real TCP HTTP server. They do not call AWS or Gemini.
"""
from __future__ import annotations

import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import settings


PAYLOAD = b"M" * 240


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):
        body = getattr(self.server, "payload", PAYLOAD)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def http_audio():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.payload = PAYLOAD
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    url = f"http://127.0.0.1:{port}/stems/clip.mp3"
    try:
        yield url
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://localhost:8001", raising=False)
    from app.utils.s3_utils import S3Utils

    return S3Utils()


def _s3_store(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3", raising=False)
    monkeypatch.setattr(settings, "CDN_DOMAIN", "https://cdn.example.test", raising=False)
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", "cuti-test", raising=False)
    from app.utils.s3_utils import S3Utils

    objects: dict[str, bytes] = {}
    s3_gets: list[str] = []

    class _FakeClient:
        def put_object(self, Bucket, Key, Body, **kwargs):
            objects[Key] = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body)

        def download_file(self, Bucket, Key, Filename):
            s3_gets.append(Key)
            if Key not in objects:
                raise FileNotFoundError(Key)
            parent = os.path.dirname(Filename)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(Filename, "wb") as handle:
                handle.write(objects[Key])

    store = S3Utils()
    store.s3_client = _FakeClient()
    return store, objects, s3_gets


@pytest.mark.asyncio
async def test_local_ingest_then_gemini_copies_disk_not_vendor(tmp_path, monkeypatch, http_audio):
    """Open-source: Suno HTTP → /files URL → analyze copies disk. No S3."""
    s3 = _local_store(tmp_path, monkeypatch)
    stored = await s3.download_and_upload_audio_to_s3(http_audio, generation_id="suno_clip")
    assert stored.startswith("http://localhost:8001/files/audios/")
    on_disk = os.path.join(str(tmp_path), stored.split("/files/", 1)[1])
    assert open(on_disk, "rb").read() == PAYLOAD

    dst = tmp_path / "gemini.mp3"
    assert await s3.download_file(stored, str(dst)) is True
    assert dst.read_bytes() == PAYLOAD


@pytest.mark.asyncio
async def test_local_fetch_foreign_url_over_real_http(tmp_path, monkeypatch, http_audio):
    """If a vendor URL slips through, local still HTTP-gets it for Gemini."""
    s3 = _local_store(tmp_path, monkeypatch)
    dst = tmp_path / "vendor.mp3"
    assert await s3.download_file(http_audio, str(dst)) is True
    assert dst.read_bytes() == PAYLOAD


@pytest.mark.asyncio
async def test_s3_ingest_then_fetch_uses_bucket_not_http(monkeypatch, http_audio, tmp_path):
    """dest/prod: ingest to S3, later Gemini reads the bucket for our CDN URL."""
    s3, objects, s3_gets = _s3_store(monkeypatch)
    stored = await s3.download_and_upload_audio_to_s3(http_audio, generation_id="prod_clip")
    assert stored.startswith("https://cdn.example.test/audios/")
    assert objects, "upload must put_object"
    dst = tmp_path / "from-s3.mp3"
    assert await s3.download_file(stored, str(dst)) is True
    assert dst.read_bytes() == PAYLOAD
    assert s3_gets, "our CDN URL must use S3 get, not HTTP"


@pytest.mark.asyncio
async def test_s3_fetch_foreign_url_over_real_http(monkeypatch, http_audio, tmp_path):
    """dest/prod leftover vendor URL (ingest failed) still HTTP-gets."""
    s3, objects, s3_gets = _s3_store(monkeypatch)
    dst = tmp_path / "vendor.mp3"
    assert await s3.download_file(http_audio, str(dst)) is True
    assert dst.read_bytes() == PAYLOAD
    assert s3_gets == []
    assert objects == {}


@pytest.mark.asyncio
async def test_convert_media_url_uses_same_fetch(tmp_path, monkeypatch, http_audio):
    s3 = _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.utils.s3_utils.s3_utils", s3)

    from app.utils.file_utils import MediaFormat, MediaType
    from app.utils.s3_utils import convert_media_url_to_s3

    stored = await s3.download_and_upload_audio_to_s3(http_audio, generation_id="shared")
    converted = await convert_media_url_to_s3(stored, MediaType.AUDIO, MediaFormat.LOCAL_PATH)
    assert converted and open(converted, "rb").read() == PAYLOAD


@pytest.mark.asyncio
async def test_gemini_download_step_gets_bytes_from_our_url(tmp_path, monkeypatch, http_audio):
    """Gemini's first step is download_file; local /files must yield bytes."""
    s3 = _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.tools.transcribe.gemini.s3_utils", s3)
    stored = await s3.download_and_upload_audio_to_s3(http_audio, generation_id="gemini")

    from app.tools.transcribe import gemini as gemini_mod

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, "gemini.mp3")
        ok = await gemini_mod.s3_utils.download_file(stored, temp_file_path)
        assert ok is True
        assert open(temp_file_path, "rb").read() == PAYLOAD


def test_video_analyze_uses_storage_prepare():
    import inspect
    from app.tools.video_analyze import gemini

    source = inspect.getsource(gemini.analyze_video_with_gemini)
    assert "from app.utils.file_utils import prepare_video_for_llm" in source
    assert "app.chat.utils.file_utils" not in source


@pytest.mark.asyncio
async def test_transcribe_download_limited_copies_local_files_url(tmp_path, monkeypatch):
    s3 = _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.utils.s3_utils.s3_utils", s3)
    stored = await s3.upload_file(PAYLOAD, "media/run/audio.mp3", "audio/mpeg")

    from app.services.subtitle_transcription_service import _download_limited

    dest = tmp_path / "whisper.mp3"
    written = await _download_limited(stored, dest, max_bytes=10_000)
    assert written == len(PAYLOAD)
    assert dest.read_bytes() == PAYLOAD


@pytest.mark.asyncio
async def test_transcribe_download_limited_enforces_size_cap(tmp_path, monkeypatch):
    s3 = _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.utils.s3_utils.s3_utils", s3)
    await s3.upload_file(PAYLOAD, "media/run/audio.mp3", "audio/mpeg")
    url = "http://localhost:8001/files/media/run/audio.mp3"

    from app.services.subtitle_transcription_service import _download_limited

    dest = tmp_path / "too-big.mp3"
    with pytest.raises(ValueError, match="transcription limit"):
        await _download_limited(url, dest, max_bytes=10)
    assert not dest.exists()


@pytest.mark.asyncio
async def test_nano_banana_and_keyframe_download_foreign_http(tmp_path, monkeypatch, http_audio):
    s3 = _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.utils.s3_utils.s3_utils", s3)
    monkeypatch.setattr("app.tools.image.nano_banana.s3_utils", s3)

    from app.tools.image import nano_banana
    from app.utils.s3_utils import s3_utils as shared

    dst = tmp_path / "nb.webp"
    assert await nano_banana.s3_utils.download_file(http_audio, str(dst)) is True
    dst2 = tmp_path / "kf.webp"
    assert await shared.download_file(http_audio, str(dst2)) is True
    assert dst.read_bytes() == dst2.read_bytes() == PAYLOAD
