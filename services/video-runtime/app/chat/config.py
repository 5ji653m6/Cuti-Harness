"""
Video chat-agent configuration
Loads .env.local / .env.development / .env.production based on ENVIRONMENT
"""
import os
from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# load_dotenv is already done by main based on ENVIRONMENT at startup; this only reads environment variables
class EnvironmentType(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


# Prompt Shield: for local testing, set this to True to turn on all SHIELD_* boolean switches at once (no .env needed).
# Keep it False before merging to main / going live; individual fields can still be overridden via SHIELD_* environment variables.
PROMPT_SHIELD_DEV_ALL_ENABLED = True


class Settings(BaseSettings):
    ENVIRONMENT: EnvironmentType = Field(default=EnvironmentType.DEVELOPMENT, description="运行环境")
    DEBUG: bool = Field(default=False, description="调试模式")
    SERVER_HOST: str = Field(default="0.0.0.0", description="监听地址")
    SERVER_PORT: int = Field(default=9004, description="服务端口")
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")

    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/storybook_dev",
        description="数据库连接",
    )
    REDIS_URL: str = Field(default="redis://127.0.0.1:6379/0", description="Redis 连接")
    VIDEOAGENT_BASE_URL: str = Field(
        default="",
        description="Cuti-VideoAgent 服务 API 基础地址，例如 https://videoagent-host/api/cuti",
    )
    CUTI_SERVICE_TOKEN: str = Field(default="", description="调用 Cuti-VideoAgent 的服务间 Bearer Token")
    VIDEOAGENT_REQUEST_TIMEOUT_SECONDS: int = Field(default=60, description="调用 Cuti-VideoAgent 的超时时间（秒）")
    # workflow invocation mode:
    # http (default) = delegate-submit over HTTP to a separate VideoAgent process (original behavior, unchanged);
    # local = merged monolith: call the VideoAgent enqueue logic in-process directly, skipping the HTTP hop and inter-service auth.
    WORKFLOW_CLIENT_MODE: str = Field(
        default="http",
        description="http = delegate over HTTP (default, unchanged); local = in-process call into VideoAgent core (merged monorepo).",
    )

    # user-uploaded images/audio/video are returned as CDN URLs after S3 (for frontend display and downstream use)
    AWS_REGION: str = Field(
        default="ap-southeast-2",
        description="AWS region",
    )
    S3_BUCKET_NAME: str = Field(
        default="",
        description="Optional object-store bucket when STORAGE_BACKEND=s3",
    )
    CDN_DOMAIN: str = Field(
        default="",
        description="Optional public base URL when using object storage",
    )

    MEDIA_SERVICE_URL: str = Field(
        default="http://localhost:8080",
        description="Media Service base URL",
    )

    # ==================== Prompt Shield（Input/Output Rail） ====================
    # controlled by the module constant PROMPT_SHIELD_DEV_ALL_ENABLED by default (False = all off, matching production);
    # individual fields can still be overridden via SHIELD_* in .env. See the prompt-security design notes for details.
    PROMPT_CANARY: str = Field(
        default="CUTI-CANARY-9e3f6c2b8a14",
        description="system prompt canary；不应出现在任何对外响应中，不同环境可 override",
    )
    SHIELD_INPUT_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="Input Rail 总开关（Unicode sanitize + 正则 meta-query 预筛）",
    )
    SHIELD_OUTPUT_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="Output Rail 总开关（行级 buffer + 7 条正则校验）",
    )
    SHIELD_LLM_SCREEN_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="Input Rail 的 LLM 预筛子开关（需要 SHIELD_INPUT_ENABLED=True 才生效）",
    )
    SHIELD_LLM_SCREEN_MODEL: str = Field(
        default="gpt-4.1-mini",
        description="LLM 预筛模型 id",
    )
    SHIELD_LLM_SCREEN_TIMEOUT_S: float = Field(
        default=1.5,
        description="LLM 预筛超时秒数；超时不阻塞主链路，按未命中处理",
    )
    SHIELD_COMPANION_PROXY_SANITIZE_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="VCA 代理 VA companion SSE 时逐行解析并过滤工具名/args/raw result（P0-B）",
    )
    SHIELD_THROTTLE_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="按 user_id 做 shield 命中次数限流总开关（需要 Redis）",
    )
    SHIELD_THROTTLE_THRESHOLD: int = Field(
        default=10,
        description="1 小时内触发多少次 shield 开始限流",
    )
    SHIELD_THROTTLE_WINDOW_S: int = Field(
        default=3600,
        description="限流窗口秒数",
    )
    SHIELD_AUDIT_DB_ENABLED: bool = Field(
        default=PROMPT_SHIELD_DEV_ALL_ENABLED,
        description="写 shield_events 表（需要先跑建表脚本 init/init_shield_events.py）",
    )

    CHAT_ACTION_SUGGESTIONS_MERGED: bool = Field(
        default=True,
        description="route_to_chat 将推荐动作并入同一次聊天 LLM（流式可见区 + START/END 格式化推荐动作）；失败回退独立 action_suggestions 调用",
    )

    # Deep Agent V2 is the chat coordinator.
    DEEP_AGENT_V2_ENABLED: bool = Field(default=True)
    DEEP_AGENT_V2_DATABASE_URL: str = Field(default="")
    DEEP_AGENT_V2_DATABASE_SCHEMA: str = Field(default="cuti_videochat_v2")
    DEEP_AGENT_V2_CHECKPOINT_DATABASE_URL: str = Field(default="")
    DEEP_AGENT_V2_CHECKPOINT_NAMESPACE: str = Field(default="cuti-videochat-v2")
    DEEP_AGENT_V2_MODEL: str = Field(default="gpt-5.6-terra")
    DEEP_AGENT_V2_OPENAI_API_KEY: str = Field(default="")
    OPENAI_API_KEY_FALLBACK: str = Field(default="")
    DEEP_AGENT_V2_OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")
    DEEP_AGENT_V2_TIMEOUT_SECONDS: float = Field(default=120.0)
    DEEP_AGENT_V2_TASK_MAX_ATTEMPTS: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum automatic attempts for retryable capability failures",
    )
    DEEP_AGENT_V2_TASK_TIMEOUT_SECONDS: float = Field(
        default=900.0,
        ge=10.0,
        description="Default hard timeout for one capability attempt",
    )
    DEEP_AGENT_V2_TRANSCRIPTION_TIMEOUT_SECONDS: float = Field(
        default=300.0,
        ge=30.0,
        description="Hard timeout for one media.transcribe attempt",
    )
    DEEP_AGENT_V2_PROVIDER_TIMEOUT_SECONDS: float = Field(
        default=1800.0,
        ge=60.0,
        description="Hard timeout for one provider generation or polling attempt",
    )
    DEEP_AGENT_V2_PROGRESS_INITIAL_SECONDS: float = Field(
        default=20.0,
        ge=1.0,
        description="Delay before the first automatic long-task progress message",
    )
    DEEP_AGENT_V2_PROGRESS_INTERVAL_SECONDS: float = Field(
        default=60.0,
        ge=5.0,
        description="Interval between automatic long-task progress messages",
    )
    DEEP_AGENT_V2_RETRY_BASE_DELAY_SECONDS: float = Field(
        default=2.0,
        ge=0.0,
        le=60.0,
        description="Base exponential delay before retrying a transient failure",
    )
    DEEP_AGENT_V2_MAX_PLAN_REVISIONS: int = Field(default=20, ge=1)
    DEEP_AGENT_V2_MAX_TASKS: int = Field(default=50, ge=1)
    DEEP_AGENT_V2_MAX_PARALLEL_GENERATION_TASKS: int = Field(
        default=2,
        ge=1,
        description=(
            "Max concurrent video-generation tasks per run "
            "(excludes assemble/concat/edit)"
        ),
    )
    DEEP_AGENT_V2_ACTIVE_RUN_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enforce a per-user limit on concurrently executing projects",
    )
    DEEP_AGENT_V2_MAX_ACTIVE_RUNS_PER_USER: int = Field(
        default=1,
        ge=1,
        description="Maximum planning/running/waiting_external projects per user",
    )
    DEEP_AGENT_V2_RECENT_MESSAGE_LIMIT: int = Field(default=30, ge=1)
    DEEP_AGENT_V2_SUBAGENTS_ENABLED: bool = Field(
        default=True,
        description="Allow activated Skills to delegate independent specialist work",
    )
    DEEP_AGENT_V2_TRACE_ENABLED: bool = Field(
        default=True,
        description="Write an independent JSONL trace of observable Agent decisions",
    )
    DEEP_AGENT_V2_TRACE_LOG_PATH: str = Field(
        default="logs/deep_agent_v2_trace.jsonl",
    )
    DEEP_AGENT_V2_SKILL_ROOTS: str = Field(
        default=",".join([
            str(Path(__file__).resolve().parents[2] / "skills" / "system"),
            str(Path(__file__).resolve().parents[2] / "skills" / "builtin"),
            str(Path(__file__).resolve().parents[2] / "skills" / "external"),
        ]),
        description="Comma-separated platform Skill roots (system, builtin, external)",
    )
    DEEP_AGENT_V2_EXTERNAL_SKILLS_ENABLED: bool = Field(
        default=True,
        description="Load skills from non-.system roots listed in DEEP_AGENT_V2_SKILL_ROOTS",
    )
    DEEP_AGENT_V2_MCP_SERVERS: str = Field(
        default="",
        description='JSON list of MCP servers, e.g. [{"name":"edit","url":"...","tools":["..."]}]',
    )
    DEEP_AGENT_V2_INTERNAL_EVENT_TOKEN: str = Field(default="")
    DEEP_AGENT_V2_RESULT_RECONCILE_ENABLED: bool = Field(default=True)
    DEEP_AGENT_V2_RESULT_RECONCILE_INTERVAL_SECONDS: float = Field(default=2.0)
    DEEP_AGENT_V2_RESULTS_DATABASE_URL: str = Field(default="")
    DEEP_AGENT_V2_RESULTS_SCHEMA: str = Field(default="public")
    DEEP_AGENT_V2_PIPELINE_TARGET: str = Field(default="video")
    DEEP_AGENT_V2_PIPELINE_MODE: str = Field(default="master")
    DEEP_AGENT_V2_SINGLE_VIDEO_TARGET: str = Field(default="video")
    DEEP_AGENT_V2_SINGLE_VIDEO_MODE: str = Field(default="instant")
    DEEP_AGENT_V2_VIDEO_EDIT_TARGET: str = Field(default="video")
    DEEP_AGENT_V2_VIDEO_EDIT_MODE: str = Field(default="edit")
    DEEP_AGENT_V2_SANDBOX_ENABLED: bool = Field(default=False)
    DEEP_AGENT_V2_SANDBOX_WORKER_URL: str = Field(
        default="http://sandbox-worker:8700"
    )
    DEEP_AGENT_V2_SANDBOX_TOKEN: str = Field(default="")
    DEEP_AGENT_V2_SANDBOX_REQUEST_TIMEOUT_SECONDS: float = Field(
        default=930.0,
        ge=1,
    )
    DEEP_AGENT_V2_SKILL_ENV_ALLOWLIST: str = Field(
        default="ARK_API_KEY,WAVESPEED_API_KEY",
        description="Comma-separated environment variables exposed to Skill workers",
    )
    DEEP_AGENT_V2_PROVIDER_FALLBACKS_JSON: str = Field(
        default='{"ark":"wavespeed","doubao-seedance-2-0":"wavespeed"}',
        description=(
            "JSON map of provider/model prefix → fallback provider when the "
            "primary API key is missing (e.g. ark→wavespeed)"
        ),
    )
    DEEP_AGENT_V2_HOST_GATEWAY_PUBLIC_URL: str = Field(
        default="",
        description=(
            "Absolute URL sandbox Skills use for host capabilities "
            "(defaults to PUBLIC_BASE_URL + /chat-v1/service/v2/internal/host)"
        ),
    )
    DEEP_AGENT_V2_ARK_PROTOCOL_BRIDGE: bool = Field(
        default=True,
        description=(
            "When WaveSpeed is configured and a real ARK_API_KEY is missing, "
            "redirect unmodified seedance.py Ark HTTP calls to the Ark-protocol "
            "host bridge (WaveSpeed under the hood)."
        ),
    )
    DEEP_AGENT_V2_SKILL_SIGNING_KEYS_JSON: str = Field(default="{}")

    def deep_agent_skill_root_paths(self) -> list[Path]:
        roots: list[Path] = []
        for item in self.DEEP_AGENT_V2_SKILL_ROOTS.split(","):
            text = item.strip()
            if not text:
                continue
            path = Path(text)
            if not self.DEEP_AGENT_V2_EXTERNAL_SKILLS_ENABLED and path.name == "external":
                continue
            roots.append(path)
        return roots

    def deep_agent_external_skill_root(self) -> Path:
        for path in self.deep_agent_skill_root_paths():
            if path.name == "external":
                return path
        return Path(__file__).resolve().parents[2] / "skills" / "external"

    model_config = SettingsConfigDict(
        env_file=[".env.production", ".env.development", ".env.local", ".env"],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Process-wide settings used by chat helpers, BFF uploads, and provider clients.
settings = get_settings()
