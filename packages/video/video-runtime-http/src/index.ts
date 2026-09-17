/** HTTP implementation of `ctx.videoRuntime`. @module @cuti-ai/video-runtime-http */

import { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { VideoRuntime } from '@cuti-ai/video-runtime'
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
} from '@cuti-ai/video-runtime'

/** Connection and request bounds for the Python Video Runtime HTTP provider. */
export interface Config {
  /** Runtime origin, without a project-specific API path. */
  baseUrl: string
  /** Optional service credential sent with Runtime requests. */
  serviceToken?: string
  /** Default user attribution when a request supplies none. */
  userId?: string
  /** Per-request timeout in milliseconds; defaults to 30000. */
  timeoutMs?: number
}

export const Config: z<Config> = z.object({
  baseUrl: z.string().required(),
  serviceToken: z.string(),
  userId: z.string(),
  timeoutMs: z.number().default(30_000),
})

interface RuntimeEnvelope<T> {
  data: T
}

function projectSnapshot(value: ProjectSnapshot): ProjectSnapshot {
  return {
    projectId: value.projectId,
    title: value.title,
    status: value.status,
    currentVersionId: value.currentVersionId,
    artifactCount: value.artifactCount,
    activeBuildIds: value.activeBuildIds,
    summary: value.summary,
  }
}

/** Remote Video Runtime provider with bounded requests and explicit identity headers. */
export class HttpVideoRuntime extends VideoRuntime {
  static Config = Config
  private readonly baseUrl: string
  private readonly serviceToken: string | undefined
  private readonly userId: string | undefined
  private readonly timeoutMs: number

  constructor(ctx: Context, config: Config) {
    super(ctx)
    this.baseUrl = config.baseUrl.replace(/\/+$/, '')
    this.serviceToken = config.serviceToken
    this.userId = config.userId
    this.timeoutMs = config.timeoutMs ?? 30_000
    if (!/^https?:\/\//.test(this.baseUrl)) throw new Error('video-runtime-http: baseUrl must use http or https')
    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs <= 0) {
      throw new Error('video-runtime-http: timeoutMs must be a positive integer')
    }
  }

