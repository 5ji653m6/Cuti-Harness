from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.security import validate_relative_path


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class InputFile(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    content_base64: str = Field(max_length=24 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        validate_relative_path(value)
        return value


class NetworkMode(StrEnum):
    NONE = "none"
    ALLOWLIST = "allowlist"


class NetworkPolicy(StrictModel):
    mode: NetworkMode = NetworkMode.NONE
    allowed_domains: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("allowed_domains")
    @classmethod
    def domains_are_exact_public_hostnames(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if (
                not re.fullmatch(
                    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                    r"[a-z]{2,63}",
                    host,
                )
                or host == "localhost"
            ):
                raise ValueError(f"allowed domain must be an exact public hostname: {value}")
            normalized.append(host)
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_mode_and_domains(self):
        if self.mode == NetworkMode.NONE and self.allowed_domains:
            raise ValueError("allowed_domains requires network mode 'allowlist'")
        if self.mode == NetworkMode.ALLOWLIST and not self.allowed_domains:
            raise ValueError("allowlist network mode requires allowed_domains")
        return self


class RunRequest(StrictModel):
    image: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/@:-]{0,254}$")
    command: list[str] = Field(min_length=1, max_length=64)
    inputs: list[InputFile] = Field(default_factory=list, max_length=128)
    artifacts: list[str] = Field(default_factory=list, max_length=128)
    timeout_seconds: int = Field(default=60, ge=1)
    environment: dict[str, str] = Field(default_factory=dict, max_length=32)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    @field_validator("command")
    @classmethod
    def command_is_bounded(cls, value: list[str]) -> list[str]:
        if any(not part or len(part) > 4096 or "\x00" in part for part in value):
            raise ValueError("command arguments must be non-empty and at most 4096 characters")
        return value

    @field_validator("artifacts")
    @classmethod
    def artifacts_are_safe(cls, value: list[str]) -> list[str]:
        for path in value:
            validate_relative_path(path)
        if len(value) != len(set(value)):
            raise ValueError("artifact paths must be unique")
        return value

    @field_validator("environment")
    @classmethod
    def environment_is_safe(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key
            or not key.replace("_", "A").isalnum()
            or not (key[0].isalpha() or key[0] == "_")
            or len(key) > 128
            or len(item) > 4096
            or "\x00" in item
            for key, item in value.items()
        ):
            raise ValueError("invalid environment variable")
        return value


class Artifact(StrictModel):
    path: str
    media_type: str
    size_bytes: int
    sha256: str
    content_base64: str


class RunEnvelope(StrictModel):
    run_id: str
    status: RunStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    artifacts: list[Artifact] = Field(default_factory=list)
    error: str | None = None


class CreateRunResponse(StrictModel):
    run_id: str
    status: RunStatus

