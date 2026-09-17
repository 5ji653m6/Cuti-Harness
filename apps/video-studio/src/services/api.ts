/**
 * Local agent API clients (Video Runtime / DeepSeek workspace).
 */

import type {
  ResponseModel,
  CancelTaskResponse,
  RunningTasksResponse,
  UserOption,
} from '../types/api'

// Imported Cuti endpoints have heterogeneous responses until each legacy API is retired.

type LegacyApiValue = unknown

// API 基础配置
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
export const CUTI_VIDEO_API_BASE_URL = '/api/cv-v1'
// VideoChatAgent（与 main FastAPI 网关同域时走 /chat-v1/service；本地见 vite proxy）
export const VIDEOCHAT_AGENT_SERVICE_PREFIX = '/chat-v1/service'
export const AGENT_ROUTER_SUBMIT_URL = `${VIDEOCHAT_AGENT_SERVICE_PREFIX}/agent-router/stream`
const AGENT_ROUTER_SERVICE_HEALTH_URL = `${VIDEOCHAT_AGENT_SERVICE_PREFIX}/health`
// 本地 dev 探测端口：launch.json 里 [Video Stack] VideoChatAgent 用 SERVER_PORT=9014 避开同机其他人占用的 9004。
// 这里变量名保留 9004 后缀只是历史习惯（避免大面积改名），实际端口以 launch.json SERVER_PORT 为准。
const LOCAL_9004_GATEWAY_BASE_URL = 'http://localhost:9014'
const LOCAL_9004_AGENT_ROUTER_SUBMIT_URL = `${LOCAL_9004_GATEWAY_BASE_URL}${AGENT_ROUTER_SUBMIT_URL}`
const LOCAL_9004_HEALTH_CHECK_URL = `${LOCAL_9004_GATEWAY_BASE_URL}${AGENT_ROUTER_SERVICE_HEALTH_URL}`

let _agentRouterSubmitUrlCache: string | null = null
let _agentRouterSubmitProbePromise: Promise<string> | null = null

const isLocalDevHttpRuntime = (): boolean => {
  if (typeof window === 'undefined') return false
  return (
    window.location.protocol === 'http:' &&
    ['localhost', '127.0.0.1', '0.0.0.0'].includes(window.location.hostname)
  )
}

const probeAgentRouterSubmitUrl = async (): Promise<string> => {
  if (!isLocalDevHttpRuntime()) {
    return AGENT_ROUTER_SUBMIT_URL
  }

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() =>{  controller.abort() }, 1200)
  const currentLang = localStorage.getItem('language') || 'en'

  try {
    const healthResp = await fetch(LOCAL_9004_HEALTH_CHECK_URL, {
      method: 'GET',
      credentials: 'include',
      headers: {
        'X-App-Language': currentLang,
      },
      signal: controller.signal,
    })
    if (healthResp.ok) {
      console.log('🌐 [API] Detected local 9004 service, using:', LOCAL_9004_AGENT_ROUTER_SUBMIT_URL)
      return LOCAL_9004_AGENT_ROUTER_SUBMIT_URL
    }
  } catch (error) {
    console.warn('🌐 [API] local 9004 probe failed, fallback to default submit URL:', error)
  } finally {
    window.clearTimeout(timeoutId)
  }

  return AGENT_ROUTER_SUBMIT_URL
}

const resolveAgentRouterSubmitUrl = async (): Promise<string> => {
  if (_agentRouterSubmitUrlCache) {
    return _agentRouterSubmitUrlCache
  }
  if (_agentRouterSubmitProbePromise) {
    return _agentRouterSubmitProbePromise
  }

  _agentRouterSubmitProbePromise = probeAgentRouterSubmitUrl()
    .then((resolvedUrl) => {
      _agentRouterSubmitUrlCache = resolvedUrl
      return resolvedUrl
    })
    .finally(() => {
      _agentRouterSubmitProbePromise = null
    })

  return _agentRouterSubmitProbePromise
}

export interface AgentSubmitTaskResult {
  code: number
  message: string
  data: {
    run_id?: string
    thread_id?: string
    conversation_id?: number
    status?: string
    message?: string
    ignored?: boolean
  }
  stream?: ReadableStream<Uint8Array>
  directStream?: boolean
}

/** API 业务错误（code !== 0），便于前端按错误码做 i18n */
export class ApiBusinessError extends Error {
  readonly code: number

  constructor(code: number, message: string) {
    super(message)
    this.name = 'ApiBusinessError'
    this.code = code
  }
}


