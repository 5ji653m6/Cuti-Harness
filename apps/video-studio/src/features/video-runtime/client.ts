export interface RuntimeArtifact {
  id: string
  artifact_id: string
  type: string
  version: number
  status: string
  uri?: string
  title: string
  summary?: string
  metadata?: Record<string, unknown>
  created_at?: string
  logicalId?: string
  isSelected?: boolean
}

export interface RuntimeWorkspace {
  project: {
    id: string
    title: string
    status: string
    current_version_id: string
  }
  currentProjectVersion: Record<string, unknown> & { id: string; selections: Record<string, string> }
  videoSpec: Record<string, unknown> | null
  artifacts: RuntimeArtifact[]
  artifactGroups?: Record<string, RuntimeArtifact[]>
  artifactEdges?: RuntimeEdge[]
  builds: Array<BuildSnapshot & { steps: RuntimeBuildStep[]; validations: RuntimeValidation[]; checkpoints: RuntimeCheckpoint[] }>
  projectVersionCount?: number
  projectVersions?: Array<Record<string, unknown>>
  videoSpecRevision: RuntimeSpecRevision | null
  videoSpecRevisions?: RuntimeSpecRevision[]
  currentBuildPhase: string | null
  activeCheckpoint: RuntimeCheckpoint | null
  resolvedSections: string[]
  unresolvedSections: string[]
  planRevisions?: Array<Record<string, unknown>>
}

export interface RuntimeSpecRevision {
  id: string
  revision: number
  content: Record<string, unknown>
  resolved_sections: string[]
  unresolved_sections: string[]
  complete: boolean
}

export interface RuntimeCheckpoint {
  id: string
  phase: string
  next_phase: string
  status: 'pending' | 'planning' | 'resolved' | 'failed'
  artifact_summaries: Array<Record<string, unknown>>
  resolved_sections: string[]
  unresolved_sections: string[]
  delivery_attempts: number
  error?: string
}

export type VideoEdit =
  | { type: 'patch_character'; id: string; patch: Record<string, unknown> }
  | { type: 'patch_scene'; id: string; patch: Record<string, unknown> }
  | { type: 'patch_shot'; id: string; patch: Record<string, unknown> }
  | { type: 'regenerate_artifact'; artifactVersionId: string; patch?: Record<string, unknown> }
  | { type: 'replace_music'; prompt: string }
  | { type: 'generate_lipsync'; id?: string; patch?: Record<string, unknown> }
  | { type: 'patch_timeline'; id?: string; patch: Record<string, unknown> }

export interface RuntimeEdge {
  id: string
  source_version_id: string
  target_version_id: string
  relation: string
  invalidation_policy: 'hard' | 'validate' | 'soft' | 'none'
}

export interface RuntimeProject {
  projectId: string
  title: string
  status: string
  currentVersionId: string
  artifactCount: number
  activeBuildIds: string[]
  summary: string
  artifacts: RuntimeArtifact[]
  artifactEdges: RuntimeEdge[]
}

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

export interface BuildSnapshot {
  buildId: string
  projectId: string
  status: string
  progress: number
  message: string
  projectVersionId?: string
  kind?: 'initial' | 'incremental' | 'export'
  estimatedCost?: number
  actualCost?: number
  error?: string
}

export interface BuildPlanSnapshot {
  planId: string
  projectId: string
  kind: 'initial' | 'incremental' | 'export'
  status: string
  baseProjectVersionId: string
  workflowId: string
  videoSpec?: Record<string, unknown>
  projectIntent?: Record<string, unknown>
  shotCount: number
  schemaVersion: 1 | 2
  planRevision: number
  specRevisionId?: string
  currentPhase: string
  nextCheckpoint?: Record<string, unknown>
  estimatedCost: number
  steps: Array<Record<string, unknown>>
}

export interface RuntimeBuildStep {
  id: string
  build_id: string
  plan_step_id: string
  action: string
  capability: string
  status: string
  attempt: number
  result_artifact_version_id?: string
  error?: string
  resolved_skills?: Array<{
    skill_id: string
    version?: string | null
    content_hash?: string
    source?: string
  }>
}

export interface RuntimeValidation {
  id: string
  artifact_version_id?: string
  validator_id: string
  passed: boolean
  score?: number
  issues: string[]
}

export interface RuntimeVersion {
  id: string
  parentVersionId?: string
  timelineVersionId?: string
  artifactVersionIds: string[]
  isCurrent: boolean
  createdAt: string
}

