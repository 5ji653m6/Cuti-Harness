import os
from enum import Enum
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import secrets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class EnvironmentType(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    PRODUCTION = "production"

class Settings(BaseSettings):
    """Base settings class with common configuration."""

    # Environment settings
    ENVIRONMENT: EnvironmentType = Field(
        default=EnvironmentType.DEVELOPMENT,
        description="Current environment"
    )
    DEBUG: bool = Field(
        default=False,
        description="Debug mode flag"
    )

    # Server settings
    SERVER_HOST: str = Field(
        default="0.0.0.0",
        description="Server host address"
    )
    SERVER_PORT: int = Field(
        default=8000,
        description="Server port number"
    )



    # OpenAI API settings
    OPENAI_API_KEY: str = Field(
        default="",
        description="OpenAI API key"
    )
    OPENAI_API_KEY_FALLBACK: str = Field(
        default="",
        description="Backup OpenAI API key used for one retry after a primary-key failure",
    )
    SUBTITLE_TRANSCRIPTION_MODEL: str = Field(
        default="whisper-1",
        description="OpenAI speech-to-text model used by media.transcribe",
    )
    SUBTITLE_TRANSCRIPTION_MAX_BYTES: int = Field(
        default=25 * 1024 * 1024,
        description="Maximum extracted audio size accepted for subtitle transcription",
    )
    # LLM quality tier for role-based model selection (prompts/llm_model_profiles.py)
    LLM_QUALITY: str = Field(
        default="best",
        description="LLM quality tier: best | common | economy",
    )

    # Pollo AI settings
    POLLO_API_KEY: str = Field(
        default="",
        description="Pollo AI API key for video generation"
    )

    # Google GenAI settings
    GOOGLE_API_KEY: str = Field(
        default="",
        description="Google GenAI API key"
    )

    WAVESPEED_API_KEY: str = Field(
        default="",
        description="WaveSpeed API key"
    )

    SUNO_API_KEY: str = Field(
        default="",
        description="Suno API key"
    )
    # LangSmith settings
    LANGSMITH_API_KEY: Optional[str] = Field(
        default=None,
        description="LangSmith API key for tracing"
    )
    LANGSMITH_ENDPOINT: str = Field(
        default="https://api.smith.langchain.com",
        description="LangSmith API endpoint"
    )
    LANGSMITH_PROJECT: Optional[str] = Field(
        default="cartoonbook",
        description="LangSmith project name"
    )
    LANGSMITH_TRACING: bool = Field(
        default=False,
        description="Enable LangSmith tracing. Default False so open-source/self-hosted deployments do not phone home; our envs set LANGSMITH_TRACING=true explicitly in .env."
    )
    # Logging settings
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level"
    )

    # Static files settings
    STATIC_PHOTOS_DIR: str = Field(
        default="static/photos",
        description="Directory for storing static photos"
    )
    # Video watermark: shots are overlaid on ingest by the media service's ensure-on-s3 step (assets/watermark.png); this path is only for local add_watermark_to_video_async
    VIDEO_WATERMARK_IMAGE_PATH: str = Field(
        default="app/assets/watermark.png",
        description="Local FFmpeg watermark path (MSC ensure-on-s3 uses Media Service WATERMARK_IMAGE_PATH)"
    )

    # S3 settings
    S3_BUCKET_NAME: str = Field(
        default="",
        description="S3 bucket name for file storage (set via env/.env)"
    )

    # CDN settings
    CDN_DOMAIN: str = Field(
        default="",
        description="CDN / public base URL for serving stored files (set via env/.env)"
    )

    # Service-to-service auth settings
    CUTI_SERVICE_ENABLED: bool = Field(
        default=True,
        description="Enable bearer-token service access for trusted callers like OpenClaw"
    )
    CUTI_SERVICE_TOKEN: str = Field(
        default="",
        description="Bearer token for trusted service callers (set via env/.env; empty disables service auth)"
    )
    CUTI_SERVICE_DEFAULT_USER_ID: Optional[str] = Field(
        default="local-user",
        description="Fallback user_id for local single-user mode and service callers"
    )

    # In-process Chat Agent (merged monorepo). Default False keeps this service byte-identical
    # to the standalone VideoAgent; the monorepo deployment sets True so the single process also
    # serves the Chat SSE router at /chat-v1/service (no separate VideoChatAgent process/HTTP hop).
    ENABLE_CHAT_AGENT: bool = Field(
        default=False,
        description="Mount the in-process Chat Agent router at /chat-v1/service. Default False = standalone VideoAgent behavior; True = merged single-process monorepo."
    )

    VIDEO_AGENT_BACKEND: Literal["deepseek"] = Field(
        default="deepseek",
        description="DeepSeek is the only Agent coordinator; Cuti owns video execution.",
    )
    VIDEO_INCREMENTAL_ENGINE_ENABLED: bool = Field(
        default=True,
        description="Enable project versions, dependency impact preview, and atomic partial rebuilds.",
    )

    # Self-hosted default "auto-continue": ChatAgent writes user_option.full_auto=True when enqueuing a delegation.
    # The gate still interrupts; the backend schedules auto_resume after a 15s delay (60s for smart clipping); the frontend shows a countdown and a "cancel auto-continue" control.
    # Default False = manual continue only. Do not confuse with state.full_auto (SmartTest skips the gate).
    VIDEO_FULL_AUTO: bool = Field(
        default=False,
        description="When True, enqueue with user_option.full_auto so interrupt gates auto-resume after countdown (15s / 60s smart-clip). Default False requires manual Continue."
    )

    # Single-user / local mode (self-hosted). Always on for this agent-only track.
    LOCAL_SINGLE_USER_MODE: bool = Field(
        default=True,
        description="When True, requests resolve to CUTI_SERVICE_DEFAULT_USER_ID (local-user). Default True for self-host."
    )

    # Base URL for external access
    BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL for external access to the application (set via env/.env)"
    )

    # Database URL
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/storybook",
        description="Database connection URL"
    )

    # Redis settings
    REDIS_URL: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis connection URL (e.g., redis://:password@host:port/db or redis://host:port/db)"
    )

    # AWS settings
    AWS_REGION: str = Field(
        default="ap-southeast-2",
        description="AWS region"
    )

    # S3-compatible storage endpoint (for open-source / self-hosted: point to MinIO)
    # Default None = use AWS S3; set e.g. http://minio:9000 to switch to S3-compatible storage.
    S3_ENDPOINT_URL: Optional[str] = Field(
        default=None,
        description="Custom S3-compatible endpoint (e.g. http://minio:9000). None = real AWS S3."
    )
    S3_ACCESS_KEY_ID: Optional[str] = Field(
        default=None,
        description="Access key for S3-compatible storage (only used when S3_ENDPOINT_URL is set)."
    )
    S3_SECRET_ACCESS_KEY: Optional[str] = Field(
        default=None,
        description="Secret key for S3-compatible storage (only used when S3_ENDPOINT_URL is set)."
    )

    # ==================== Provider backend switches ====================
    # Object storage backend: s3 (cluster deployment) | local (self-hosted / local disk via compose)
    STORAGE_BACKEND: str = Field(
        default="local",
        description="Object storage backend: 'local' (filesystem; default) or 's3' (AWS/MinIO)."
    )
    # Accounts/keys are read only from environment variables. This field is kept for compatibility with existing deployments (the value can only be env).
    ACCOUNT_BACKEND: str = Field(
        default="env",
        description="Provider key backend. Only 'env' is supported (reads keys from environment variables).",
    )

    @field_validator("ACCOUNT_BACKEND")
    @classmethod
    def _account_backend_is_env(cls, value: str) -> str:
        backend = (value or "env").strip().lower()
        if backend != "env":
            return "env"
        return backend
    # Local storage (STORAGE_BACKEND=local): on-disk directory + public base URL
    LOCAL_STORAGE_DIR: str = Field(
        default="./data/uploads",
        description="Directory for local file storage when STORAGE_BACKEND=local."
    )
    # Public base URL (used to build reachable URLs for locally stored files, e.g. http://localhost:8000). Falls back to CDN_DOMAIN when empty.
    PUBLIC_BASE_URL: str = Field(
        default="",
        description="Public base URL for locally-stored files (e.g. http://localhost:8000). Files served at {PUBLIC_BASE_URL}/files/*."
    )

    # Cuti-Media-Service (EKS internal ALB)
    MEDIA_SERVICE_URL: str = Field(
        default="http://localhost:8080",
        description="Cuti-Media-Service base URL (EKS internal ALB or local)"
    )

    # ==================== Prompt Shield (redact outbound responses) ====================
    # All shield features are off by default so shipping this code does not change existing behavior.
    # See the prompt-security design notes for the threat model and rationale.
    SHIELD_COMPANION_SSE_PUBLIC_SHAPE_ENABLED: bool = Field(
        default=False,
        description="VA companion SSE 使用公开形状（tool→message_key，不下发 args/raw result）P0-A"
    )
    SHIELD_CONVERSATION_DETAIL_SANITIZE_ENABLED: bool = Field(
        default=False,
        description="VA /conversation/detail 返回消息走字段白名单（P0-D）"
    )

    # ==================== Music Smart Clip (gradual-rollout switch) ====================
    # On by default; set to false to roll back or debug so gate_after_music no longer carries the smart_clip payload.
    # Note: music_generation_node still analyzes synchronously and writes smart_clip into additional_data (persisted in the DB),
    # this only controls whether it is handed to the frontend on interrupt. When the frontend has no smart_clip, SmartClipPanel does not render (original view is kept).
    MUSIC_SMART_CLIP_ENABLED: bool = Field(
        default=True,
        description="智能剪辑总开关：False 时 gate_after_music interrupt 不带 smart_clip payload",
    )

    # ==================== Runtime workspace ====================
    # Local runtime data and media cache directory; persistent media still goes through S3/CDN.
    STAGE_ARTIFACT_ROOT: str = Field(
        default="data/run_workspaces",
        description="Per-run workspace root relative to services/agent (not under kit/). Absolute paths allowed.",
    )
    STAGE_ARTIFACT_MIRROR_S3: bool = Field(
        default=False,
        description="When True, optionally mirror stage JSON artifacts to S3 (not used on agent hot path). Default False.",
    )

    model_config = SettingsConfigDict(
        env_file=[".env.production", ".env.development", ".env.local", ".env"],  # priority order
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

class LocalSettings(Settings):
    """Local development environment settings."""

    ENVIRONMENT: EnvironmentType = EnvironmentType.LOCAL
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    SERVER_PORT: int = 9002  # local uses a distinct port to avoid clashing with other environments

    # Local database configuration
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/storybook_dev",
        description="Local database connection URL"
    )

    class Config:
        env_file = ".env.local"

