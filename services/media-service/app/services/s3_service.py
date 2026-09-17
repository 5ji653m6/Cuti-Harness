import asyncio
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class S3Service:
    """Media-storage abstraction. Defaults to S3 (cloud); when storage_backend=local, writes to local disk,
    sharing the same LOCAL_STORAGE_DIR as the agent, producing URLs like {public_base_url}/files/{key}.
    In local mode it does not initialize boto3 and needs no AWS credentials.
    """

    def __init__(self):
        settings = get_settings()
        self._is_local = (settings.storage_backend or "s3").lower() == "local"
        self._bucket = settings.s3_bucket
        self._cdn_prefix = settings.s3_cdn_prefix.rstrip("/") if settings.s3_cdn_prefix else ""

        if self._is_local:
            self._client = None
            self._local_dir = os.path.abspath(settings.local_storage_dir or "./data/uploads")
            os.makedirs(self._local_dir, exist_ok=True)
            base = (settings.public_base_url or "http://localhost:8000").rstrip("/")
            # consistent with the agent main.py's /files static mount
            self._public_prefix = f"{base}/files"
            self._public_netloc = urlparse(base).netloc
            logger.info(
                "🗂️ 媒体存储后端=local，落地目录=%s，URL 前缀=%s",
                self._local_dir, self._public_prefix,
            )
        else:
            import boto3
            from botocore.config import Config as BotoConfig

            self._local_dir = ""
            self._public_prefix = ""
            self._public_netloc = ""
            self._client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None,
                region_name=settings.aws_region,
                endpoint_url=settings.s3_endpoint_url or None,
                config=BotoConfig(
                    max_pool_connections=20,
                    s3={"addressing_style": "path"} if settings.s3_endpoint_url else {},
                ),
            )

    def _is_our_url(self, url: str) -> bool:
        """Check if URL belongs to our storage (S3/CDN, or local /files base)."""
        if self._is_local:
            return bool(self._public_netloc) and urlparse(url).netloc == self._public_netloc
        if self._cdn_prefix and url.startswith(self._cdn_prefix):
            return True
        if url.startswith("s3://"):
            return True
        if f"{self._bucket}.s3" in url:
            return True
        return False

    def is_our_url(self, url: str) -> bool:
        """Public ownership check used by idempotent media pipelines."""
        return self._is_our_url(url)

    def _local_url_to_key(self, url: str) -> Optional[str]:
        """{public_base_url}/files/<key> → <key>。"""
        key = urlparse(url).path.lstrip("/")
        if key.startswith("files/"):
            key = key[len("files/"):]
        return key or None

    async def download(self, url: str, local_path: str) -> bool:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        if self._is_local:
            if self._is_our_url(url):
                return await asyncio.to_thread(self._copy_from_local, url, local_path)
            # external links (e.g. Suno/CDN); local mode also fetches them over HTTP
            return await self._download_http(url, local_path)
        if self._is_our_url(url):
            return await self._download_s3(url, local_path)
        return await self._download_http(url, local_path)

    def _copy_from_local(self, url: str, local_path: str) -> bool:
        key = self._local_url_to_key(url)
        if not key:
            logger.error("Cannot parse local storage key from URL: %s", url)
            return False
        src = os.path.join(self._local_dir, key)
        if not os.path.exists(src):
            logger.error("Local storage file not found: %s", src)
            return False
        try:
            shutil.copyfile(src, local_path)
            return True
        except Exception as e:
            logger.error("Local copy failed %s: %s", src, e)
            return False

    async def _download_s3(self, url: str, local_path: str) -> bool:
        key = self._url_to_key(url)
        if not key:
            logger.error("Cannot parse S3 key from URL: %s", url)
            return False
        try:
            await asyncio.to_thread(self._client.download_file, self._bucket, key, local_path)
            return True
        except Exception as e:
            logger.error("S3 download failed %s: %s", key, e)
            return False

    async def _download_http(self, url: str, local_path: str) -> bool:
        """Download external URL via HTTP."""
        try:
            # httpx can stall for minutes on WaveSpeed's CloudFront downloads in
            # WSL, while the same URL streams immediately through requests.
            # Keep the event loop non-blocking and avoid buffering whole videos.
            def _stream_download() -> None:
                import requests

                with requests.get(
                    url, stream=True, timeout=(10, 120), allow_redirects=True,
                ) as resp:
                    resp.raise_for_status()
                    with open(local_path, "wb") as destination:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                destination.write(chunk)

            await asyncio.to_thread(_stream_download)
            logger.info("HTTP download OK: %s (%d bytes)", url[:80], os.path.getsize(local_path))
            return True
        except Exception as e:
            logger.error("HTTP download failed %s: %s", url[:80], e)
            return False

    def _save_local(self, key: str, write_fn) -> str:
        dest = os.path.join(self._local_dir, key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        write_fn(dest)
        url = f"{self._public_prefix}/{key}"
        logger.info("Saved media output to local storage: %s → %s", dest, url)
        return url

    async def upload(self, local_path: str, key: str, content_type: str = "application/octet-stream") -> str:
        if self._is_local:
            return await asyncio.to_thread(
                self._save_local, key, lambda dest: shutil.copyfile(local_path, dest)
            )
        try:
            await asyncio.to_thread(
                self._client.upload_file,
                local_path,
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type, "CacheControl": _IMMUTABLE_CACHE_CONTROL},
            )
            if self._cdn_prefix:
                return f"{self._cdn_prefix}/{key}"
            return f"https://{self._bucket}.s3.amazonaws.com/{key}"
        except Exception as e:
            logger.error("S3 upload failed %s: %s", key, e)
            raise

    async def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        if self._is_local:
            def _write(dest: str):
                with open(dest, "wb") as f:
                    f.write(data)
            return await asyncio.to_thread(self._save_local, key, _write)

        from io import BytesIO

        try:
            await asyncio.to_thread(
                self._client.upload_fileobj,
                BytesIO(data),
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type, "CacheControl": _IMMUTABLE_CACHE_CONTROL},
            )
            if self._cdn_prefix:
                return f"{self._cdn_prefix}/{key}"
            return f"https://{self._bucket}.s3.amazonaws.com/{key}"
        except Exception as e:
            logger.error("S3 upload_bytes failed %s: %s", key, e)
            raise

    async def ensure_local(self, url: str, workspace_dir: Path) -> Optional[str]:
        """Download URL to workspace inputs dir, deduplicated by URL hash."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = os.path.splitext(url.split("?")[0])[-1] or ".bin"
        local_path = workspace_dir / "inputs" / f"{url_hash}{ext}"
        if local_path.exists():
            return str(local_path)
        ok = await self.download(url, str(local_path))
        return str(local_path) if ok else None

    def _url_to_key(self, url: str) -> Optional[str]:
        if self._cdn_prefix and url.startswith(self._cdn_prefix):
            return url[len(self._cdn_prefix) :].lstrip("/")
        if url.startswith("s3://"):
            parts = url.replace("s3://", "").split("/", 1)
            return parts[1] if len(parts) > 1 else None
        if f"{self._bucket}.s3" in url:
            idx = url.find(self._bucket)
            after = url[idx + len(self._bucket) :]
            after = after.lstrip(".s3.amazonaws.com").lstrip("/")
            return after
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                path = url[len(prefix) :].split("/", 1)
                if len(path) > 1:
                    return path[1]
        return None


_s3_service: Optional[S3Service] = None


def get_s3_service() -> S3Service:
    global _s3_service
    if _s3_service is None:
        _s3_service = S3Service()
    return _s3_service