export interface RuntimeExport {
  exportId: string
  projectId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  uri?: string
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/video${path}`, {
    credentials: 'include',
    ...init,
    headers: requestHeaders({ 'Content-Type': 'application/json' }, init.headers),
  })
  const payload = await response.json().catch(() => null) as { data?: T; detail?: string } | null
  if (!response.ok || payload?.data === undefined) {
    throw new Error(payload?.detail || `Video Runtime request failed (${response.status})`)
  }
  return payload.data
}

export const videoRuntimeClient = {
  createProject: (title: string) => request<RuntimeProject>('/projects', {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ title }),
  }),
  project: (projectId: string) => request<RuntimeProject>(`/projects/${encodeURIComponent(projectId)}`),
  workspace: (projectId: string) => request<RuntimeWorkspace>(
    `/projects/${encodeURIComponent(projectId)}/workspace`,
  ),
  versions: (projectId: string) => request<RuntimeVersion[]>(`/projects/${encodeURIComponent(projectId)}/versions`),
  preview: (projectId: string, change: string, targets: string[]) => request<ChangePreview>(
    `/projects/${encodeURIComponent(projectId)}/changes/preview`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ change, targetArtifactVersionIds: targets }),
    },
  ),
  previewEdits: (
    projectId: string,
    currentVersionId: string,
    edits: VideoEdit[],
    description = '',
  ) => request<BuildPlanSnapshot>(`/projects/${encodeURIComponent(projectId)}/edits/preview`, {
    method: 'POST',
    body: JSON.stringify({
      baseProjectVersionId: currentVersionId,
      idempotencyKey: crypto.randomUUID(),
      description,
      edits,
    }),
  }),
  applyEditPlan: (plan: BuildPlanSnapshot) => request<BuildSnapshot>(
    `/projects/${encodeURIComponent(plan.projectId)}/builds`,
    { method: 'POST', body: JSON.stringify({
      planId: plan.planId,
      baseProjectVersionId: plan.baseProjectVersionId,
      idempotencyKey: crypto.randomUUID(),
    }) },
  ),
  selectArtifact: (projectId: string, versionId: string, currentVersionId: string) => request<{
    projectId: string
    artifactId: string
    versionId: string
    projectVersionId: string
  }>(`/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(versionId)}/select`, {
    method: 'POST',
    body: JSON.stringify({ baseProjectVersionId: currentVersionId, idempotencyKey: crypto.randomUUID() }),
  }),
  rebuild: (preview: ChangePreview, idempotencyKey: string) => request<BuildSnapshot>(
    `/projects/${encodeURIComponent(preview.projectId)}/rebuilds`,
    { method: 'POST', body: JSON.stringify({
      planId: preview.planId,
      baseProjectVersionId: preview.baseProjectVersionId,
      idempotencyKey,
    }) },
  ),
  plan: (projectId: string, currentVersionId: string, videoSpec: Record<string, unknown>) => request<BuildPlanSnapshot>(
    `/projects/${encodeURIComponent(projectId)}/plans`,
    { method: 'POST', body: JSON.stringify({
      baseProjectVersionId: currentVersionId,
      idempotencyKey: crypto.randomUUID(),
      videoSpec,
    }) },
  ),
  startBuild: (plan: BuildPlanSnapshot) => request<BuildSnapshot>(
    `/projects/${encodeURIComponent(plan.projectId)}/builds`,
    { method: 'POST', body: JSON.stringify({
      planId: plan.planId,
      baseProjectVersionId: plan.baseProjectVersionId,
      idempotencyKey: crypto.randomUUID(),
    }) },
  ),
  build: (projectId: string, buildId: string) => request<BuildSnapshot>(
    `/projects/${encodeURIComponent(projectId)}/builds/${encodeURIComponent(buildId)}`,
  ),
  buildSteps: (projectId: string, buildId: string) => request<RuntimeBuildStep[]>(
    `/projects/${encodeURIComponent(projectId)}/builds/${encodeURIComponent(buildId)}/steps`,
  ),
  buildValidations: (projectId: string, buildId: string) => request<RuntimeValidation[]>(
    `/projects/${encodeURIComponent(projectId)}/builds/${encodeURIComponent(buildId)}/validations`,
  ),
  cancel: (projectId: string, buildId: string) => request<BuildSnapshot>(
    `/projects/${encodeURIComponent(projectId)}/builds/${encodeURIComponent(buildId)}/cancel`,
    { method: 'POST' },
  ),
  restore: (projectId: string, versionId: string, currentVersionId: string) => request<{ projectVersionId: string }>(
    `/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/restore`,
    { method: 'POST', body: JSON.stringify({
      baseProjectVersionId: currentVersionId,
      idempotencyKey: crypto.randomUUID(),
    }) },
  ),
  exportProject: (
    projectId: string,
    currentVersionId: string,
    format: 'mp4' | 'mov' | 'webm' | 'project' = 'mp4',
  ) => request<RuntimeExport>(`/projects/${encodeURIComponent(projectId)}/exports`, {
    method: 'POST',
    body: JSON.stringify({
      baseProjectVersionId: currentVersionId,
      idempotencyKey: crypto.randomUUID(),
      format,
    }),
  }),
}
import { requestHeaders } from '../../utils/requestHeaders'
