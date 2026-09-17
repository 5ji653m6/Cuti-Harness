from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.skills.lock import SkillLock
from app.orchestration.skills.models import (
    ResolvedSkillRef,
    SkillConstraintContract,
    SkillContext,
    SkillHardConstraint,
)


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InputFile(BaseModel):
    type: str
    url: str
    filename: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlannedTask(BaseModel):
    capability_id: str
    objective: str
    input_artifact_version_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    resolved_skills: list[ResolvedSkillRef] = Field(default_factory=list)
    skill_context: SkillContext | None = None
    constraint_contract: SkillConstraintContract | None = None
    client_key: str = Field(default_factory=uid)


class InterruptionRequest(BaseModel):
    category: Literal["skill_required", "failure", "blocked", "workflow_confirm"]
    requires_confirmation: bool = True
    what_happened: str = Field(min_length=1)
    why_interrupted: str = Field(min_length=1)
    what_next: str = Field(min_length=1)
    skill_name: str | None = None
    skill_resource: str | None = None
    skill_policy: str | None = None
    capability_id: str | None = None
    task_id: str | None = None
    stage: str | None = None
    will_auto_resume: bool = False
    auto_resume_seconds: int | None = Field(default=None, ge=0)


class PlanPatch(BaseModel):
    base_revision: int = 0
    reason: str = ""
    add_tasks: list[PlannedTask] = Field(default_factory=list)
    cancel_task_ids: list[str] = Field(default_factory=list)
    goal_satisfied: bool = False
    waiting_for_input: bool = False
    interruption: InterruptionRequest | None = None
    response: str = ""


class AgentRun(BaseModel):
    id: str = Field(default_factory=uid)
    thread_id: str
    project_id: str
    user_id: str
    title: str = ""
    objective: str
    idempotency_key: str
    status: RunStatus = RunStatus.PLANNING
    current_revision: int = 0
    goal_started_revision: int = 0
    last_response: str = ""
    output_language: Literal["zh", "en"] = "en"
    user_option: dict[str, Any] | None = None
    input_files: list[InputFile] = Field(default_factory=list)
    activated_skills: list[str] = Field(default_factory=list)
    skill_locks: list[SkillLock] = Field(default_factory=list)
    durable_summary: str = ""
    summary_through_sequence: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class PlanRevision(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    number: int
    parent_number: int
    reason: str = ""
    patch: PlanPatch
    created_at: datetime = Field(default_factory=now)


class Task(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    revision: int
    client_key: str
    capability_id: str
    objective: str
    input_artifact_version_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    resolved_skills: list[ResolvedSkillRef] = Field(default_factory=list)
    skill_context: SkillContext | None = None
    status: TaskStatus = TaskStatus.PROPOSED
    remote_operation_id: str | None = None
    remote_thread_id: str | None = None
    remote_interrupt_msgid: int | None = None
    error: str | None = None
    execution_phase: str = "queued"
    attempt_count: int = 0
    max_attempts: int = 3
    failure_category: str | None = None
    action_required: str | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    def objective_with_skill_context(self) -> str:
        return self.apply_skill_context(self.objective)

    def apply_skill_context(self, text: str) -> str:
        return self.skill_context.apply_to(text) if self.skill_context is not None else text


class TaskAttempt(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    task_id: str
    number: int
    status: AttemptStatus = AttemptStatus.RUNNING
    idempotency_key: str
    remote_operation_id: str | None = None
    error: str | None = None
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None


class ToolInvocation(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    task_id: str | None = None
    tool_name: str
    idempotency_key: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    status: str = "started"
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ArtifactVersion(BaseModel):
    id: str = Field(default_factory=uid)
    artifact_id: str = Field(default_factory=uid)
    project_id: str
    type: str
    version: int = 1
    status: str = "ready"
    produced_by_task_id: str
    title: str = ""
    summary: str = ""
    uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class ArtifactEdge(BaseModel):
    id: str = Field(default_factory=uid)
    project_id: str
    source_version_id: str
    target_version_id: str
    relation: str
    created_at: datetime = Field(default_factory=now)


class ArtifactSelection(BaseModel):
    project_id: str
    type: str
    artifact_version_id: str
    updated_at: datetime = Field(default_factory=now)


class DomainEvent(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    sequence: int = 0
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class UserCommand(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    content: str
    idempotency_key: str
    created_at: datetime = Field(default_factory=now)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=uid)
    run_id: str
    role: str
    content: str
    sequence: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class SourceEvent(BaseModel):
    remote_run_id: str
    event_type: str
    source_event_id: str | None = None
    content: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class RunSnapshot(BaseModel):
    run: AgentRun
    revisions: list[PlanRevision] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    artifacts: list[ArtifactVersion] = Field(default_factory=list)
    selections: list[ArtifactSelection] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    last_event_sequence: int = 0
