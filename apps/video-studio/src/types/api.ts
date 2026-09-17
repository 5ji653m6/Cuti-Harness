// API 响应类型定义

// Imported Cuti response payloads remain heterogeneous during the Runtime migration.

type LegacyApiValue = unknown

/**
 * 统一响应格式 - CartoonBook Backend
 */
export interface ResponseModel<T> {
  code: number  // 0 表示成功，其他表示错误
  message: string
  data: T
}

/**
 * 用户信息
 */
export interface User {
  user_id: string
  email?: string
  is_admin?: boolean
}

/**
 * 对话信息
 */
export interface Conversation {
  id: number
  user_id: string
  thread_id: string
  title: string
  created_at: string
  updated_at: string
  last_active_at: string
  is_active: boolean
  message_count: number
  preview?: string
  /** 用户输入的图片 URL，用于对话列表缩略图展示 */
  preview_image_url?: string
  agent_type?: string  // 添加 agent_type 字段：'storybook' | 'video' | 'chat' 等
  /** 对话/任务语言偏好（ISO 639-1），用于新建任务时沿用 */
  language?: string
  /** 创建会话时首次提交的 user_option（JSON）；可能与最近一次 run 不同。含与后端 UserOption 一致字段，含 full_auto（完全托管） */
  user_option?: Record<string, unknown>
  task_status?: {  // 新增：当前任务状态
    run_id: string
    status: string
    progress?: number
    step?: string
  }
}

/**
 * 对话列表响应
 */
export interface ConversationListResponse {
  conversations: Conversation[]
  page: number
  size: number
  total: number
}

/**
 * 消息信息
 */
export interface Message {
  id: number
  conversation_id: number
  role: string  // "human" | "ai" | "system"
  content: string
  created_at: string
  sequence: number
  metadata?: Record<string, LegacyApiValue>
  event_type?: string
  event_data?: StreamEvent
}

/**
 * 任务状态枚举 - 与后端 TaskStatus 对齐
 */
export enum TaskStatus {
  QUEUED = 'queued',             // 队列中
  RESUME_QUEUED = 'resume_queued', // resume 已入队，等待 worker 拉取
  RUNNING = 'running',           // 运行中
  COMPLETED = 'completed',       // 已完成
  FAILED = 'failed',             // 失败
  CANCELLED = 'cancelled',       // 已取消
  INTERRUPTED = 'interrupted',    // 已暂停（等待用户点击继续）
}

/**
 * 任务信息（run 维度，一个对话下可有多个 run）
 */
export interface Task {
  run_id: string
  thread_id?: string
  status: TaskStatus
  /** 与后端 RunType 对齐：main | resume | regenerate_keyframes | regenerate_videos | regenerate_characters */
  run_type?: string
  agent_type?: string  // 与后端 AgentType 对齐：video | story | music | image | clarify | auto 等
  progress?: number
  current_step?: string
  created_at?: string
  updated_at?: string
  completed_at?: string
  error_message?: string
  /** 该任务的语言偏好（ISO 639-1） */
  language?: string
  /** 该次 run 提交时的 user_option 快照（含 full_auto 等与后端 UserOption 对齐的字段） */
  user_option?: Record<string, unknown>
}

/**
 * 对话详情响应
 */
export interface ConversationDetailResponse {
  conversation: Conversation
  messages: Message[]
  tasks?: Task[]  // 新增：所有任务列表
  /** 最近一次 run（created_at DESC）带有的 user_option，用于恢复右侧面板（含 full_auto） */
  latest_user_option?: Record<string, unknown>
}

/**
 * 流式事件类型
 */
export interface StreamEvent {
  type: string
  message?: string
  timestamp: string
  thread_id?: string
  conversation_id?: number
  run_id?: string

  // 不同事件类型的特定数据
  [key: string]: LegacyApiValue
}

// video_gen（单模型直生）结构化视频项，由 video_agent_generated 事件的 event_data.videos[] 携带。
// 仅暴露前端播放所需最小字段，不下发 model / prompt / 分辨率等内部信息。
export interface GeneratedVideoItem {
  index: number
  video_url: string
  cover_image_url?: string | null
}

/**
 * 用户选项
 */
export interface UserOption {
  // 图像生成工具
  image_generation_tool?: 'nano_banana' | 'nano_banana_2' | 'nano_banana_pro' | 'seedream' | 'gpt_image_2'

  // 视频生成工具
  video_generation_tool?:
    | 'auto'
    | 'pollo_seedance'
    | 'pollo_seedance_v1_5'
    | 'seedance_2_i2v'
    | 'seedance_2_i2v_turbo'
    | 'seedance_2_fast_i2v'
    | 'seedance_2_fast_i2v_turbo'
    | 'wan_2_5'
    | 'wan_2_6_flash'
    | 'kling_v3_std'
    | 'happyhorse_1_0_i2v'
    | 'happyhorse_1_1_i2v'
    | 'openai_sora'
    | 'openai_sora_pro'

  /** 口型镜头视频模型（与后端 lipsync_video_tool 一致；不在 UI 提供 wan_2_5） */
  lipsync_video_tool?:
    | 'auto'
    | 'ltx_2_3'
    | 'kling_v2_ai_avatar_pro'
    | 'wan_2_2_speech_to_video'
    | 'wan_2_6_flash'

  // 视频生成模式
  mode?: 'instant' | 'master'

  // 视频宽高比
  aspect_ratio?: '16:9' | '1:1' | '9:16'

  // 视频分辨率
  resolution?: '480p' | '720p' | '1080p'

  // 视频时长（秒），范围5-300
  duration?: number

  // 唇形同步覆盖率百分比：0=关闭, 10/20/30...=覆盖比例
  lipsync_coverage?: number

  // 是否启用连续模式（所有帧从头到尾保持连续连接）
  enable_continuity_mode?: boolean
  // 是否启用关键帧反思（生成后 AI 检查角色一致性并自动优化不满意的画面）
  enable_keyframe_reflection?: boolean

  /** 暂停点是否自动继续（与后端 full_auto 一致） */
  full_auto?: boolean
}

/**
 * 取消任务请求
 */
export interface CancelTaskRequest {
  thread_id: string
}

/**
 * 取消任务响应
 */
export interface CancelTaskResponse {
  thread_id: string
  cancelled: boolean
}

/**
 * 运行中任务
 */
export interface RunningTask {
  thread_id: string
  user_id: string
  status: string
  started_at: string
  conversation_id?: number
}

/**
 * 运行中任务列表响应
 */
export interface RunningTasksResponse {
  running_tasks: RunningTask[]
  count: number
}

/**
 * 工具信息
 */
export interface ToolInfo {
  tool_id: string
  name: string
  description: string
  category: string
  is_available: boolean
  enum_value: string
}


export interface CharacterUploadImage {
  image_data: string
  filename: string
}

export interface CharacterUploadRequest {
  character_name: string
  images: CharacterUploadImage[]
  parent_folder_id?: number | null
  additional_data?: string
}

export interface Character {
  id: number
  uuid: string
  user_id: string
  character_name: string
  url: string
  filename: string
  folder_id: number
  additional_data?: string
  created_at: string
  updated_at: string
  is_deleted: boolean
}

export interface CharacterUploadResponse {
  folder_id: number
  folder_name: string
  characters: Character[]
  total: number
  failed: number
}
