from pydantic import BaseModel, Field
from typing import Optional


class RunIdMixin(BaseModel):
    run_id: str = Field(description="Task run_id for workspace isolation")


class MediaResult(BaseModel):
    result_url: Optional[str] = Field(
        default=None,
        description="S3 CDN URL of the processed file；无音轨等跳过处理时为 null",
    )


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
