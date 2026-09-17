from pydantic import BaseModel, Field
from typing import Optional, List
from .common import RunIdMixin, MediaResult


class SegmentVideo(BaseModel):
    url: str
    target_duration: float


class SegmentProcessRequest(RunIdMixin):
    videos: List[SegmentVideo]
    total_target_duration: float
    normalize: bool = Field(default=True)


class SegmentProcessResponse(MediaResult):
    duration: float


class NarrationSegment(BaseModel):
    url: str
    start_time: float
    duration: float
    volume: float = 1.0


class AudioEffectSegment(BaseModel):
    url: str
    start_time: float
    duration: float
    volume: float = 0.8


class BackgroundMusic(BaseModel):
    url: str
    mode: str = Field(default="loop", description="loop | truncate | once")
    volume: float = 0.3
    crossfade_ms: int = 2000


class VideoAssemblyRequest(RunIdMixin):
    segments: List[dict]
    narrations: List[NarrationSegment] = Field(default_factory=list)
    audio_effects: List[AudioEffectSegment] = Field(default_factory=list)
    background_music: Optional[BackgroundMusic] = None
    watermark: bool = True


class VideoAssemblyResponse(MediaResult):
    duration: float


class EnsureOnS3Request(RunIdMixin):
    external_url: str
    target_width: Optional[int] = None
    target_height: Optional[int] = None
    target_fps: Optional[int] = None
    target_duration: Optional[float] = None
    strip_audio: bool = False
    watermark: bool = False
    force_watermark: bool = False


class WorkspaceCleanupRequest(BaseModel):
    run_id: str


class WorkspaceCleanupResponse(BaseModel):
    cleaned_files: int
    freed_mb: float
