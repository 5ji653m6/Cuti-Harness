import type { SmartClipPayload } from './SmartClipPanel'

/** Fields consumed by the chat's media version and progress projections. */
export interface MediaVersion {
  id?: string | number
  uuid?: string
  version_number?: number
  frame_index?: number
  keyframe_url?: string
  video_url?: string
}

export interface MediaRecord {
  version_number?: number
  id?: string | number
  uuid?: string
  name?: string
  shot_number?: number
  frame_index?: number
  current_version_index?: number
  versions?: MediaVersion[]
}

export interface KeyframeData {
  keyframes?: MediaRecord[]
  total?: number
  shot_total?: number
}

export interface VideoData {
  video_generations?: MediaRecord[]
  total?: number
}

export interface CharacterData { characters?: MediaRecord[] }
export interface MusicData { music_generations?: unknown[]; _noMusic?: boolean }

export interface RegenerationItem {
  keyframe_uuid?: string
  character_uuid?: string
  video_uuid?: string
  new_version_uuid?: string
  keyframe_version_uuid?: string
  video_generation_uuid?: string
  video_generation_version_uuid?: string
  version_uuid?: string
  shot_number?: string | number
  frame_index?: number
}

export interface WorkflowPathEntry { id: string; label_key?: string; est_seconds?: number }

export interface InterruptData {
  [key: string]: unknown
  paused_intent_key?: string
  message_key?: string
  message_default?: string
  auto_resume_at?: string
  auto_continue_seconds?: number
  auto_resume_dismissed?: boolean
  available_agents?: string[]
  credit_estimate?: {
    remaining_credits_estimate?: number
    keyframe_credits_estimate?: number
    video_credits_estimate?: number
  }
  smart_clip?: SmartClipPayload
}

type UploadReference = string | { url: string; filename?: string }

export interface ChatEventData {
  waiting_input?: boolean
  action_suggestions?: unknown
  run_id?: string
  run_type?: string
  thread_id?: string
  message_id?: string | number
  message?: string
  status?: string
  stage?: string
  completed?: number
  total?: number
  continued?: boolean
  is_regenerate_task?: boolean
  todo_pending_user_input?: boolean
  auto_resume_dismissed?: boolean
  keyframe_completed?: number
  keyframe_total?: number
  keyframe_progress_percent?: number
  keyframe_reflection_completed?: number
  keyframe_reflection_total?: number
  keyframe_reflection_progress_percent?: number
  narration_completed?: number
  narration_total?: number
  progress_percent?: number
  completed_steps?: string[]
  path?: WorkflowPathEntry[]
  total_est_seconds?: number
  image_content?: string
  music_content?: string
  story_content?: string
  images?: UploadReference[]
  audio_files?: UploadReference[]
  video_files?: UploadReference[]
  interrupt_type?: string
  interrupt_data?: InterruptData
  failed_items?: Array<{ index?: number | string; shot_number?: number; frame_index?: number; reason?: string; message?: string }>
  interaction?: { payload?: { kind?: string; items?: RegenerationItem[]; propagate?: { items?: RegenerationItem[] } } }
}

export interface ChatMessage extends ChatEventData {
  id?: string | number
  role: string
  content: string
  timestamp?: string
  event_type?: string
  event_data?: ChatEventData
  message_id?: string | number
  run_id?: string
  interrupt_type?: string
  interrupt_data?: InterruptData
  isOptimistic?: boolean
}
