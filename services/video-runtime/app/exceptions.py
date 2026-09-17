from fastapi import HTTPException
from typing import Any, Optional, Dict
from enum import Enum

class BusinessExceptionCode(Enum):
    # Generic business errors
    RESOURCE_NOT_FOUND = (10002, "资源未找到", "Resource not found")
    INTERNAL_SERVER_ERROR = (10003, "服务器内部错误", "Internal server error")
    INVALID_CONTENT_TYPE = (10006, "无效的内容类型", "Invalid content type")
    INVALID_PARAMETER = (10007, "无效的参数", "Invalid parameter")

    # OpenAI-related errors
    OPENAI_IMAGE_ANALYSIS_ERROR = (10012, "OpenAI图片分析失败", "OpenAI image analysis failed")

    # File and image processing errors
    FILE_UPLOAD_FAILED = (10030, "文件上传失败", "File upload failed")
    FILE_TOO_LARGE = (10031, "文件过大", "File too large")
    UNSUPPORTED_FILE_FORMAT = (10033, "不支持的文件格式", "Unsupported file format")

    # User and auth errors (code values aligned with the backend error codes)
    INVALID_REQUEST_PARAMETERS = (10001, "无效的请求参数", "Invalid request parameters")
    CONFIGURATION_ERROR = (10009, "配置错误", "Configuration error")
    UNAUTHORIZED = (10050, "未授权", "Unauthorized")
    PERMISSION_DENIED = (10051, "权限不足", "Permission denied")
    INSUFFICIENT_CREDITS = (10058, "积分不足", "Insufficient credits")
    INVALID_TOKEN = (10110, "无效的令牌", "Invalid token")

    # Agent related errors
    AGENT_INPUT_ANALYSIS_ERROR = (10121, "Agent输入分析失败", "Agent input analysis failed")

    # Generic business errors
    BUSINESS_ERROR = (10140, "业务逻辑错误", "Business logic error")

    # Video eligibility: requires a prior real payment/subscription
    VIDEO_ELIGIBILITY_REQUIRED = (10155, "视频创作需先完成一次充值或订阅", "Video creation requires at least one purchase or subscription")

    # Video Agent related errors
    VIDEO_ANALYSIS_UUID_MISSING = (10150, "缺少视频分析UUID", "Video analysis UUID missing")
    VIDEO_ANALYSIS_DATA_NOT_FOUND = (10151, "未找到视频分析数据", "Video analysis data not found")
    VIDEO_DATABASE_CONNECTION_MISSING = (10152, "缺少数据库连接", "Database connection missing")

    # Resume idempotency: the run was already resumed or this interrupt was already continued; the API layer can return 200 without erroring
    RESUME_ALREADY_CONTINUED = (10156, "该任务已继续", "Task already continued")

    def __init__(self, code, message_zh, message_en):
        self._value_ = code
        self.message_zh = message_zh
        self.message_en = message_en

    @property
    def code(self):
        return self.value

    def message(self, lang: str = "zh"):
        return self.message_zh if lang == "zh" else self.message_en

class BusinessException(Exception):
    def __init__(self, error_code: BusinessExceptionCode, detail: Optional[str] = None, lang: str = "zh"):
        self.error_code = error_code
        self.detail = detail or error_code.message(lang)
        self.lang = lang
        super().__init__(self.detail)

    def to_dict(self):
        return {
            "code": self.error_code.code,
            "message": self.error_code.message(self.lang),
            "detail": self.detail
        }