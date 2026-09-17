from pydantic import BaseModel, Field
from typing import Optional
from .common import RunIdMixin, MediaResult


class AudioInfoRequest(BaseModel):
    audio_url: str


class AudioInfoResponse(BaseModel):
    duration: float


class AudioTrimRequest(RunIdMixin):
    audio_url: str
    start: float
    duration: float


class AudioTrimWithFadeRequest(RunIdMixin):
    """Trim + fade in/out (consistent with the smart-clip confirm trim). Fade time is within the trimmed segment (0..duration)."""
    audio_url: str
    start: float
    duration: float
    fade_in_sec: float = Field(default=0.0, ge=0.0, le=10.0)
    fade_out_sec: float = Field(default=0.0, ge=0.0, le=10.0)


class AudioExtractRequest(RunIdMixin):
    video_url: str
    format: str = Field(default="mp3")
    quality: str = Field(default="192k")


class AudioConvertRequest(RunIdMixin):
    audio_url: str
    target_format: str = Field(default="wav")


class AudioPeaksRequest(RunIdMixin):
    """Normalized peak array needed by the frontend waveform (lightweight, ~a few KB)."""
    audio_url: str
    sample_count: int = Field(default=512, ge=16, le=4096)


class AudioPeaksResponse(BaseModel):
    sample_count: int
    duration: float
    values: list[float]