// submitTask 请求去重：同一 thread_id 的并发 POST 只发送一次
const _submitTaskPending = new Map<string, Promise<AgentSubmitTaskResult>>()

/** Validate the shared API envelope; each endpoint supplies its payload type. */
async function readApiResponse<T>(response: Response): Promise<ResponseModel<T>> {
  const value: unknown = await response.json()
  if (typeof value !== 'object' || value === null || !('code' in value) || typeof value.code !== 'number'
    || !('message' in value) || typeof value.message !== 'string') {
    throw new Error('Invalid API response envelope')
  }
  if (value.code !== 0) throw new ApiBusinessError(value.code, value.message || 'Request failed')
  if (!('data' in value)) throw new Error('API response is missing data')
  return { code: value.code, message: value.message, data: value.data as T }
}
/** 当前进行中的 submitTask POST（directStream SSE） */
let _activeSubmitAbortController: AbortController | null = null
let _activeSubmitDedupeKey: string | null = null

/**
 * 通用请求函数
 */
async function makeRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  baseUrl: string = API_BASE_URL,
): Promise<ResponseModel<T>> {
  // 开发环境：使用相对路径，走 Vite 代理（解决跨域 cookie 问题）
  // 生产环境：使用空字符串，因为前后端在同一域名下
  const url = `${baseUrl}${endpoint}`
  // const url = import.meta.env.DEV ? `${baseUrl}${endpoint}` : `${baseUrl}${endpoint}`;
  const currentLang = localStorage.getItem('language') || 'en'
  const defaultOptions: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      'X-App-Language': currentLang, // 注入自定义语言 Header
    },
    credentials: 'include', // 重要：包含 cookies
    ...options,
  }

  try {
    const response = await fetch(url, defaultOptions)

    // 解析响应
    const result = await readApiResponse<T>(response)

    // 检查业务逻辑错误
    if (result.code !== 0) {
      throw new ApiBusinessError(result.code, result.message || 'API request failed')
    }

    return result
  } catch (error) {
    console.error(`API request failed: ${url}`, error)
    throw error
  }
}

/**
 * Agent 对话相关 API
 */