  createProject(request: CreateProjectRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot> {
    return this.request('/api/video/projects', identity, {
      method: 'POST', body: { title: request.title, sessionId: identity.sessionId }, signal,
      extraHeaders: { 'Idempotency-Key': request.idempotencyKey },
    })
  }

  async openProject(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot> {
    const snapshot = await this.request<ProjectSnapshot>(
      `/api/video/projects/${encodeURIComponent(projectId)}`,
      identity,
      { signal },
    )
    // The project endpoint also serves Studio-only artifact and dependency
    // details. Keep those out of the strict model-facing tool contract.
    return projectSnapshot(snapshot)
  }

  inspectProject(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<ProjectSnapshot> {
    return this.openProject(projectId, identity, signal)
  }

  listWorkflows(identity: RequestIdentity, signal?: AbortSignal): Promise<WorkflowSummary[]> {
    return this.request('/api/video/workflows', identity, { signal })
  }

  loadWorkflow(workflowId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<WorkflowDetail> {
    return this.request(`/api/video/workflows/${encodeURIComponent(workflowId)}`, identity, { signal })
  }

  loadSkill(skillId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<SkillDetail> {
    return this.request(`/api/video/skills/${encodeURIComponent(skillId)}`, identity, { signal })
  }

  loadSkillResource(skillId: string, path: string, identity: RequestIdentity, signal?: AbortSignal): Promise<SkillResourceDetail> {
    const query = new URLSearchParams({ path }).toString()
    return this.request(`/api/video/skills/${encodeURIComponent(skillId)}/resources?${query}`, identity, { signal })
  }

  previewChange(request: ChangePreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ChangePreview> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/changes/preview`, identity, {
      method: 'POST', body: request, signal,
      extraHeaders: { 'Idempotency-Key': request.idempotencyKey },
    })
  }

  previewEdits(request: EditPreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/edits/preview`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  listArtifacts(projectId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<MediaArtifactSummary[]> {
    return this.request(`/api/video/projects/${encodeURIComponent(projectId)}/artifacts`, identity, { signal })
  }

  listPlanPatchCapabilities(identity: RequestIdentity, signal?: AbortSignal): Promise<CapabilityPromptView[]> {
    return this.request('/api/video/plan-patch-capabilities', identity, { signal })
  }

  previewPlanPatch(request: PlanPatchPreviewRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/plan-patches/preview`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  planProject(request: BuildPlanRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/plans`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  startBuild(request: RebuildRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/builds`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  applyRebuild(request: RebuildRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/rebuilds`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  getBuild(projectId: string, buildId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(projectId)}/rebuilds/${encodeURIComponent(buildId)}`, identity, { signal })
  }

  cancelBuild(projectId: string, buildId: string, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(projectId)}/rebuilds/${encodeURIComponent(buildId)}/cancel`, identity, {
      method: 'POST', signal,
    })
  }

  inspectCheckpoint(
    projectId: string,
    buildId: string,
    checkpointId: string,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<PlanCheckpoint> {
    const path = `/api/video/projects/${encodeURIComponent(projectId)}`
      + `/builds/${encodeURIComponent(buildId)}/checkpoints/${encodeURIComponent(checkpointId)}`
    return this.request(path, identity, { signal, method: checkpointId === 'live' ? 'POST' : 'GET' })
  }

  resolveCheckpoint(request: CheckpointResolutionRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<BuildPlanSnapshot> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/builds/${encodeURIComponent(request.buildId)}/checkpoints/${encodeURIComponent(request.checkpointId)}/resolve`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  retryCheckpoint(
    projectId: string,
    buildId: string,
    checkpointId: string,
    identity: RequestIdentity,
    signal?: AbortSignal,
  ): Promise<PlanCheckpoint> {
    const path = `/api/video/projects/${encodeURIComponent(projectId)}`
      + `/builds/${encodeURIComponent(buildId)}/checkpoints/${encodeURIComponent(checkpointId)}/retry`
    return this.request(path, identity, {
      method: 'POST', signal,
    })
  }

  selectArtifact(request: ArtifactSelectionRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ArtifactSelectionResult> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/artifacts/${encodeURIComponent(request.versionId)}/select`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  exportProject(request: ExportRequest, identity: RequestIdentity, signal?: AbortSignal): Promise<ExportResult> {
    return this.request(`/api/video/projects/${encodeURIComponent(request.projectId)}/exports`, identity, {
      method: 'POST', body: request, signal,
    })
  }

  private async request<T>(path: string, identity: RequestIdentity, options: {
    method?: 'GET' | 'POST'
    body?: object | undefined
    signal?: AbortSignal | undefined
    extraHeaders?: Record<string, string> | undefined
  }): Promise<T> {
    options.signal?.throwIfAborted()
    const timeout = AbortSignal.timeout(this.timeoutMs)
    const combined = options.signal === undefined ? timeout : AbortSignal.any([options.signal, timeout])
    const headers = new Headers({ Accept: 'application/json' })
    if (options.body !== undefined) headers.set('Content-Type', 'application/json')
    if (this.serviceToken !== undefined) headers.set('Authorization', `Bearer ${this.serviceToken}`)
    if (identity.sessionId !== undefined) headers.set('X-Video-Session-Id', identity.sessionId)
    for (const [name, value] of Object.entries(options.extraHeaders ?? {})) headers.set(name, value)
    const userId = identity.userId ?? this.userId
    if (userId !== undefined) headers.set('X-Video-User-Id', userId)
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: options.method ?? 'GET',
      headers,
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      signal: combined,
    })
    const payload: unknown = await response.json().catch(() => undefined)
    if (!response.ok) {
      const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
        ? (typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail))
        : `HTTP ${response.status}`
      throw new Error(`video runtime request failed (HTTP ${response.status}): ${detail}`)
    }
    if (typeof payload !== 'object' || payload === null || !('data' in payload)) {
      throw new Error('video runtime returned an invalid response envelope')
    }
    return (payload as RuntimeEnvelope<T>).data
  }
}

export default HttpVideoRuntime