class DevelopmentSettings(Settings):
    """Development environment settings."""

    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    SERVER_PORT: int = 9001  # dev uses a distinct port to avoid clashing with production

    # Development database configuration
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/storybook_dev",
        description="Development database connection URL"
    )

    class Config:
        env_file = ".env"

class ProductionSettings(Settings):
    """Production environment settings."""

    ENVIRONMENT: EnvironmentType = EnvironmentType.PRODUCTION
    DEBUG: bool = False
    LOG_LEVEL: str = "DEBUG"  # same as dev for easier debugging; can be overridden via .env.production
    SERVER_PORT: int = 8000  # production uses the standard port

    class Config:
        env_file = ".env.production"

@lru_cache()
def get_settings() -> Settings:
    """
    Get the appropriate settings based on the ENVIRONMENT variable.
    Uses LRU cache to prevent reloading the settings multiple times.
    """
    environment = os.getenv("ENVIRONMENT", EnvironmentType.DEVELOPMENT)

    settings_map: Dict[str, Any] = {
        EnvironmentType.LOCAL: LocalSettings,
        EnvironmentType.DEVELOPMENT: DevelopmentSettings,
        EnvironmentType.PRODUCTION: ProductionSettings,
    }

    settings_class = settings_map.get(environment, DevelopmentSettings)
    return settings_class()

# Create a singleton settings instance
settings = get_settings()
