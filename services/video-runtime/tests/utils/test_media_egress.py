"""media_egress.resolve_outbound_media_url 各分支单测（不触真网络）。

覆盖：
  - 空 / data: / 非本地 URL → 原样透传
  - 对象存储（_storage_is_local=False）→ 透传
  - 本地 + auto/provider_upload → 上传换公网 URL
  - 本地 + provider_upload 上传失败 → 兜底返回原 URL（不阻断）
  - 本地 + public_base → 前缀改写
  - 本地 + base64（accepts_base64）→ data URI
  - _upload_to_wavespeed 无 API key → None
  - 纯函数 _rewrite_public_base / _guess_mime / _egress_mode
"""
import base64
import os
import tempfile

import pytest

from app.utils import media_egress as me


# ----------------------- 纯函数 -----------------------

def test_guess_mime():
    assert me._guess_mime("/x/a.webp") == "image/webp"
    assert me._guess_mime("/x/a.MP4") == "video/mp4"
    assert me._guess_mime("/x/a.mp3") == "audio/mpeg"
    assert me._guess_mime("/x/a.unknown") == "application/octet-stream"


def test_egress_mode_default(monkeypatch):
    monkeypatch.delenv("MEDIA_EGRESS_MODE", raising=False)
    assert me._egress_mode() == "auto"
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "  Provider_Upload ")
    assert me._egress_mode() == "provider_upload"


def test_rewrite_public_base(monkeypatch):
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", "https://pub.example.com/")
    url = "http://localhost:8000/files/kf/shot-01.webp"
    assert me._rewrite_public_base(url) == "https://pub.example.com/files/kf/shot-01.webp"


def test_rewrite_public_base_missing_env_returns_original(monkeypatch):
    monkeypatch.delenv("MEDIA_PUBLIC_BASE_URL", raising=False)
    url = "http://localhost:8000/files/kf/shot-01.webp"
    assert me._rewrite_public_base(url) == url


def test_local_path_for_finds_shared_disk_file(monkeypatch, tmp_path):
    from app.utils.s3_utils import s3_utils

    root = tmp_path / "media"
    (root / "audios").mkdir(parents=True)
    target = root / "audios" / "cut.mp3"
    target.write_bytes(b"audio")
    monkeypatch.setattr(s3_utils, "_local_dir", str(root), raising=False)
    assert me._local_path_for("http://localhost:8001/files/audios/cut.mp3") == str(target.resolve())


def test_local_path_for_missing_file_is_none(monkeypatch, tmp_path):
    from app.utils.s3_utils import s3_utils

    monkeypatch.setattr(s3_utils, "_local_dir", str(tmp_path), raising=False)
    assert me._local_path_for("http://localhost:8001/files/audios/missing.mp3") is None


def test_reachable_media_url_prefers_public_original():
    stored = "http://localhost:8000/files/audios/suno.mp3"
    original = "https://files.aimusicapi.ai/stems/clip.mp3"
    assert me.reachable_media_url(stored, original) == original
    assert me.reachable_media_url("https://cdn.example.com/a.mp3", original) == "https://cdn.example.com/a.mp3"
    assert me.reachable_media_url("", original) == original


# ----------------------- passthrough -----------------------

@pytest.mark.parametrize("val", ["", None, "   ", "data:image/png;base64,AAAA"])
async def test_empty_or_data_uri_passthrough(val):
    assert await me.resolve_outbound_media_url(val) == val


async def test_non_local_url_passthrough(monkeypatch):
    """_local_path_for 返回 None（对象存储/外部公网）→ 原样透传。"""
    monkeypatch.setattr(me, "_local_path_for", lambda u: None)
    url = "https://cdn.example.com/files/a.webp"
    assert await me.resolve_outbound_media_url(url) == url


async def test_loopback_files_url_without_disk_file_passthrough(monkeypatch):
    """磁盘上没有这份文件时不 HTTP 再拉，原样透传。本地测靠 compose 共享盘命中 _local_path_for。"""
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "auto")
    monkeypatch.setattr(me, "_local_path_for", lambda u: None)

    async def boom(_path):
        raise AssertionError("must not upload when the file is not on this disk")

    monkeypatch.setattr(me, "_upload_to_wavespeed", boom)
    url = "http://127.0.0.1:8001/files/cut.mp3"
    assert await me.resolve_outbound_media_url(url) == url


# ----------------------- provider_upload -----------------------

async def test_local_provider_upload(monkeypatch):
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "auto")
    monkeypatch.setattr(me, "_local_path_for", lambda u: "/fake/kf.webp")

    async def fake_upload(path):
        assert path == "/fake/kf.webp"
        return "https://api.wavespeed.ai/media/xyz.webp"

    monkeypatch.setattr(me, "_upload_to_wavespeed", fake_upload)
    out = await me.resolve_outbound_media_url("http://localhost:8000/files/kf.webp")
    assert out == "https://api.wavespeed.ai/media/xyz.webp"