export const agentApi = {
  /**
   * 提交任务（新：返回任务信息，不再是流式响应）
   */
  async submitTask(data: {
    userInput?: string
    files?: File[]
    threadId?: string
    conversationId?: number
    userOption?: UserOption
    agentType?: string
    hasConfirmed?: boolean
    confirmedInputSummary?: string
    generationInput?: string
    originalUserInput?: string
    preferPanelUserOption?: boolean
    /** resume 时传 JSON：{"run_id":"...","interrupt_msgid":123}，此时可不传 userInput */
    resumeData?: string
    /** 为 true 时后端拒绝无 conversation_id/thread_id 的请求，防止误开新会话（续聊场景） */
    requireConversationContext?: boolean
  }): Promise<AgentSubmitTaskResult> {
    const dedupeKey = data.threadId

    // 如果同一 thread_id 已有请求在途中，直接复用那个 Promise，不再发第二次 POST
    if (dedupeKey && _submitTaskPending.has(dedupeKey)) {
      console.warn('[submitTask] Duplicate request for thread:', dedupeKey, '- reusing in-flight promise')
      const pending = _submitTaskPending.get(dedupeKey)
      if (pending) return pending
    }

    // 将 fetch 逻辑包在 IIFE 里，得到一个普通 Promise
    // 必须在任何 await 之前把 promise 注册到 Map，保证后续同步调用能命中去重逻辑
    const submitDedupeKey = dedupeKey || `ephemeral:${Date.now()}:${Math.random().toString(36).slice(2, 9)}`

    const promise = (async () => {
      if (_activeSubmitAbortController) {
        _activeSubmitAbortController.abort()
      }
      const submitAbortController = new AbortController()
      _activeSubmitAbortController = submitAbortController
      _activeSubmitDedupeKey = submitDedupeKey

      const formData = new FormData()
      const isVideoResume = !!data.resumeData && data.resumeData.trim().startsWith('{')
      formData.append('user_input', isVideoResume ? '' : (data.userInput ?? ''))

      if (data.threadId) {
        formData.append('thread_id', data.threadId)
      }

      if (data.conversationId) {
        formData.append('conversation_id', data.conversationId.toString())
      }

      if (data.userOption) {
        formData.append('user_option', JSON.stringify(data.userOption))
      }

      if (data.agentType) {
        formData.append('agent_type', data.agentType)
      }

      if (typeof data.hasConfirmed === 'boolean') {
        formData.append('has_confirmed', String(data.hasConfirmed))
      }

      if (data.confirmedInputSummary) {
        formData.append('confirmed_input_summary', data.confirmedInputSummary)
      }

      if (data.generationInput) {
        formData.append('generation_input', data.generationInput)
      }

      if (data.originalUserInput) {
        formData.append('original_user_input', data.originalUserInput)
      }

      if (data.preferPanelUserOption === true) {
        formData.append('prefer_panel_user_option', 'true')
      }

      if (data.resumeData) {
        formData.append('resume_data', data.resumeData)
      }

      if (data.requireConversationContext === true) {
        formData.append('require_conversation_context', 'true')
      }

      // 添加文件
      if (data.files && data.files.length > 0) {
        data.files.forEach((file) => {
          formData.append('files', file)
        })
      }

      const currentLang = localStorage.getItem('language') || 'en'
      const submitUrl = await resolveAgentRouterSubmitUrl()
      const buildSubmitRequestInit = (): RequestInit => ({
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          'X-App-Language': currentLang,
          'Accept': 'text/event-stream',
        },
        signal: submitAbortController.signal,
      })

      let response: Response
      try {
        response = await fetch(submitUrl, buildSubmitRequestInit())
      } catch (error) {
        if (submitAbortController.signal.aborted) {
          throw error
        }
        if (submitUrl !== AGENT_ROUTER_SUBMIT_URL) {
          console.warn('🌐 [API] submit via local 9004 failed, retry default submit URL')
          _agentRouterSubmitUrlCache = AGENT_ROUTER_SUBMIT_URL
          response = await fetch(AGENT_ROUTER_SUBMIT_URL, buildSubmitRequestInit())
        } else {
          throw error
        }
      }

      if (!response.ok && submitUrl !== AGENT_ROUTER_SUBMIT_URL && !submitAbortController.signal.aborted) {
        console.warn(`🌐 [API] submit via local 9004 got status ${response.status}, retry default submit URL`)
        _agentRouterSubmitUrlCache = AGENT_ROUTER_SUBMIT_URL
        response = await fetch(AGENT_ROUTER_SUBMIT_URL, buildSubmitRequestInit())
      }

      if (!response.ok) {
        let errorMessage = `HTTP error! status: ${response.status}`
        try {
          const contentType = (response.headers.get('content-type') || '').toLowerCase()
          if (contentType.includes('application/json')) {
            const result: unknown = await response.json()
            if (typeof result === 'object' && result !== null) {
              const fields = result as Record<string, unknown>
              const detail = [fields.message, fields.detail, fields.error].find(value => typeof value === 'string' && value)
              if (typeof detail === 'string') errorMessage = detail
            }
          } else {
            const text = await response.text()
            errorMessage = text || errorMessage
          }
        } catch {
          /* keep status fallback */
        }
        throw new Error(errorMessage)
      }

      const contentType = (response.headers.get('content-type') || '').toLowerCase()
      if (!contentType.includes('application/json')) {
        if (!response.body) {
          throw new Error('Response body is null')
        }
        return {
          code: 0,
          message: 'direct stream',
          data: {},
          stream: response.body,
          directStream: true,
        } as AgentSubmitTaskResult
      }

      const result = await readApiResponse<AgentSubmitTaskResult['data']>(response)
      if (result.code !== 0) {
        throw new Error(result.message || 'Request failed')
      }

      return result as AgentSubmitTaskResult
    })()

    // 同步注册（在 IIFE 第一个 await 之前），确保并发的第二次调用能命中去重检查
    _submitTaskPending.set(submitDedupeKey, promise)
    if (dedupeKey) {
      _submitTaskPending.set(dedupeKey, promise)
    }
    void promise.finally(() => {
      _submitTaskPending.delete(submitDedupeKey)
      if (dedupeKey) {
        _submitTaskPending.delete(dedupeKey)
      }
      if (_activeSubmitDedupeKey === submitDedupeKey) {
        _activeSubmitAbortController = null
        _activeSubmitDedupeKey = null
      }
    })

    return promise
  },

  abortSubmitStream(threadId?: string) {
    if (_activeSubmitAbortController) {
      _activeSubmitAbortController.abort()
      _activeSubmitAbortController = null
    }
    if (threadId) {
      _submitTaskPending.delete(threadId)
    }
    if (_activeSubmitDedupeKey) {
      _submitTaskPending.delete(_activeSubmitDedupeKey)
      _activeSubmitDedupeKey = null
    }
  },

  /**
   * 获取消息流（SSE）- 持续监听直到任务完成
   * 不再需要 fromId 参数，后端会自动从 last_generated_id 开始
   * 流会在任务完成（COMPLETED/FAILED/CANCELLED）时自动结束
   */
  async getMessageStream(
    runId: string,
    usePost: boolean = true,
  ): Promise<ReadableStream<Uint8Array>> {
    if (!runId || !runId.trim()) {
      throw new Error('Missing run_id for message stream')
    }
    // 同一 run_id 新连接时先 abort 掉上一次（本 tab 内只保留一个 stream）
    if (streamAbortControllers[runId]) {
      streamAbortControllers[runId].abort()
    }
    const controller = new AbortController()
    streamAbortControllers[runId] = controller

    console.log('🌐 [API] ===== getMessageStream CALLED =====')
    console.log('🌐 [API] run_id:', runId)
    console.log('🌐 [API] usePost:', usePost)
    console.log('🌐 [API] URL:', `${CUTI_VIDEO_API_BASE_URL}/agent-router/messages/stream`)

    let response: Response
    if (usePost) {
      const requestBody = { run_id: runId }
      console.log('🌐 [API] POST body:', JSON.stringify(requestBody))
      const currentLang = localStorage.getItem('language') || 'en'
      response = await fetch(
        `${CUTI_VIDEO_API_BASE_URL}/agent-router/messages/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-App-Language': currentLang,
          },
          credentials: 'include',
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        },
      )
    } else {
      console.log('🌐 [API] Using GET method')
      const currentLang = localStorage.getItem('language') || 'en'
      response = await fetch(
        `${CUTI_VIDEO_API_BASE_URL}/agent-router/messages/${runId}`,
        {
          method: 'GET',
          credentials: 'include',
          headers: {
            'X-App-Language': currentLang,
          },
          signal: controller.signal,
        },
      )
    }

    console.log('🌐 [API] Response status:', response.status)
    console.log('🌐 [API] Response headers:', {
      'content-type': response.headers.get('content-type'),
      'content-length': response.headers.get('content-length'),
      'transfer-encoding': response.headers.get('transfer-encoding'),
    })

    if (!response.ok) {
      console.error('🌐 [API] ❌ Response not OK!')
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    if (!response.body) {
      console.error('🌐 [API] ❌ Response body is null!')
      throw new Error('Response body is null')
    }

    console.log('🌐 [API] ✅ Response body exists, returning stream')
    return response.body
  },

  abortMessageStream(runId?: string) {
    if (!runId) return
    if (streamAbortControllers[runId]) {
      streamAbortControllers[runId].abort()
      Reflect.deleteProperty(streamAbortControllers, runId)
    }
  },

  /**
   * 按当前选中的 image_tool / video_tool / lipsync_tool 获取支持的 aspect_ratio、resolution、lipsync_video_tools 等（供前端展示/置灰）
   */
  async getOptionsCapabilities(params?: { image_tool?: string; video_tool?: string; lipsync_tool?: string }): Promise<ResponseModel<{
    aspect_ratios: { value: string; label: string }[]
    resolutions: { value: string; label: string }[]
    warnings: string[]
    lipsync_video_tools?: { value: string; label: string }[]
  }>> {
    const search = new URLSearchParams()
    if (params?.image_tool) search.set('image_tool', params.image_tool)
    if (params?.video_tool) search.set('video_tool', params.video_tool)
    if (params?.lipsync_tool) search.set('lipsync_tool', params.lipsync_tool)
    const q = search.toString()
    return makeRequest<{
      aspect_ratios: { value: string; label: string }[]
      resolutions: { value: string; label: string }[]
      warnings: string[]
      lipsync_video_tools?: { value: string; label: string }[]
    }>(`/agent-router/options/capabilities${q ? `?${q}` : ''}`, {
      method: 'GET',
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 获取任务状态（使用 run_id）
   */
  async getTaskStatus(runId: string): Promise<ResponseModel<{
    run_id: string
    status: string
    is_terminal?: boolean // 后端返回：终态含 completed/failed/cancelled/interrupted
    progress?: string
    current_step?: string
    last_generated_event?: string
    last_generated_id?: string
    analysis_uuid?: string
    story_outline_uuid?: string
    video_assembly_uuid?: string
  }>> {
    return makeRequest<{
      run_id: string
      status: string
      is_terminal?: boolean
      progress?: string
      current_step?: string
      last_generated_event?: string
      last_generated_id?: string
      analysis_uuid?: string
      story_outline_uuid?: string
      video_assembly_uuid?: string
    }>('/agent-router/task/status', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId }),
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 创建流式对话请求（保留向后兼容，内部调用submitTask + getMessageStream）
   * @deprecated 使用 submitTask + getMessageStream 代替
   */
  async createStreamRequest(data: {
    userInput: string
    files?: File[]
    threadId?: string
    conversationId?: number
    userOption?: UserOption
    agentType?: string
  }): Promise<ReadableStream<Uint8Array>> {
    // 向后兼容：先提交任务，再获取消息流
    const taskResponse = await this.submitTask(data)
    const { run_id } = taskResponse.data
    if (!run_id) throw new Error('Task response did not include a run id')
    return this.getMessageStream(run_id)
  },

  /**
   * 取消任务（thread_id 与 run_id 至少传一个）
   */
  async cancelTask(params: { threadId?: string; runId?: string }): Promise<ResponseModel<CancelTaskResponse>> {
    const threadId = params.threadId?.trim()
    const runId = params.runId?.trim()
    if (!threadId && !runId) {
      throw new Error('cancelTask requires thread_id or run_id')
    }
    return makeRequest<CancelTaskResponse>('/agent-router/cancel', {
      method: 'POST',
      body: JSON.stringify({
        ...(threadId ? { thread_id: threadId } : {}),
        ...(runId ? { run_id: runId } : {}),
      }),
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 关闭「本次 interrupt」的 15s 自动继续（仍可手动点继续）；须 full_auto / 前端自动继续开启时才有意义。
   */
  async dismissInterruptAutoResume(body: {
    thread_id: string
    interrupted_run_id: string
    interrupt_msgid: number
  }): Promise<ResponseModel<{ ok: boolean }>> {
    return makeRequest<{ ok: boolean }>('/agent-router/dismiss-interrupt-auto-resume', {
      method: 'POST',
      body: JSON.stringify({
        thread_id: body.thread_id,
        interrupted_run_id: body.interrupted_run_id,
        interrupt_msgid: body.interrupt_msgid,
      }),
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 视频 pipeline resume：直接发给 VideoAgent（VA 有 interrupt checkpoint，ChatAgent 没有）
   */
  async submitVideoResume(data: {
    threadId: string
    resumeData: string
  }): Promise<AgentSubmitTaskResult> {
    const formData = new FormData()
    formData.append('thread_id', data.threadId)
    formData.append('resume_data', data.resumeData)
    const currentLang = localStorage.getItem('language') || 'en'
    const response = await fetch(`${CUTI_VIDEO_API_BASE_URL}/agent-router/stream`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
      headers: {
        'X-App-Language': currentLang,
      },
    })
    const result = await readApiResponse<AgentSubmitTaskResult['data']>(response)
    if (!response.ok) {
      throw new Error(result.message || `VideoAgent resume failed: ${response.status}`)
    }
    if (result.code !== 0) {
      throw new ApiBusinessError(result.code, result.message || 'Request failed')
    }
    if (!result.data.run_id) {
      throw new ApiBusinessError(result.code, result.message || 'missing run_id')
    }
    return result
  },

  /**
   * 获取运行中的任务列表
   */
  async getRunningTasks(): Promise<ResponseModel<RunningTasksResponse>> {
    return makeRequest<RunningTasksResponse>('/agent-router/running-tasks', {}, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 提交澄清回复
   */
  async submitClarification(threadId: string, data: {
    clarification_answers: Record<string, string>
    clarification_data: LegacyApiValue
  }): Promise<ResponseModel<LegacyApiValue>> {
    return makeRequest<LegacyApiValue>('/agent-router/submit-clarification', {
      method: 'POST',
      body: JSON.stringify({
        thread_id: threadId,
        clarification_answers: data.clarification_answers,
        clarification_data: data.clarification_data,
      }),
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 更新音乐提示词
   */
  async updateMusicPrompt(musicUuid: string, versionUuid: string, musicPrompt: string): Promise<ResponseModel<LegacyApiValue>> {
    return makeRequest<LegacyApiValue>(`/agent-router/music-editing/update-prompt/${musicUuid}/${versionUuid}`, {
      method: 'PUT',
      body: JSON.stringify({ music_prompt: musicPrompt }),
    }, CUTI_VIDEO_API_BASE_URL)
  },

  /**
   * 生成关键帧提示词
   */
  async generateKeyframePrompt(request: {
    keyframe_uuid: string
    version_number: number
    edit_instruction: string
    conversation_id: number
  }): Promise<ResponseModel<LegacyApiValue>> {
    return makeRequest<LegacyApiValue>('/agent-router/keyframe/generate-prompt', {
      method: 'POST',
      body: JSON.stringify(request),
    }, CUTI_VIDEO_API_BASE_URL)
  },
}


export const api = {
  agent: agentApi,
}

export default api
