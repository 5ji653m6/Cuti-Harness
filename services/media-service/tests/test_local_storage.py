"""Media Service 本地存储后端（STORAGE_BACKEND=local）单元测试。

覆盖：
- upload 落地本地磁盘并返回 {PUBLIC_BASE_URL}/files/{key}
- upload_bytes 同上
- _is_our_url / download 能识别本地 URL 并从共享目录回读（无需 AWS）
- 外链走 HTTP（这里仅校验 _is_our_url 判定，不实际联网）
"""
import asyncio
from pathlib import Path

import pytest

import app.config as config_mod
from app.services.s3_service import S3Service


def _make_local_service(tmp_path: Path, monkeypatch) -> S3Service:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    config_mod.get_settings.cache_clear()
    return S3Service()


def test_local_upload_returns_files_url(tmp_path, monkeypatch):
    svc = _make_local_service(tmp_path, monkeypatch)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"hello-video")

    url = asyncio.run(svc.upload(str(src), "media/run1/out.mp4", "video/mp4"))

    assert url == "http://localhost:8000/files/media/run1/out.mp4"
    assert (tmp_path / "media/run1/out.mp4").read_bytes() == b"hello-video"


def test_local_upload_bytes(tmp_path, monkeypatch):
    svc = _make_local_service(tmp_path, monkeypatch)
    url = asyncio.run(svc.upload_bytes(b"abc", "videos/x.mp4", "video/mp4"))
    assert url == "http://localhost:8000/files/videos/x.mp4"
    assert (tmp_path / "videos/x.mp4").read_bytes() == b"abc"


def test_local_is_our_url(tmp_path, monkeypatch):
    svc = _make_local_service(tmp_path, monkeypatch)
    assert svc._is_our_url("http://localhost:8000/files/audios/a.mp3") is True
    assert svc._is_our_url("https://musicapi-cdn.b-cdn.net/x.mp3") is False


def test_local_download_roundtrip(tmp_path, monkeypatch):
    """upload → download 应能在共享目录内回读（模拟 agent 产物被 media 消费）。"""
    svc = _make_local_service(tmp_path, monkeypatch)
    (tmp_path / "audios").mkdir(parents=True, exist_ok=True)
    (tmp_path / "audios/a.mp3").write_bytes(b"song")

    out = tmp_path / "dl" / "a.mp3"
    ok = asyncio.run(svc.download("http://localhost:8000/files/audios/a.mp3", str(out)))

    assert ok is True
    assert out.read_bytes() == b"song"


def test_local_backend_no_boto3_client(tmp_path, monkeypatch):
    """local 模式下不应初始化 S3 客户端（自托管零 AWS 依赖）。"""
    svc = _make_local_service(tmp_path, monkeypatch)
    assert svc._client is None


def test_local_download_foreign_url_over_real_http(tmp_path, monkeypatch):
    """Open-source media-service: vendor URLs HTTP-get; no S3."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    payload = b"N" * 240

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            return

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        svc = _make_local_service(tmp_path, monkeypatch)
        url = f"http://127.0.0.1:{server.server_address[1]}/stems/clip.mp3"
        out = tmp_path / "dl" / "clip.mp3"
        ok = asyncio.run(svc.download(url, str(out)))
        assert ok is True
        assert out.read_bytes() == payload
    finally:
        server.shutdown()
        thread.join(timeout=2)
