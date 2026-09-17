"""
S3 upload (same logic used for ``process_uploaded_files``).

Contains only ``upload_image`` / ``upload_audio`` / ``upload_video`` needed for user-uploaded images/audio/video,
avoiding dependencies on the video_generation CRUD and Media Service pipeline.
"""
import asyncio
import io
import logging
import os
import uuid
from typing import Optional, Tuple

import boto3
from PIL import Image

from app.chat.config import settings
from app.chat.exceptions import BusinessException, BusinessExceptionCode

logger = logging.getLogger(__name__)


class S3Utils:
    """S3 utility class: handles file uploads to S3, returning CDN URLs."""

    def __init__(self):
        # Storage backend flags live in the main app config (chat config only carries AWS_REGION/
        # S3_BUCKET_NAME/CDN_DOMAIN). STORAGE_BACKEND=local (self-hosted) writes to the local
        # filesystem and needs no S3 client / AWS credentials.
        from app.config import settings as app_settings

        self._is_local = (getattr(app_settings, "STORAGE_BACKEND", "local") or "local").lower() == "local"
        self.bucket_name = settings.S3_BUCKET_NAME
        if self._is_local:
            self.s3_client = None
            self._local_dir = os.path.abspath(getattr(app_settings, "LOCAL_STORAGE_DIR", "./data/uploads"))
            os.makedirs(self._local_dir, exist_ok=True)
            base = (getattr(app_settings, "PUBLIC_BASE_URL", "") or "").strip() or "http://localhost:8000"
            # {PUBLIC_BASE_URL}/files matches the /files static mount in main.py
            self.cdn_domain = f"{base.rstrip('/')}/files"
            logger.info("Storage backend=local, dir=%s, url prefix=%s", self._local_dir, self.cdn_domain)
        else:
            self.s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
            self.cdn_domain = settings.CDN_DOMAIN.rstrip("/")

    _IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

    def _upload_file_sync(self, file_data: bytes, file_key: str, content_type: str = None) -> str:
        try:
            if self._is_local:
                dest = os.path.join(self._local_dir, file_key)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(file_data)
                url = f"{self.cdn_domain}/{file_key}"
                logger.info("Saved file to local storage: %s -> %s", dest, url)
                return url
            extra_args = {"CacheControl": self._IMMUTABLE_CACHE_CONTROL}
            if content_type:
                extra_args["ContentType"] = content_type
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=file_key,
                Body=file_data,
                **extra_args,
            )
            cdn_url = f"{self.cdn_domain}/{file_key}"
            logger.info("Uploaded file to S3: %s -> %s", file_key, cdn_url)
            return cdn_url
        except Exception as e:
            logger.error("Error uploading file to S3: %s", e)
            raise BusinessException(
                BusinessExceptionCode.BUSINESS_ERROR,
                f"文件上传失败: {str(e)}",
            )

    async def upload_file(self, file_data: bytes, file_key: str, content_type: str = None) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_file_sync(file_data, file_key, content_type),
        )

    def _upload_image_sync(
        self,
        image_data: bytes,
        generation_id: Optional[str] = None,
        content_type: str = "image/webp",
        resize_to: Optional[Tuple[int, int]] = None,
    ) -> str:
        try:
            image_bytes = image_data
            with Image.open(io.BytesIO(image_bytes)) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                if resize_to:
                    target_width, target_height = resize_to
                    if img.width != target_width or img.height != target_height:
                        logger.info(
                            "Resize image: %sx%s -> %sx%s",
                            img.width,
                            img.height,
                            target_width,
                            target_height,
                        )
                        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                img.save(output, "webp", quality=85)
                processed_image_bytes = output.getvalue()
            filename = f"{generation_id}.webp" if generation_id else f"{uuid.uuid4()}.webp"
            file_key = f"images/{filename}"
            return self._upload_file_sync(processed_image_bytes, file_key, content_type)
        except Exception as e:
            logger.error("Error processing and uploading image: %s", e)
            raise BusinessException(
                BusinessExceptionCode.BUSINESS_ERROR,
                f"图片处理或上传失败: {str(e)}",
            )

    async def upload_image(
        self,
        image_data: bytes,
        generation_id: Optional[str] = None,
        content_type: str = "image/webp",
        resize_to: Optional[Tuple[int, int]] = None,
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_image_sync(image_data, generation_id, content_type, resize_to),
        )

    def _upload_audio_sync(
        self,
        audio_data: bytes,
        filename: str = None,
        generation_id: Optional[str] = None,
        content_type: str = "audio/mpeg",
    ) -> str:
        if filename:
            _, ext = os.path.splitext(filename)
            ext = ext or ".mp3"
        else:
            ext = ".mp3"
        name = f"{generation_id}{ext}" if generation_id else f"{uuid.uuid4()}{ext}"
        file_key = f"audios/{name}"
        return self._upload_file_sync(audio_data, file_key, content_type)

    async def upload_audio(
        self,
        audio_data: bytes,
        filename: str = None,
        generation_id: Optional[str] = None,
        content_type: str = "audio/mpeg",
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_audio_sync(audio_data, filename, generation_id, content_type),
        )

    def _upload_video_sync(
        self,
        video_data: bytes,
        filename: str = None,
        generation_id: Optional[str] = None,
        content_type: str = "video/mp4",
    ) -> str:
        if filename:
            _, ext = os.path.splitext(filename)
            ext = ext or ".mp4"
        else:
            ext = ".mp4"
        name = f"{generation_id}{ext}" if generation_id else f"{uuid.uuid4()}{ext}"
        file_key = f"videos/{name}"
        return self._upload_file_sync(video_data, file_key, content_type)

    async def upload_video(
        self,
        video_data: bytes,
        filename: str = None,
        generation_id: Optional[str] = None,
        content_type: str = "video/mp4",
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_video_sync(video_data, filename, generation_id, content_type),
        )


s3_utils = S3Utils()
