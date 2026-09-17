/** Serializable video project runtime vocabulary. @module @cuti-ai/video-runtime/types */

export type JsonPrimitive = string | number | boolean | null
/** JSON-serializable parameter or artifact content; excludes executable values. */
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

/** Current project selection and active builds, independent of a conversation turn. */
export interface ProjectSnapshot {
  projectId: string
  title: string
  status: string
  currentVersionId: string
  artifactCount: number
  activeBuildIds: string[]
  summary: string
}

/** Stable character identity and appearance constraints used across shots. */
export interface VideoCharacterSpec {
  id: string
  name: string
  appearance: string
  clothing?: string
  personality?: string
  voice?: string
}

/** A timed shot with creative instructions and project-local reference identifiers. */
export interface VideoShotSpec {
  id: string
  order: number
  duration_seconds: number
  beat: string
  visual_prompt: string
  narration?: string
  character_ids?: string[]
  reference_asset_ids?: string[]
  transition?: string
}

/** Persistent and independent locale choices for every user-visible and media output. */
export interface VideoLanguageContract {
  ui_locale: 'zh-CN' | 'en-US'
  content_language: 'zh-CN' | 'en-US'
  spoken_language: 'zh-CN' | 'en-US'
  subtitle_language: 'zh-CN' | 'en-US'
  provider_prompt_language: 'auto' | 'zh-CN' | 'en-US'
}

/** Complete production specification with independent language and provider choices. */
export interface VideoSpec {
  title: string
  language: string
  language_contract: VideoLanguageContract
  target_duration_seconds: number
  aspect_ratio: '16:9' | '9:16' | '1:1'
  resolution: string
  /** Installed Video Runtime workflow id, including workflow SKILL.md adapters. */
  workflow_id: string
  style_id: string
  activated_skill_ids?: string[]
  source_asset_ids?: string[]
  workflow_parameters?: Record<string, JsonValue>
  characters: VideoCharacterSpec[]
  shots: VideoShotSpec[]
  audio: { narration_voice: string; bgm_prompt: string; subtitles: boolean }
  providers: { video: string; image: string; music: string }
  automation: { mode: 'automatic'; max_artifact_retries: number }
}

/** Initial user constraints; unresolved creative details can be planned later. */
export interface ProjectIntent {
  title: string
  brief: string
  language: string
  language_contract: VideoLanguageContract
  target_duration_seconds: number
  aspect_ratio: '16:9' | '9:16' | '1:1'
  resolution: string
  workflow_id: string
  style_id: string
  activated_skill_ids?: string[]
  source_asset_ids?: string[]
  workflow_parameters?: Record<string, JsonValue>
  providers: { video: string; image: string; music: string }
  automation: { mode: 'automatic'; max_artifact_retries: number }
  constraints?: Record<string, JsonValue>
}

/** Idempotent request to create a long-lived project. */
export interface CreateProjectRequest {
  title: string
  idempotencyKey: string
}

/** Version-checked planning request accepting intent or a complete specification. */
export interface BuildPlanRequest {
  projectId: string
  baseProjectVersionId: string
  idempotencyKey: string
  videoSpec?: VideoSpec
  projectIntent?: ProjectIntent
}

/** Persisted plan revision, concrete steps, costs, and next planning checkpoint. */
export interface BuildPlanSnapshot {
  planId: string
  projectId: string
  kind: 'initial' | 'incremental' | 'export'
  status: string
  baseProjectVersionId: string
  workflowId: string
  videoSpec?: VideoSpec
  projectIntent?: ProjectIntent
  shotCount: number
  schemaVersion: 1 | 2
  planRevision: number
  specRevisionId?: string
  currentPhase: string
  nextCheckpoint?: Record<string, JsonValue>
  estimatedCost: number
  steps: Array<Record<string, JsonValue>>
}

/** Requested artifact changes for impact analysis without execution. */
export interface ChangePreviewRequest {
  projectId: string
  change: string
  targetArtifactVersionIds: string[]
  idempotencyKey: string
}

/** Dependency impact classification and estimated rebuild order and cost. */
export interface ChangePreview {
  planId: string
  projectId: string
  baseProjectVersionId: string
  staleArtifactIds: string[]
  validationArtifactIds: string[]
  reusedArtifactIds: string[]
  rebuildOrder: string[]
  estimatedCost: number
}

/** Supported structured editing operations. */
export type VideoEditType =
  | 'patch_character' | 'patch_scene' | 'patch_shot' | 'regenerate_artifact'
  | 'replace_music' | 'generate_lipsync' | 'patch_timeline'

/** One logical edit or artifact regeneration with replacement parameters. */
export interface VideoEdit {
  type: VideoEditType
  id?: string
  artifactVersionId?: string
  prompt?: string
  patch?: Record<string, JsonValue>
}

/** Idempotent edit preview based on a specific project version. */
export interface EditPreviewRequest {
  projectId: string
  baseProjectVersionId: string
  idempotencyKey: string
  description: string
  edits: VideoEdit[]
}

/** Versioned project artifact metadata exposed to the planner. */
export interface MediaArtifactSummary {
  artifactVersionId: string
  artifactId: string
  logicalId: string
  type: string
  title: string
  summary: string
}

/** Runtime capability description, parameter schema, and enabled state. */
export interface CapabilityPromptView {
  id: string
  accepted_aliases: string[]
  description: string
  required_inputs: string[]
  optional_references: string[]
  output: string
  executor: string
  parameters_schema: Record<string, JsonValue>
  trust_level: string
  enabled: boolean
}

