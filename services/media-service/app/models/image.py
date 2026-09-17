from pydantic import BaseModel, Field
from typing import Optional
from .common import RunIdMixin, MediaResult


class ImageInfoRequest(BaseModel):
    image_url: str


class ImageInfoResponse(BaseModel):
    width: int
    height: int


class ImageResizeRequest(RunIdMixin):
    image_url: str
    target_width: int
    target_height: int
    format: str = Field(default="webp")
    quality: int = Field(default=85)


class ImageResizeResponse(MediaResult):
    width: int
    height: int
