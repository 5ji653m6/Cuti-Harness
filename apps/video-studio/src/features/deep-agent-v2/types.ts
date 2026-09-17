import type { ActionSuggestionItem } from '@/utils/actionSuggestions'

export type DeepAgentRunStatus =
  | 'planning'
  | 'running'
  | 'waiting_external'
  | 'waiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type DeepAgentTaskStatus =
  | 'proposed'
  | 'blocked'
  | 'ready'
  | 'running'
  | 'waiting_external'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface DeepAgentSkill {
  name: string
  description: string
  trust_level: string
  enabled: boolean
  capability_id?: string | null
  bundle_digest?: string | null
  installed_at?: string | null
  metadata?: Record<string, unknown>
  kind?: string | null
  available?: boolean
  unavailable_reason?: string | null
  workflow_mode?: string | null
}

export interface DeepAgentSkillLock {
  project_id: string
  skill_id: string
  version: string
  digest: string
  source: string
  enabled: boolean
}

export interface DeepAgentRun {
  id: string
  thread_id: string
  project_id: string
  title: string
  objective: string
  status: DeepAgentRunStatus
  current_revision: number
  last_response: string
  output_language?: 'zh' | 'en'
  language_contract?: {
    ui_locale: 'zh-CN' | 'en-US'
    content_language: 'zh-CN' | 'en-US'
    spoken_language: 'zh-CN' | 'en-US'
    subtitle_language: 'zh-CN' | 'en-US'
    provider_prompt_language: 'auto' | 'zh-CN' | 'en-US'
  } | null
  user_option?: Record<string, unknown> | null
  input_files?: DeepAgentInputFile[]
  automatic_video?: boolean
  planning_off?: boolean
  code_video_mode?: boolean
  skill_locks?: DeepAgentSkillLock[]
  created_at: string
  updated_at: string
}

export type DeepAgentRunSummary = Pick<
  DeepAgentRun,
  | 'id'
  | 'thread_id'
  | 'project_id'
  | 'title'
  | 'status'
  | 'last_response'
  | 'created_at'
  | 'updated_at'
>

export interface DeepAgentTask {
  id: string
  run_id: string
  revision: number
  capability_id: string
  objective: string
  input_artifact_version_ids: string[]
  depends_on: string[]
  status: DeepAgentTaskStatus
  remote_operation_id?: string | null
  remote_thread_id?: string | null
  error?: string | null
  progress?: number
  progress_message?: string
  resolved_skills?: Array<{
    skill_id: string
    version?: string | null
    content_hash?: string
    source?: string
  }>
  created_at: string
  updated_at: string
}

export interface DeepAgentArtifact {
  id: string
  artifact_id: string
  project_id: string
  type: string
  version: number
  status: string
  produced_by_task_id: string
  title: string
  summary: string
  uri?: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface DeepAgentSelection {
  project_id: string
  type: string
  artifact_version_id: string
  updated_at: string
}

export interface DeepAgentMessage {
  id: string
  run_id: string
  role: string
  content: string
  sequence?: number
  metadata?: Record<string, unknown>
  created_at: string
  event_type?: string
  event_data?: Record<string, unknown>
}

export interface DeepAgentInputFile {
  type: string
  url: string
  artifact_id?: string
  filename?: string | null
  metadata: Record<string, unknown>
}

export interface DeepAgentMessageOptions {
  thread_id?: string
  user_option?: Record<string, unknown>
  input_files?: DeepAgentInputFile[]
  workflow_id?: string
  activated_skill_ids?: string[]
  automatic_video?: boolean
  planning_off?: boolean
  code_video_mode?: boolean
}

export interface DeepAgentRuntimeOptions {
  wavespeed_configured: boolean
  default_code_video_mode: boolean
}

export interface DeepAgentEvent {
  id: string
  run_id: string
  sequence: number
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface DeepAgentSnapshot {
  run: DeepAgentRun
  revisions: unknown[]
  tasks: DeepAgentTask[]
  artifacts: DeepAgentArtifact[]
  selections: DeepAgentSelection[]
  messages: DeepAgentMessage[]
  events?: DeepAgentEvent[]
  has_more_events?: boolean
  last_event_sequence?: number
}

export interface DeepAgentTokenUsage {
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  reasoning_tokens: number
  total_tokens: number
  requested_tokens: number
  calls: number
  failed_calls: number
  retry_attempts: number
  by_scope: Record<string, { calls: number; input_tokens: number; output_tokens: number; total_tokens: number }>
  by_task: Array<{
    task_id: string
    capability_id?: string
    calls: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
  }>
  records: Array<Record<string, unknown>>
  attempt_records: Array<Record<string, unknown>>
}

export interface DeepAgentSuggestion extends ActionSuggestionItem {
  generation_input?: Record<string, unknown>
}

export type DeepAgentNoticeSeverity = 'error' | 'warning' | 'info'

/** User-facing banner. Only terminal failures use severity "error". */
export interface DeepAgentNotice {
  message: string
  severity: DeepAgentNoticeSeverity
  whatHappened?: string
  whyInterrupted?: string
  whyConfirm?: string
  confirmationRequired?: boolean
  interruptCategory?: string
  skillName?: string
  skillResource?: string
  skillPolicy?: string
  capabilityId?: string
  taskId?: string
  stage?: string
  willAutoResume?: boolean
  autoResumeSeconds?: number
}

export interface DeepAgentWorkspaceState {
  runs: DeepAgentRunSummary[]
  selectedRunId: string | null
  snapshot: DeepAgentSnapshot | null
  messages: DeepAgentMessage[]
  traceEvents: DeepAgentEvent[]
  suggestions: DeepAgentSuggestion[]
  lastSequence: number
  seenEventIds: string[]
  isLoadingRuns: boolean
  isHydrating: boolean
  isStreaming: boolean
  isSending: boolean
  notice: DeepAgentNotice | null
}
