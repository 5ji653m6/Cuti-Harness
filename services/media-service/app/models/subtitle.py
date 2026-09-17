from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .common import MediaResult, RunIdMixin


class SubtitleCue(BaseModel):
    start: float = Field(ge=0, description="Cue start in seconds")
    end: float = Field(gt=0, description="Cue end in seconds")
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("subtitle cue end must be greater than start")
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("subtitle cue text cannot be blank")
        return self


class SubtitleComposeRequest(RunIdMixin):
    cues: list[SubtitleCue] = Field(min_length=1, max_length=10000)
    format: Literal["srt", "vtt", "ass"] = "srt"
    max_lines: int = Field(default=2, ge=1, le=3)
    max_chars_per_line: int = Field(default=18, ge=4, le=100)
    max_cps: float = Field(default=15.0, gt=0, le=100)


class SubtitleComposeResponse(MediaResult):
    format: str
    cue_count: int
    validation: dict


class SubtitleBurnRequest(RunIdMixin):
    video_url: str
    subtitle_url: str
    style_preset: Literal["short-video-bold", "clean", "minimal"] = "clean"
    position: Literal["bottom-safe", "bottom", "center", "top"] = "bottom-safe"
    font_name: Optional[str] = Field(default=None, max_length=80)


class SubtitleBurnResponse(MediaResult):
    duration: float
    source_video_url: str
    subtitle_url: str
    style: dict


class OverlayLayer(BaseModel):
    type: Literal["title", "kinetic"] = "title"
    text: str = Field(min_length=1, max_length=200)
    start: float = Field(default=0, ge=0)
    end: float = Field(default=3.0, gt=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("overlay layer end must be greater than start")
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("overlay layer text cannot be blank")
        return self


HYPERFRAMES_CAPTION_STYLES = Literal[
    "caption-highlight",
    "caption-pill-karaoke",
    "caption-editorial-emphasis",
    "caption-glitch-rgb",
    "caption-kinetic-slam",
    "caption-neon-glow",
    "caption-neon-accent",
    "caption-clip-wipe",
    "caption-gradient-fill",
    "caption-matrix-decode",
    "caption-emoji-pop",
    "caption-parallax-layers",
    "caption-particle-burst",
    "caption-texture",
    "caption-weight-shift",
]


class HyperframesCaptionRequest(RunIdMixin):
    video_url: str
    words: list[dict] = Field(default_factory=list)
    cues: list[dict] = Field(default_factory=list)
    style: Optional[HYPERFRAMES_CAPTION_STYLES] = None
    accent_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    position: Optional[Literal["bottom-safe", "lower-middle", "center"]] = None
    playbook: Optional[str] = Field(default=None, max_length=80)
    layers: list[OverlayLayer] = Field(default_factory=list, max_length=12)
    caption_html: Optional[str] = Field(default=None, max_length=500_000)
    composition_html: Optional[str] = Field(default=None, max_length=500_000)

class HyperframesCaptionResponse(MediaResult):
    duration: float
    source_video_url: str
    style: dict
