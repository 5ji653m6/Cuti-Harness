"""Live media DTOs used by uploads, transcription, and smart-clip."""
from typing import List, Optional

from pydantic import BaseModel, Field

from .user_options import UserOption

__all__ = [
    "UserOption",
    "ImageUserInput",
    "AudioFileUserInput",
    "VideoFileUserInput",
    "AudioSegment",
    "AudioWord",
    "AudioTranscription",
]


class ImageUserInput(BaseModel):
    url: str = Field(description="图片URL")
    filename: Optional[str] = Field(default=None, description="原始文件名")
    is_new: bool = Field(default=True, description="是否为本轮新上传的资源")


class AudioFileUserInput(BaseModel):
    url: str = Field(description="音频文件URL")
    filename: Optional[str] = Field(default=None, description="原始文件名")
    is_new: bool = Field(default=True, description="是否为本轮新上传的资源")
    generated_lyrics: Optional[str] = Field(default=None, description="生成音乐时的歌词")
    suno_clip_id: Optional[str] = Field(
        default=None,
        description="Suno generated 时的 clip_id；user upload 时为空",
    )
    duration: Optional[float] = Field(default=None, description="音频时长（秒）")


class VideoFileUserInput(BaseModel):
    url: str = Field(description="视频文件URL")
    filename: Optional[str] = Field(default=None, description="原始文件名")
    is_new: bool = Field(default=True, description="是否为本轮新上传的资源")


class AudioSegment(BaseModel):
    uuid: str = Field(default="", description="片段UUID")
    id: int = Field(description="片段ID（序号）")
    start: float = Field(description="开始时间（秒）")
    end: float = Field(description="结束时间（秒）")
    text: str = Field(description="转录文本或音乐段落描述")
    duration: float = Field(description="片段时长（秒）")
    emotion: Optional[str] = Field(default=None, description="情感/调性")
    tempo: Optional[str] = Field(default=None, description="速度/动态（仅纯音乐）")
    vocal_presence: Optional[bool] = Field(default=None, description="是否有人声")
    vocal_gender: Optional[str] = Field(default=None, description="人声性别：'f' 或 'm'")


class AudioWord(BaseModel):
    id: int = Field(description="词汇ID")
    word: str = Field(description="词汇文本")
    start: float = Field(description="开始时间（秒）")
    end: float = Field(description="结束时间（秒）")


class AudioTranscription(BaseModel):
    uuid: Optional[str] = Field(default=None, description="转录 UUID")
    task: str = Field(description="任务类型")
    language: str = Field(description="识别语言")
    duration: float = Field(description="总时长（秒）")
    text: str = Field(description="完整转录文本或音乐整体描述")
    segments: List[AudioSegment] = Field(description="音频片段列表")
    audio_url: str = Field(description="原始音频文件URL")
    filename: Optional[str] = Field(default=None, description="原始音频文件名")
    is_instrumental: bool = Field(default=False, description="是否为纯音乐")
    additional_data: Optional[dict] = Field(default=None, description="额外数据")
    song_name: Optional[str] = Field(default=None, description="歌曲名称")
    global_bpm: Optional[float] = Field(default=None, description="整曲 BPM")
    genre: Optional[str] = Field(default=None, description="音乐流派")
    global_emotion: Optional[str] = Field(default=None, description="听觉整体基调")
    suggested_global_theme: Optional[str] = Field(default=None, description="建议核心设计理念")
    suggested_color_palette: Optional[str] = Field(default=None, description="建议整体色彩倾向")
