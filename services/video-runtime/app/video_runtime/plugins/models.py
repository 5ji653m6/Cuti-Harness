from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models import (
    CheckpointResolution,
    MediaCapabilityContract,
    MediaArtifactVersion,
    PlanCheckpoint,
    ProjectIntent,
    RebuildPlan,
    ValidationResult,
    VideoSpec,
)
from ..security import CapabilityExecutionEnvelope


class PluginPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_domains: list[str] = Field(default_factory=list)
    credentials: list[str] = Field(default_factory=list)
    sandbox: bool = True
    max_cost_usd: float = Field(default=0, ge=0)


class PluginContributions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    styles: list[str] = Field(default_factory=list)
    validators: list[str] = Field(default_factory=list)
    media_operators: list[str] = Field(default_factory=list)
    # Capabilities that an Agent may append as a PlanPatch. Separate from
    # execution registration: installing a capability never makes it addable
    # on every Workflow.
    plan_patch_capabilities: list[str] = Field(default_factory=list)


class PluginSandboxRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/@:-]{0,254}$")
    entrypoint: str = Field(min_length=1)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @field_validator("entrypoint")
    @classmethod
    def entrypoint_is_confined(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("sandbox entrypoint must be a confined relative path")
        return normalized


class VideoPluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
    api_version: str = Field(default="v1", pattern=r"^v1$")
    runtime_entrypoint: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$",
    )
    contributions: PluginContributions = Field(default_factory=PluginContributions)
    skills: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    permissions: PluginPermissions = Field(default_factory=PluginPermissions)
    migration_version: int = Field(default=0, ge=0)
    cordis_plugin: str | None = None
    frontend_extension: str | None = None
    trusted: bool = False
    sandbox_runtime: PluginSandboxRuntime | None = None

    @model_validator(mode="after")
    def execution_mode_is_complete(self):
        if self.trusted and not self.runtime_entrypoint:
            raise ValueError("trusted plugin requires runtime_entrypoint")
        return self


@dataclass
class PluginContext:
    project_id: str | None = None
    build_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)


class VideoPlugin(Protocol):
    def plan_patch_capability_contracts(self) -> list[MediaCapabilityContract]: ...
    def media_capability_contracts(self) -> list[MediaCapabilityContract]: ...
    def planning_mode(self, workflow_id: str) -> str: ...
    async def compile_build_plan(
        self, context: PluginContext, spec: VideoSpec,
    ) -> RebuildPlan: ...
    async def compile_initial(
        self, context: PluginContext, intent: ProjectIntent,
    ) -> RebuildPlan: ...
    async def compile_phase(
        self,
        context: PluginContext,
        checkpoint: PlanCheckpoint,
        resolution: CheckpointResolution,
        plan: RebuildPlan,
    ) -> RebuildPlan: ...
    def capability_handlers(self) -> dict[
        str,
        Callable[[CapabilityExecutionEnvelope, dict[str, Any]], Awaitable[Any]],
    ]: ...
    async def on_load(self, context: PluginContext) -> None: ...
    async def before_plan(self, context: PluginContext) -> None: ...
    async def after_plan(self, context: PluginContext, plan: RebuildPlan) -> RebuildPlan: ...
    async def before_execute(self, context: PluginContext, envelope: CapabilityExecutionEnvelope) -> None: ...
    async def after_execute(self, context: PluginContext, result: Any) -> Any: ...
    async def validate_artifact(
        self, context: PluginContext, artifact: MediaArtifactVersion,
    ) -> list[ValidationResult]: ...
    async def on_artifact_committed(self, context: PluginContext, artifact: MediaArtifactVersion) -> None: ...
    async def on_unload(self, context: PluginContext) -> None: ...
    async def migrate(self, context: PluginContext, from_version: int, to_version: int) -> None: ...


class BaseVideoPlugin:
    """No-op lifecycle base for plugins that implement only selected contributions."""

    def capability_handlers(self) -> dict[
        str,
        Callable[[CapabilityExecutionEnvelope, dict[str, Any]], Awaitable[Any]],
    ]:
        return {}

    def plan_patch_capability_contracts(self) -> list[MediaCapabilityContract]:
        """Describe the explicitly allow-listed Artifact transformations.

        ``media_capability_contracts`` remains as the v1 compatibility hook for
        existing video plugins; the Harness consumes this generic hook.
        """
        return self.media_capability_contracts()

    def media_capability_contracts(self) -> list[MediaCapabilityContract]:
        return []

    async def compile_build_plan(
        self, _context: PluginContext, _spec: VideoSpec,
    ) -> RebuildPlan:
        raise NotImplementedError("plugin does not contribute a workflow compiler")

    async def compile_initial(
        self, _context: PluginContext, _intent: ProjectIntent,
    ) -> RebuildPlan:
        raise NotImplementedError("plugin does not contribute a staged workflow compiler")

    async def compile_phase(
        self,
        _context: PluginContext,
        _checkpoint: PlanCheckpoint,
        _resolution: CheckpointResolution,
        _plan: RebuildPlan,
    ) -> RebuildPlan:
        raise NotImplementedError("plugin does not contribute a staged workflow compiler")

    async def on_load(self, _context: PluginContext) -> None: return None
    async def before_plan(self, _context: PluginContext) -> None: return None
    async def after_plan(self, _context: PluginContext, plan: RebuildPlan) -> RebuildPlan: return plan
    async def before_execute(
        self, _context: PluginContext, _envelope: CapabilityExecutionEnvelope,
    ) -> None: return None
    async def after_execute(self, _context: PluginContext, result: Any) -> Any: return result
    async def validate_artifact(
        self, _context: PluginContext, _artifact: MediaArtifactVersion,
    ) -> list[ValidationResult]: return []
    async def on_artifact_committed(
        self, _context: PluginContext, _artifact: MediaArtifactVersion,
    ) -> None: return None
    async def on_unload(self, _context: PluginContext) -> None: return None
    async def migrate(
        self, _context: PluginContext, _from_version: int, _to_version: int,
    ) -> None: return None


@dataclass(frozen=True)
class LoadedVideoPlugin:
    manifest: VideoPluginManifest
    implementation: VideoPlugin
    manifest_path: Path
    def planning_mode(self, _workflow_id: str) -> str:
        return "full"
