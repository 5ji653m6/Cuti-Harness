/** Video project runtime capability seam (`ctx.videoRuntime`). @module @cuti-ai/video-runtime */

import { Context, Service } from '@deepseek-ai/cordis'
import type {
  ArtifactSelectionRequest,
  ArtifactSelectionResult,
  BuildSnapshot,
  BuildPlanRequest,
  BuildPlanSnapshot,
  ChangePreview,
  ChangePreviewRequest,
  ExportRequest,
  ExportResult,
  ProjectSnapshot,
  CreateProjectRequest,
  RebuildRequest,
  RequestIdentity,
  EditPreviewRequest,
  MediaArtifactSummary,
  CapabilityPromptView,
  PlanPatchPreviewRequest,
  WorkflowSummary,
  WorkflowDetail,
  SkillDetail,
  SkillResourceDetail,
  PlanCheckpoint,
  CheckpointResolutionRequest,
} from './types.ts'

export type * from './types.ts'

declare module '@deepseek-ai/cordis' {
  interface Context {
    videoRuntime: VideoRuntime
  }
}

/** Stable interface implemented by local or remote video project runtimes. */
export abstract class VideoRuntime extends Service {
  constructor(ctx: Context) {
    super(ctx, 'videoRuntime')
  }

  /**
   * Open an existing project and bind it to the supplied session.
   * @param projectId - Persistent project identifier.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract openProject(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot>
  /**
   * Create a persistent project with an idempotent request.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract createProject(request: CreateProjectRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot>
  /**
   * Read the current project version and active build summary.
   * @param projectId - Persistent project identifier.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract inspectProject(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot>
  /**
   * List installed workflows, including unavailability reasons.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract listWorkflows(identity: RequestIdentity, signal?: AbortSignal): Promise<WorkflowSummary[]>
  /**
   * Read a workflow's instructions, resources, and execution requirements.
   * @param workflowId - Installed Workflow identifier.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract loadWorkflow(workflowId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<WorkflowDetail>
  /**
   * Read an installed Skill and its resource inventory.
   * @param skillId - Installed Skill identifier.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract loadSkill(skillId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<SkillDetail>
  /**
   * Read one resource owned by the requested Skill.
   * @param skillId - Installed Skill identifier.
   * @param path - Skill-relative resource path.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract loadSkillResource(skillId: string, path: string, identity: RequestIdentity, signal?: AbortSignal): Promise<SkillResourceDetail>
  /**
   * Persist an impact preview without submitting media generation.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract previewChange(request: ChangePreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ChangePreview>
  /**
   * Persist a structured edit plan against its base project version.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract previewEdits(request: EditPreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot>
  /**
   * List project artifacts available as planning inputs.
   * @param projectId - Persistent project identifier.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract listArtifacts(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<MediaArtifactSummary[]>
  /**
   * Read executable capabilities and their parameter schemas.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract listPlanPatchCapabilities(identity: RequestIdentity, signal?: AbortSignal): Promise<CapabilityPromptView[]>
  /**
   * Validate and persist artifact-based operations without executing them.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract previewPlanPatch(request: PlanPatchPreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot>
  /**
   * Persist an initial plan from a project intent or complete video specification.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract planProject(request: BuildPlanRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot>
  /**
   * Start a persisted plan using an idempotent, version-checked request.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract startBuild(request: RebuildRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot>
  /**
   * Execute a rebuild plan against its recorded base project version.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract applyRebuild(request: RebuildRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot>
  /**
   * Read durable build progress, costs, and failure details.
   * @param projectId - Persistent project identifier.
   * @param buildId - Build identifier belonging to the project.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract getBuild(projectId: string, buildId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot>
  /**
   * Request build cancellation; already-submitted provider work may continue.
   * @param projectId - Persistent project identifier.
   * @param buildId - Build identifier belonging to the project.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract cancelBuild(projectId: string, buildId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot>
  /**
   * Read a checkpoint or open the live planning snapshot when its id is live.
   * @param projectId - Persistent project identifier.
   * @param buildId - Build identifier belonging to the project.
   * @param checkpointId - Checkpoint identifier, or live for an editable planning snapshot.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract inspectCheckpoint(
    projectId: string,
    buildId: string,
    checkpointId: string,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<PlanCheckpoint>
  /**
   * Atomically append a revision-checked planning resolution.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract resolveCheckpoint(
    request: CheckpointResolutionRequest,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<BuildPlanSnapshot>
  /**
   * Request redelivery of a failed planning checkpoint.
   * @param projectId - Persistent project identifier.
   * @param buildId - Build identifier belonging to the project.
   * @param checkpointId - Checkpoint identifier, or live for an editable planning snapshot.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract retryCheckpoint(
    projectId: string,
    buildId: string,
    checkpointId: string,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<PlanCheckpoint>
  /**
   * Select an existing artifact version without generating new media.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract selectArtifact(
    request: ArtifactSelectionRequest,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<ArtifactSelectionResult>
  /**
   * Create an idempotent export request for the selected project version.
   * @param request - Structured request including idempotency and revision fields where required.
   * @param identity - Session and user attribution for Runtime authorization.
   * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
   * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
   */
  abstract exportProject(request: ExportRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ExportResult>
}

export default VideoRuntime