/** Accepted artifact role and multiplicity for one capability input. */
export interface PlanPatchCapabilityInputContract {
  role: string
  artifact_types: string[]
  parameter: string
  required: boolean
  multiple: boolean
  description: string
}

/** Runtime-owned operation schema and input binding requirements. */
export interface PlanPatchCapabilityContract {
  capability: string
  description: string
  inputs: PlanPatchCapabilityInputContract[]
  output_artifact_type: string
  replaces_input_role?: string
  estimated_cost: number
  skill_id?: string
  parameters_schema: Record<string, JsonValue>
}

/** Artifact input referencing a persisted version or a preceding operation. */
export interface PlanPatchInput {
  role: string
  artifact_version_id?: string
  operation_step_id?: string
}

/** A proposed capability invocation with typed artifact input roles. */
export interface PlanPatchOperation {
  step_id: string
  capability: string
  inputs: PlanPatchInput[]
  parameters?: Record<string, JsonValue>
  title?: string
}

/** Version-checked preview of dynamically composed operations. */
export interface PlanPatchPreviewRequest {
  projectId: string
  baseProjectVersionId: string
  idempotencyKey: string
  description: string
  operations: PlanPatchOperation[]
}

/** Idempotent execution request for an existing plan and base version. */
export interface RebuildRequest {
  projectId: string
  planId: string
  baseProjectVersionId: string
  idempotencyKey: string
}

/** Durable build lifecycle summary; completion may publish a project version. */
export interface BuildSnapshot {
  buildId: string
  projectId: string
  status: 'queued' | 'running' | 'waiting_external' | 'waiting_agent' | 'completed' | 'failed' | 'cancelled'
  progress: number
  message: string
  projectVersionId?: string
  kind: 'initial' | 'incremental' | 'export'
  estimatedCost: number
  actualCost: number
  error?: string
}

/** Versioned planning handoff containing real artifacts and unresolved decisions. */
export interface PlanCheckpoint {
  id: string
  project_id: string
  build_id: string
  plan_id: string
  workflow_id: string
  session_id: string
  phase: string
  next_phase: string
  status: 'pending' | 'planning' | 'resolved' | 'failed'
  artifact_summaries: Array<Record<string, JsonValue>>
  resolved_sections: string[]
  unresolved_sections: string[]
  planner_instruction: string
  planning_mode: 'staged' | 'agentic'
  base_plan_revision: number
  base_spec_revision: number
  delivery_attempts: number
  error?: string
}

/** Idempotent planning update with optimistic plan and specification revisions. */
export interface CheckpointResolutionRequest {
  projectId: string
  buildId: string
  checkpointId: string
  basePlanRevision: number
  baseSpecRevision: number
  idempotencyKey: string
  videoSpec?: VideoSpec
  videoSpecPatch?: Record<string, JsonValue>
  phaseInputs?: Record<string, JsonValue>
  proposedSteps?: Array<Record<string, JsonValue>>
  cancelStepIds?: string[]
  /** Failed task IDs mapped to new proposed task IDs; pending descendants are rewired atomically. */
  replaceFailedStepIds?: Record<string, string>
  goalSatisfied?: boolean
  waitingForInput?: boolean
  response?: string
  reason?: string
}

/** Version-checked selection of an existing artifact without generation. */
export interface ArtifactSelectionRequest {
  projectId: string
  versionId: string
  baseProjectVersionId: string
  idempotencyKey: string
}

/** Committed artifact selection and resulting project version. */
export interface ArtifactSelectionResult {
  projectId: string
  artifactId: string
  versionId: string
  projectVersionId: string
}

/** Idempotent export request bound to a project version. */
export interface ExportRequest {
  projectId: string
  baseProjectVersionId: string
  idempotencyKey: string
  format: string
}

/** Export lifecycle and output URI when available. */
export interface ExportResult {
  exportId: string
  projectId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  uri?: string
}

/** Caller-provided session and user attribution; not a self-issued permission grant. */
export interface RequestIdentity {
  sessionId?: string
  userId?: string
}

/** Installed workflow discovery and execution availability. */
export interface WorkflowSummary {
  id: string
  title: string
  description: string
  mode: string
  available: boolean
  unavailableReason?: string
  requiredCapabilities: string[]
  missingCapabilities: string[]
  userSelectable: boolean
  executionKind: string
  /** Exact Runtime compiler selected for this Workflow; absent only when unavailable. */
  compiler?: string | null
  entrypoints: string[]
}

/** Workflow instructions, capability requirements, and resource ownership. */
export interface WorkflowDetail extends WorkflowSummary {
  parameters: Record<string, JsonValue>
  pipeline: string[]
  skillDependencies: string[]
  instructions: string
  /** Optional Skill whose original instructions define this plugin Workflow alias. */
  instructionSkillId?: string
  /** Explicit plugin-only extension appended after the source Skill instructions. */
  instructionAppendix?: string
  /** Skill id that must be passed to loadSkillResource for every listed path. */
  resourceOwnerSkillId: string
  resources: string[]
  resourceContents: Array<{ path: string; content: string }>
  /** Runtime-owned provider facts; Workflow Skills only teach planning policy. */
  videoModelCapabilities?: Array<Record<string, JsonValue>>
}

/** Loaded Skill instructions and discoverable bundled resources. */
export interface SkillDetail {
  id: string
  description: string
  kind: string
  instructions: string
  /** Skill id that must be passed to loadSkillResource for every listed path. */
  resourceOwnerSkillId: string
  resources: string[]
  resourceContents: Array<{ path: string; content: string }>
}

/** One resolved Skill resource and its text contents. */
export interface SkillResourceDetail {
  id: string
  path: string
  content: string
}
