export interface StudioRun {
  id: string
  thread_id: string
  objective: string
  status: string
}

export interface StudioTask {
  id: string
  capability_id?: string
  objective?: string
  status?: string
  depends_on?: string[]
}

export interface StudioArtifact {
  id: string
  artifact_type?: string
  status?: string
  version?: number
  metadata?: Record<string, unknown>
}

export interface StudioSnapshot {
  run?: StudioRun
  tasks?: StudioTask[]
  artifacts?: StudioArtifact[]
  selections?: Array<{ artifact_type?: string; artifact_version_id?: string }>
}

export interface StudioPlanItem {
  operation?: string
  task_id?: string
  capability_id?: string
  objective?: string
}

interface ResponseModel<T> {
  code: number
  message: string
  data: T
}

const STUDIO_BASE_URL = '/chat-v1/service/studio'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${STUDIO_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: requestHeaders({
      'Content-Type': 'application/json',
      'X-App-Language': localStorage.getItem('language') || 'zh',
    }, init.headers),
  })
  const payload = await response.json().catch(() => null) as ResponseModel<T> | { detail?: string } | null
  if (!response.ok || !payload || !('data' in payload) || payload.code !== 0) {
    const message = payload && 'detail' in payload
      ? payload.detail
      : payload && 'message' in payload
        ? payload.message
        : `Studio request failed (${response.status})`
    throw new Error(message || `Studio request failed (${response.status})`)
  }
  return payload.data
}

export const studioClient = {
  createProject: (objective: string) => request<{ project: StudioRun; suggested_plan: StudioPlanItem[] }>('/projects', {
    method: 'POST',
    body: JSON.stringify({ objective }),
  }),
  getProject: (threadId: string) => request<StudioSnapshot>(`/projects/${encodeURIComponent(threadId)}`),
  sendCommand: (threadId: string, objective: string) => request<{ project: StudioRun; suggested_plan: StudioPlanItem[] }>(
    `/projects/${encodeURIComponent(threadId)}/commands`,
    { method: 'POST', body: JSON.stringify({ objective }) },
  ),
  selectArtifact: (threadId: string, artifactId: string) => request<unknown>(
    `/projects/${encodeURIComponent(threadId)}/artifacts/${encodeURIComponent(artifactId)}/select`,
    { method: 'POST' },
  ),
  listSkills: () => request<Array<Record<string, unknown>>>('/skills'),
}
import { requestHeaders } from '../../utils/requestHeaders'
