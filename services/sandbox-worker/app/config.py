from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_", extra="ignore")

    staging_root: Path = Path("/var/lib/cuti-sandbox")
    max_concurrent_runs: int = Field(default=4, ge=1, le=64)
    max_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_input_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    max_artifact_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    max_log_bytes: int = Field(default=1024 * 1024, ge=1)
    memory_limit: str = "512m"
    nano_cpus: int = Field(default=1_000_000_000, ge=100_000_000)
    pids_limit: int = Field(default=128, ge=16)
    sandbox_uid: int = Field(default=65532, ge=1)
    sandbox_gid: int = Field(default=65532, ge=1)
    environment: str = "development"
    unsafe_dev_mode: bool = False
    internal_token: str = ""

    @model_validator(mode="after")
    def reject_unsafe_production(self):
        if self.unsafe_dev_mode and self.environment.lower() == "production":
            raise ValueError("SANDBOX_UNSAFE_DEV_MODE cannot be enabled in production")
        return self

