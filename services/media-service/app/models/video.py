from pydantic import BaseModel, Field
from typing import Optional, List
from .common import RunIdMixin, MediaResult


class VideoInfoRequest(BaseModel):
    video_url: str


class VideoInfoResponse(BaseModel):
    duration: float
    width: int
    height: int
    fps: float
    nb_frames: Optional[int] = None
    codec: Optional[str] = None
    pix_fmt: Optional[str] = None
    has_audio: bool


class VideoTrimRequest(RunIdMixin):
    video_url: str
    target_duration: float
    mode: str = Field(
        default="pad_or_trim",
        description="trim_only | pad_or_trim | freeze_or_tail_slow（短：静帧copy/尾慢/整片慢）",
    )
    tolerance: float = Field(
        default=0.02,
        description="若 |probe_duration−target| < tolerance 则直接 copy 跳过重编码；设为 0 表示从不跳过",
    )


class VideoTrimResponse(MediaResult):
    duration: float


class VideoConcatRequest(RunIdMixin):
    video_urls: List[str]
    normalize: bool = Field(default=True)
    transition_duration: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Cross-fade duration in seconds between consecutive clips; 0 keeps hard cuts",
    )


class VideoConcatResponse(MediaResult):
    duration: float


class VideoSpeedRequest(RunIdMixin):
    video_url: str
    target_duration: float


class VideoSpeedResponse(MediaResult):
    duration: float


class VideoNormalizeRequest(RunIdMixin):
    video_url: str
    target_width: int
    target_height: int


class VideoNormalizeResponse(MediaResult):
    metadata: dict


class VideoWatermarkRequest(RunIdMixin):
    video_url: str


class VideoStripAudioRequest(RunIdMixin):
    video_url: str


class VideoMixAudioRequest(RunIdMixin):
    video_url: str
    audio_url: str
    audio_volume: float = Field(default=0.3)
    loop_audio: bool = Field(default=False, description="Loop audio to match video duration")


class VideoAddAudioRequest(RunIdMixin):
    video_url: str
    audio_segments: List[dict]


class VideoPlaceholderRequest(RunIdMixin):
    duration: float
    width: int = 1280
    height: int = 720
    fps: int = 30


class VideoExtractFrameRequest(RunIdMixin):
    video_url: str
    timestamp: Optional[float] = Field(default=None, ge=0, description="Seconds from video start")
    position: str = Field(
        default="timestamp",
        description="timestamp | last; last resolves the final decoded video frame",
    )
    format: str = Field(default="jpeg", description="jpeg | png")


class VideoExtractFrameResponse(MediaResult):
    timestamp: float
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = "jpeg"


class HyperframesRenderRequest(RunIdMixin):
    composition_html: str = Field(min_length=1, max_length=500_000)
    width: int = Field(default=1920, ge=320, le=4096)
    height: int = Field(default=1080, ge=320, le=4096)
    duration: float = Field(default=10, gt=0, le=300)
    fps: int = Field(default=30, ge=12, le=60)


class HyperframesRenderResponse(MediaResult):
    duration: float
    width: int
    height: int
    fps: float
    renderer: str = "hyperframes"
    render_metadata: dict = Field(default_factory=dict)
