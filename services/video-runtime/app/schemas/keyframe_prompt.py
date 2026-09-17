"""Keyframe prompt data shared without importing legacy execution services."""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class RefImageRole(str, Enum):
    """Reference-image character type."""
    CHARACTER = "character"
    SHEET = "sheet"
    FIRST_FRAME = "first_frame"


class RefImageInfo(BaseModel):
    """Structured info for a single reference image."""
    url: str = Field(description="图片 URL（干净，无内部 tag）")
    role: RefImageRole = Field(description="图片角色：角色参考图 / Reference Sheet / 首帧")
    label: Optional[str] = Field(default=None, description="标签（角色名、'Reference Sheet (溢出角色)' 等）")


# ---------------------------------------------------------------------------
# keyframe prompt result
# ---------------------------------------------------------------------------
class KeyframePromptResult(BaseModel):
    """Result of generating a single keyframe prompt."""
    shot_number: int = Field(description="镜头编号")
    t2i_prompt: str = Field(description="生成的关键帧提示词（使用本镜头内 image 1, image 2 等引用）")
    frame_index: int = Field(default=0, description="帧索引：0=首帧, -1=尾帧")

    ref_images: List[RefImageInfo] = Field(
        default_factory=list,
        description="本镜头参考图列表（含角色图、拼接表、首帧等），顺序与 prompt 中 image 1, image 2 对应"
    )

    final_prompt: Optional[str] = Field(
        default=None,
        description="最终执行的 prompt（resolve 阶段设置，可能含 Reference Sheet 引导语前缀）"
    )

    user_regenerate_instruction: Optional[str] = Field(
        default=None,
        description="再生时用户自然语言修改说明；与 t2i_prompt 在 tool execution 模板中分开展示",
    )

    # -- computed properties --------------------------------------------------
    @property
    def has_reference_sheet(self) -> bool:
        return any(img.role == RefImageRole.SHEET for img in self.ref_images)

    @property
    def sheet_index(self) -> Optional[int]:
        for i, img in enumerate(self.ref_images):
            if img.role == RefImageRole.SHEET:
                return i
        return None

    @property
    def all_ref_urls(self) -> List[str]:
        """All reference-image URLs (passed to the model)."""
        return [img.url for img in self.ref_images]

    @property
    def display_ref_urls(self) -> List[str]:
        """Reference-image URLs shown to the frontend (excluding the Reference Sheet)."""
        return [img.url for img in self.ref_images if img.role != RefImageRole.SHEET]


class BatchKeyframePromptResult(BaseModel):
    """Wrapper class for batch keyframe-prompt generation results."""
    prompts: List[KeyframePromptResult] = Field(description="批量关键帧prompt生成结果列表")
