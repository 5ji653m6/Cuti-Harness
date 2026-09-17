"""External-provider media egress resolution: replace locally stored URLs with a public form the provider can fetch.

One codebase adapts to multiple deployments, distinguished by STORAGE_BACKEND + MEDIA_EGRESS_MODE (no code changes):

  - STORAGE_BACKEND=s3 (AWS / public MinIO / R2 ...)
        the media URL is already a public CDN -> pass through directly, do nothing.

  - STORAGE_BACKEND=local (self-hosted / compose shared disk, files at PUBLIC_BASE_URL/files/...)
        remote providers cannot fetch localhost. When the file is found on disk, handle per MEDIA_EGRESS_MODE:
          auto / provider_upload (default): upload to WaveSpeed /media/upload/binary and get back a public URL;
          base64: inline as a data URI only for calls that "declare base64 input support" (most providers do not support it, hence not the default);
          public_base: rewrite the /files/<key> prefix to MEDIA_PUBLIC_BASE_URL (for those exposing the service via tunnel/reverse proxy).
        Not found on disk -> pass through as-is, do not re-fetch over HTTP. Local testing uses the compose shared disk, with runtime and
        media-service reading the same LOCAL_STORAGE_DIR.

Non-local URL / already data: / file not found / processing failure -> always return as-is, never blocking the main flow (let the provider itself error).
"""
import asyncio
import base64
import logging
import os
import pathlib
from typing import Optional
from urllib.parse import unquote, urlparse

import aiohttp

logger = logging.getLogger(__name__)

_WAVESPEED_UPLOAD_URL = "https://api.wavespeed.ai/api/v3/media/upload/binary"

_MIME_BY_EXT = {
    ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".tiff": "image/tiff",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".flac": "audio/flac", ".ogg": "audio/ogg",
}


def _egress_mode() -> str:
    return (os.getenv("MEDIA_EGRESS_MODE", "auto") or "auto").strip().lower()


def _guess_mime(path: str) -> str:
    return _MIME_BY_EXT.get(pathlib.Path(path).suffix.lower(), "application/octet-stream")


def _local_path_for(url: str) -> Optional[str]:
    """When it is local storage and one of our own URLs, return the absolute disk path; otherwise None (meaning no/impossible egress handling)."""
    from app.utils.s3_utils import s3_utils, is_our_cdn_url, _storage_is_local

    if not _storage_is_local() and not (
        (urlparse(url.strip()).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
        and urlparse(url.strip()).path.startswith("/files/")
    ):
        return None  # object storage: the URL is already public, pass through
    parsed = urlparse(url.strip())
    local_host = (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
    shared_media_url = local_host and parsed.path.startswith("/files/")
    if not is_our_cdn_url(url) and not shared_media_url:
        return None  # already an external public URL
    file_key = (unquote(parsed.path[len("/files/"):]).lstrip("/")
                if shared_media_url else s3_utils.cdn_url_to_s3_key(url))
    if not file_key:
        return None
    repository_store = pathlib.Path(__file__).resolve().parents[4] / "data" / "uploads"
    configured_store = pathlib.Path(getattr(s3_utils, "_local_dir", repository_store))
    roots = (configured_store.resolve(), repository_store.resolve())
    for candidate in (configured_store / file_key, repository_store / file_key):
        resolved = candidate.resolve()
        if any(root == resolved or root in resolved.parents for root in roots) and resolved.is_file():
            return str(resolved)
    return None


def _is_loopback_files_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} and parsed.path.startswith("/files/")


def reachable_media_url(stored: str | None, original: str | None = None) -> str:
    """Prefer a non-loopback URL when a public original exists.

    Do not use this for stored artifact URIs. Internal analyze/Gemini must keep
    our storage URL (local ``/files`` or dest CDN) so fetch can copy from disk/S3.
    External vendors go through ``resolve_outbound_media_url``.
    """
    stored_s = (stored or "").strip()
    original_s = (original or "").strip()
    if stored_s and _is_loopback_files_url(stored_s) and original_s and not _is_loopback_files_url(original_s):
        return original_s
    return stored_s or original_s


async def resolve_outbound_media_url(url: str, *, accepts_base64: bool = False) -> str:
    """Resolve a single media URL into a form remote providers can fetch. See the module docstring."""
    if not url or not isinstance(url, str):
        return url
    u = url.strip()
    if not u or u.startswith("data:"):
        return url

    try:
        local_path = _local_path_for(u)
        mode = _egress_mode()
        if not local_path:
            return url  # public / non-local / file not on this disk -> pass through

        if mode == "public_base":
            return _rewrite_public_base(u)
        if mode == "base64" and accepts_base64:
            return await _to_data_uri(local_path)
        # auto / provider_upload (default)
        uploaded = await _upload_to_wavespeed(local_path)
        return uploaded or url
    except Exception as e:
        logger.warning("media egress 解析失败 url=%s err=%s", u[:120], e)
        return url


def _rewrite_public_base(url: str) -> str:
    base = (os.getenv("MEDIA_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    idx = url.find("/files/")
    if not base or idx < 0:
        logger.warning("media egress public_base：未配置 MEDIA_PUBLIC_BASE_URL 或 URL 无 /files/ 前缀")
        return url
    return base + url[idx:]


async def _to_data_uri(local_path: str) -> str:
    raw = await asyncio.to_thread(pathlib.Path(local_path).read_bytes)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{_guess_mime(local_path)};base64,{b64}"


async def _upload_to_wavespeed(local_path: str) -> Optional[str]:
    """Upload a local disk file to WaveSpeed; returns the public URL on success, None on failure."""
    raw = await asyncio.to_thread(pathlib.Path(local_path).read_bytes)
    filename = os.path.basename(local_path)
    api_key = os.getenv("WAVESPEED_API_KEY")
    if not api_key:
        logger.warning("media egress provider_upload：未配置 WAVESPEED_API_KEY")
        return None
    form = aiohttp.FormData()
    form.add_field("file", raw, filename=filename, content_type=_guess_mime(filename))
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            _WAVESPEED_UPLOAD_URL, headers={"Authorization": f"Bearer {api_key}"}, data=form
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.warning("media egress WaveSpeed 上传失败 %s: %s", resp.status, body[:200])
                return None
            import json as _json

            data = (_json.loads(body).get("data") or {})
            # in practice it returns data.download_url (the docs say data.url; handle both)
            public_url = (data.get("download_url") or data.get("url")) if isinstance(data, dict) else None
            if not public_url:
                logger.warning("media egress WaveSpeed 上传返回无 url: %s", body[:200])
                return None
            logger.info("media egress: 已上传 %s → %s", filename, public_url)
            return public_url
