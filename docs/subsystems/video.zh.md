# Video Runtime

[English](video.md) | 中文

`ctx.videoRuntime` 是视频工具使用的项目 API。DeepSeek 负责 agent loop（智能体循环）；Python Runtime 负责持久项目版本、产物依赖、构建和规划检查点。[服务包](../../packages/video/video-runtime/README.zh.md) 定义消费方约定，[HTTP Provider](../../packages/video/video-runtime-http/README.zh.md) 定义传输配置。

## 请求与响应类型

[TypeScript 定义](../../packages/video/video-runtime/src/types.ts) 是可序列化字段的权威来源。`RequestIdentity` 提供用户／Session 归属信息，而非权限。`ProjectSnapshot` 和 `BuildSnapshot` 描述持久状态。`BuildPlanRequest`、`RebuildRequest`、`ArtifactSelectionRequest` 和 `ExportRequest` 携带幂等及基础版本值；过期编辑会被拒绝，不会应用到其他版本。

`WorkflowSummary`、`WorkflowDetail`、`SkillDetail` 和 `SkillResourceDetail` 提供已安装的指令、资源和可用性。`ChangePreview` 对依赖影响分类；`BuildPlanSnapshot` 包含持久步骤、费用和规划版本。`MediaArtifactSummary` 和 `CapabilityPromptView` 是规划发现结果。`PlanPatchPreviewRequest` 将操作绑定到产物输入，而非编造文件 URL。`PlanCheckpoint` 和 `CheckpointResolutionRequest` 在同一 Session 内协调带版本检查的续跑。

## 取消与持久化

中止 HTTP 请求不会撤销已接受的工作。取消构建必须显式请求；已提交的上游任务可能继续执行并产生费用。预览操作不会提交付费生成。执行和恢复语义见 [Runtime API 与调度参考](../../services/video-runtime/README.zh.md)。

<!-- BEGIN GENERATED cordis-surface (gen-cordis-catalog.ts) — do not edit between markers -->

<a id="cordis-surface"></a>

## Cordis API

Generated from source by `scripts/gen-cordis-catalog.ts` (verified fresh by `pnpm run verify-cordis-catalog` in doc-sync; regenerate with `pnpm run gen-cordis-catalog`) — the language sides differ only in locale-specific paired document paths. Signature blocks use a `ts cordis-catalog` fence and keep the original source JSDoc; dispatch modes are defined in the [primer](../cordis-primer.zh.md#dispatch-modes), and the framework-inherited `ctx` API lives in [cordis-api/inherited.md](../cordis-api/inherited.md).

<a id="ctxvideoruntime--videoruntime-abstract-seam"></a>

### `ctx.videoRuntime` — `VideoRuntime` (abstract seam)

Stable interface implemented by local or remote video project runtimes.

```ts cordis-catalog
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
abstract inspectCheckpoint( projectId: string, buildId: string, checkpointId: string, identity: RequestIdentity, signal?: AbortSignal, ): Promise<PlanCheckpoint>

/**
 * Atomically append a revision-checked planning resolution.
 * @param request - Structured request including idempotency and revision fields where required.
 * @param identity - Session and user attribution for Runtime authorization.
 * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
 * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
 */
abstract resolveCheckpoint( request: CheckpointResolutionRequest, identity: RequestIdentity, signal?: AbortSignal, ): Promise<BuildPlanSnapshot>

/**
 * Request redelivery of a failed planning checkpoint.
 * @param projectId - Persistent project identifier.
 * @param buildId - Build identifier belonging to the project.
 * @param checkpointId - Checkpoint identifier, or live for an editable planning snapshot.
 * @param identity - Session and user attribution for Runtime authorization.
 * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
 * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
 */
abstract retryCheckpoint( projectId: string, buildId: string, checkpointId: string, identity: RequestIdentity, signal?: AbortSignal, ): Promise<PlanCheckpoint>

/**
 * Select an existing artifact version without generating new media.
 * @param request - Structured request including idempotency and revision fields where required.
 * @param identity - Session and user attribution for Runtime authorization.
 * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
 * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
 */
abstract selectArtifact( request: ArtifactSelectionRequest, identity: RequestIdentity, signal?: AbortSignal, ): Promise<ArtifactSelectionResult>

/**
 * Create an idempotent export request for the selected project version.
 * @param request - Structured request including idempotency and revision fields where required.
 * @param identity - Session and user attribution for Runtime authorization.
 * @param signal - Optional cancellation signal for this request; abort does not undo remote work.
 * @returns Runtime response after validation; rejects on transport, authorization, or state errors.
 */
abstract exportProject(request: ExportRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ExportResult>
```

Source: [`packages/video/video-runtime/src/index.ts`](../../packages/video/video-runtime/src/index.ts)
<!-- END GENERATED cordis-surface -->