async def test_local_provider_upload_failure_falls_back_to_original(monkeypatch):
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "provider_upload")
    monkeypatch.setattr(me, "_local_path_for", lambda u: "/fake/kf.webp")

    async def fake_upload(path):
        return None  # 上传失败

    monkeypatch.setattr(me, "_upload_to_wavespeed", fake_upload)
    url = "http://localhost:8000/files/kf.webp"
    assert await me.resolve_outbound_media_url(url) == url


async def test_resolver_never_raises(monkeypatch):
    """内部异常也必须吞掉、返回原 URL，绝不阻断主流程。"""
    def boom(u):
        raise RuntimeError("boom")

    monkeypatch.setattr(me, "_local_path_for", boom)
    url = "http://localhost:8000/files/kf.webp"
    assert await me.resolve_outbound_media_url(url) == url


# ----------------------- public_base -----------------------

async def test_local_public_base(monkeypatch):
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "public_base")
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", "https://tunnel.example.com")
    monkeypatch.setattr(me, "_local_path_for", lambda u: "/fake/kf.webp")
    out = await me.resolve_outbound_media_url("http://localhost:8000/files/kf.webp")
    assert out == "https://tunnel.example.com/files/kf.webp"


# ----------------------- base64 -----------------------

async def test_local_base64_when_supported(monkeypatch):
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "base64")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNGDATA")
        path = f.name
    try:
        monkeypatch.setattr(me, "_local_path_for", lambda u: path)
        out = await me.resolve_outbound_media_url("http://localhost:8000/files/x.png", accepts_base64=True)
        assert out.startswith("data:image/png;base64,")
        assert base64.b64decode(out.split(",", 1)[1]) == b"\x89PNGDATA"
    finally:
        os.unlink(path)


async def test_base64_mode_but_not_supported_falls_back_to_upload(monkeypatch):
    """base64 模式但该入参不支持 base64 → 退回 provider_upload。"""
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "base64")
    monkeypatch.setattr(me, "_local_path_for", lambda u: "/fake/kf.webp")

    async def fake_upload(path):
        return "https://api.wavespeed.ai/media/xyz.webp"

    monkeypatch.setattr(me, "_upload_to_wavespeed", fake_upload)
    out = await me.resolve_outbound_media_url("http://localhost:8000/files/kf.webp", accepts_base64=False)
    assert out == "https://api.wavespeed.ai/media/xyz.webp"


# ----------------------- upload helper -----------------------

async def test_upload_without_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
        f.write(b"x")
        path = f.name
    try:
        assert await me._upload_to_wavespeed(path) is None
    finally:
        os.unlink(path)


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, status, body):
        self._status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **k):
        return _FakeResp(self._status, self._body)


def _patch_session(monkeypatch, status, body):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    monkeypatch.setattr(me.aiohttp, "ClientSession", lambda *a, **k: _FakeSession(status, body))


def _tmpfile():
    f = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
    f.write(b"imgbytes")
    f.close()
    return f.name


async def test_upload_parses_download_url_on_200(monkeypatch):
    """实测响应结构 {code,message,data:{type,download_url,filename}} 取 data.download_url。"""
    _patch_session(
        monkeypatch, 200,
        '{"code":200,"message":"success","data":{"type":"image",'
        '"download_url":"https://cdn.example.com/media/abc.webp","filename":"abc.webp"}}',
    )
    path = _tmpfile()
    try:
        assert await me._upload_to_wavespeed(path) == "https://cdn.example.com/media/abc.webp"
    finally:
        os.unlink(path)


async def test_upload_parses_url_fallback_on_200(monkeypatch):
    """文档结构 data.url 作为兜底。"""
    _patch_session(monkeypatch, 200, '{"code":200,"message":"success","data":{"url":"https://api.wavespeed.ai/media/abc.webp"}}')
    path = _tmpfile()
    try:
        assert await me._upload_to_wavespeed(path) == "https://api.wavespeed.ai/media/abc.webp"
    finally:
        os.unlink(path)


async def test_upload_non_200_returns_none(monkeypatch):
    _patch_session(monkeypatch, 500, "internal error")
    path = _tmpfile()
    try:
        assert await me._upload_to_wavespeed(path) is None
    finally:
        os.unlink(path)


async def test_upload_missing_url_returns_none(monkeypatch):
    _patch_session(monkeypatch, 200, '{"code":200,"data":{}}')
    path = _tmpfile()
    try:
        assert await me._upload_to_wavespeed(path) is None
    finally:
        os.unlink(path)


async def test_resolve_end_to_end_provider_upload(monkeypatch):
    """端到端（除网络外）：local + auto → _local_path_for 命中 → 走上传解析 → 公网 URL。"""
    path = _tmpfile()
    monkeypatch.setenv("MEDIA_EGRESS_MODE", "auto")
    monkeypatch.setattr(me, "_local_path_for", lambda u: path)
    _patch_session(monkeypatch, 200, '{"code":200,"data":{"type":"image","download_url":"https://cdn.example.com/media/e2e.webp"}}')
    try:
        out = await me.resolve_outbound_media_url("http://localhost:8000/files/kf.webp")
        assert out == "https://cdn.example.com/media/e2e.webp"
    finally:
        os.unlink(path)
