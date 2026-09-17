import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, AlertTriangle, BrainCircuit, ChevronDown, FileCode2, ListX, Loader2, PanelLeft, Play, RotateCcw, WandSparkles } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ChatSidebar } from '@/components/video/ChatSidebar'
import { MessageArea } from '@/components/video/MessageArea'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { useIsMobile } from '@/hooks/use-mobile'
import { useLanguage } from '@/i18n/LanguageContext'
import {
  DEFAULT_IMAGE_GENERATION_TOOL,
  DEFAULT_VIDEO_OPTIONS,
  type ImageGenerationToolType,
} from '@/constants/defaults'
import { deepAgentV2Client } from '@/features/deep-agent-v2/client'
import { useComposerAttachments } from '@/features/deep-agent-v2/useComposerAttachments'
import { DeepAgentArtifacts } from '@/features/deep-agent-v2/DeepAgentArtifacts'
import {
  AgentProductionProgress,
  type RuntimeProductionProgress,
} from '@/features/deep-agent-v2/AgentProductionProgress'
import { DeepAgentTracePanel } from '@/features/deep-agent-v2/DeepAgentTracePanel'
import type { DeepAgentInputFile, DeepAgentSkill, DeepAgentSkillLock, DeepAgentTokenUsage } from '@/features/deep-agent-v2/types'
import { useDeepAgentWorkspace } from '@/features/deep-agent-v2/useDeepAgentWorkspace'
import { unpinConversation } from '@/utils/pinnedConversations'
import { resolveUserOptionDurationSec } from '@/utils/targetVideoDuration'
import {
  interpolate,
  skillDescription,
  skillDisplayName,
  skillUnavailableReason,
} from '@/features/deep-agent-v2/labels'

const activeTaskStatuses = new Set(['proposed', 'blocked', 'ready', 'running', 'waiting_external'])
const staleTerminalCheckpointMessage = /cannot modify a terminal build|该检查点已过期：构建已在后续流程中完成/
const CREATE_DEFAULT_DURATION_SECONDS = 15
const videoModelValues: Record<string, string> = {
  Auto: 'auto',
  'Seedance 1.0 Pro Fast': 'pollo_seedance',
  'Seedance 1.5 Pro Fast': 'pollo_seedance_v1_5',
  'Seedance 2.0': 'seedance_2_i2v',
  'Seedance 2.0 Turbo': 'seedance_2_i2v_turbo',
  'Seedance 2.0 Fast': 'seedance_2_fast_i2v',
  'Seedance 2.0 Fast Turbo': 'seedance_2_fast_i2v_turbo',
  'Kling v3 Std': 'kling_v3_std',
  'HappyHorse 1.0': 'happyhorse_1_0_i2v',
  'HappyHorse 1.1': 'happyhorse_1_1_i2v',
  Sora2: 'openai_sora',
  'Sora2 Pro': 'openai_sora_pro',
}

export default function DeepAgentWorkspacePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { threadId: routeThreadId } = useParams<{ threadId?: string }>()
  const initialRequest = location.state as {
    initialPrompt?: string
    uploadedFiles?: File[]
    inputFiles?: DeepAgentInputFile[]
    userOption?: Record<string, unknown>
    shouldAutoSend?: boolean
    workflow_id?: string
    automatic_video?: boolean
    planning_off?: boolean
    code_video_mode?: boolean
  } | null
  const shouldStartFromHome = Boolean(initialRequest?.shouldAutoSend && initialRequest.initialPrompt?.trim())
  const isMobile = useIsMobile()
  const { language, t } = useLanguage()
  const workspaceBase = location.pathname.includes('/deep-agent-v2')
    ? 'deep-agent-v2'
    : 'create'
  const workspacePath = useCallback((threadId?: string | null) => {
    const base = `/${language}/${workspaceBase}`
    const normalized = (threadId || '').trim()
    return normalized ? `${base}/${encodeURIComponent(normalized)}` : base
  }, [language, workspaceBase])
  const workspace = useDeepAgentWorkspace({
    // `/create` is a product entry, so a bare route always starts a fresh
    // project. The general Deep Agent workspace keeps its recent-run behavior.
    autoSelect: workspaceBase !== 'create' && !shouldStartFromHome && !routeThreadId,
    routeThreadId: routeThreadId || null,
  })
  const { state, loadFullTrace } = workspace
  const sendWorkspaceMessage = workspace.sendMessage
  const initialRequestHandled = useRef(false)
  const [message, setMessage] = useState('')
  const attachments = useComposerAttachments()
  const uploadedFiles = attachments.files
  const defaultDuration = workspaceBase === 'create'
    ? CREATE_DEFAULT_DURATION_SECONDS
    : DEFAULT_VIDEO_OPTIONS.duration
  const [duration, setDuration] = useState([defaultDuration])
  const [aspectRatio, setAspectRatio] = useState(DEFAULT_VIDEO_OPTIONS.aspectRatio)
  const [resolution, setResolution] = useState(DEFAULT_VIDEO_OPTIONS.resolution)
  const [selectedModel, setSelectedModel] = useState(DEFAULT_VIDEO_OPTIONS.selectedModel)
  const [imageGenerationTool, setImageGenerationTool] = useState<ImageGenerationToolType>(
    DEFAULT_IMAGE_GENERATION_TOOL,
  )
  const [lipsyncCoverage, setLipsyncCoverage] = useState(DEFAULT_VIDEO_OPTIONS.lipsyncCoverage)
  const [lipsyncVideoModel, setLipsyncVideoModel] = useState(DEFAULT_VIDEO_OPTIONS.lipsyncVideoModel)
  const [enableContinuityMode, setEnableContinuityMode] = useState(
    DEFAULT_VIDEO_OPTIONS.enableContinuityMode,
  )
  const [enableKeyframeReflection, setEnableKeyframeReflection] = useState(
    DEFAULT_VIDEO_OPTIONS.enableKeyframeReflection,
  )
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<'chat' | 'artifacts'>('chat')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)
  const [tokenUsage, setTokenUsage] = useState<DeepAgentTokenUsage | null>(null)
  const [skills, setSkills] = useState<DeepAgentSkill[]>([])
  const [selectedSkillName, setSelectedSkillName] = useState('')
  const [planningOff, setPlanningOff] = useState(false)
  const [codeVideoMode, setCodeVideoMode] = useState(false)
  const [defaultCodeVideoMode, setDefaultCodeVideoMode] = useState(false)
  const [wavespeedConfigured, setWavespeedConfigured] = useState<boolean | null>(null)
  const [projectSkillLocks, setProjectSkillLocks] = useState<DeepAgentSkillLock[]>([])
  const [isInstallingSkill, setIsInstallingSkill] = useState(false)
  const [runtimeProgress, setRuntimeProgress] = useState<RuntimeProductionProgress | null>(null)
  const skillUploadRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    void deepAgentV2Client.getRuntimeOptions(controller.signal)
      .then((options) => {
        setWavespeedConfigured(options.wavespeed_configured)
        setDefaultCodeVideoMode(options.default_code_video_mode)
        if (!state.snapshot?.run.id) setCodeVideoMode(options.default_code_video_mode)
      })
      .catch(() => undefined)
    return () => { controller.abort() }
  }, [state.snapshot?.run.id])

  useEffect(() => {
    setRuntimeProgress(null)
  }, [state.selectedRunId])

  useEffect(() => {
    if (!traceOpen || !state.selectedRunId) {
      if (!state.selectedRunId) setTokenUsage(null)
      return
    }
    const controller = new AbortController()
    void deepAgentV2Client.getTokenUsage(state.selectedRunId, controller.signal)
      .then(setTokenUsage)
      .catch(() => undefined)
    if (state.snapshot?.has_more_events) {
      void loadFullTrace()
    }
    return () =>{  controller.abort() }
  }, [traceOpen, state.selectedRunId, state.snapshot?.has_more_events, state.traceEvents.length, loadFullTrace])

  const status = state.snapshot?.run.status
  const isWaitingInput = status === 'waiting_input'
  const hasActiveTask = Boolean(state.snapshot?.tasks.some(task =>
    activeTaskStatuses.has(task.status),
  ))
  const runtimeBusy = Boolean(
    runtimeProgress && ['queued', 'running', 'waiting_external'].includes(runtimeProgress.status),
  )
  const runtimeFinished = Boolean(
    runtimeProgress && ['completed', 'failed', 'cancelled'].includes(runtimeProgress.status),
  )
  // Stop/send follows real work, not the SSE transport flag.
  // isStreaming stays true while the event socket is open or reconnecting, even
  // after the video build finished; that used to leave the red stop button stuck.
  // Downstream interrupt keeps the task as waiting_external while the run is
  // waiting_input — do not treat that as "still generating".
  const agentBusy =
    !isWaitingInput &&
    !runtimeFinished && (
      hasActiveTask ||
      state.isSending ||
      status === 'planning' ||
      status === 'running' ||
      status === 'waiting_external' ||
      isSubmitting
    )
  const isRunning = agentBusy || runtimeBusy

  // SSE is the live path; if a terminal run event is missed, hydrate so the
  // composer can leave the stop button. Right-hand artifacts already poll.
  useEffect(() => {
    const runId = state.selectedRunId
    const busy = status === 'planning' || status === 'running' || status === 'waiting_external'
    if (!runId || !busy) return
    const timer = window.setInterval(() => {
      void workspace.refresh()
    }, 8000)
    return () =>{  window.clearInterval(timer) }
  }, [state.selectedRunId, status, workspace.refresh])

  const selectedSkill = skills.find(skill => skill.name === selectedSkillName)
  const workflowSkills = useMemo(
    () => skills.filter(skill => skill.kind === 'workflow' || skill.metadata?.kind === 'workflow'),
    [skills],
  )
  const helperSkills = useMemo(
    () => skills.filter(skill => !(skill.kind === 'workflow' || skill.metadata?.kind === 'workflow')),
    [skills],
  )
  const activeThreadId = workspace.sessionThreadId
  // Skill picker is page-level state, not per-run. Switching conversations
  // must return to Automatic; otherwise $mv (etc.) leaks into the next chat.
  useEffect(() => {
    setSelectedSkillName('')
    setPlanningOff(false)
    setCodeVideoMode(defaultCodeVideoMode)
  }, [activeThreadId, defaultCodeVideoMode])
  useEffect(() => {
    if (state.snapshot?.run.id) {
      setPlanningOff(Boolean(state.snapshot.run.planning_off))
      setCodeVideoMode(Boolean(state.snapshot.run.code_video_mode))
    }
  }, [state.snapshot?.run.code_video_mode, state.snapshot?.run.id, state.snapshot?.run.planning_off])
  const enabledProjectSkillIds = new Set(
    projectSkillLocks.filter(lock => lock.enabled).map(lock => lock.skill_id),
  )
  const waitingInputPrompt = [
    state.notice?.whatHappened && interpolate(t('da.page.noticeNow'), { text: state.notice.whatHappened }),
    state.notice?.whyInterrupted && interpolate(t('da.page.noticeWhy'), { text: state.notice.whyInterrupted }),
    state.notice?.whyConfirm && interpolate(t('da.page.noticeNext'), { text: state.notice.whyConfirm }),
    state.notice?.skillName && interpolate(t('da.page.noticeSkill'), { text: skillDisplayName(state.notice.skillName, t) }),
    state.notice?.skillResource && interpolate(t('da.page.noticePolicySource'), { text: state.notice.skillResource }),
    state.notice?.skillPolicy && interpolate(t('da.page.noticePolicy'), { text: state.notice.skillPolicy }),
  ].filter(Boolean).join('\n')
    || (
      state.notice?.willAutoResume
        ? interpolate(t('da.page.waitingAuto'), { seconds: state.notice.autoResumeSeconds || 15 })
        : t('da.page.waitingManual')
    )
  const chatMessages = useMemo(
    () => {
      const mapped = state.messages
        .filter(item => !(
          status === 'completed'
          && item.role === 'assistant'
          && staleTerminalCheckpointMessage.test(item.content)
        ))
        .map((item) => {
          const metadataFiles = Array.isArray(item.metadata?.input_files)
            ? item.metadata.input_files.filter((file): file is Record<string, unknown> =>
              Boolean(file) && typeof file === 'object',
            )
            : []
          const attachmentData = metadataFiles.reduce<{
            images: Array<{ url: string; filename?: string }>
            audio_files: Array<{ url: string; filename?: string }>
            video_files: Array<{ url: string; filename?: string }>
          }>((result, file) => {
            if (typeof file.url !== 'string' || !file.url) return result
            const attachment = { ...file, url: file.url, filename: typeof file.filename === 'string' ? file.filename : undefined }
            if (file.type === 'image') result.images.push(attachment)
            if (file.type === 'audio' || file.type === 'music') result.audio_files.push(attachment)
            if (file.type === 'video') result.video_files.push(attachment)
            return result
          }, { images: [], audio_files: [], video_files: [] })
          const hasAttachments = metadataFiles.length > 0
          return {
            id: item.id,
            message_id: item.id,
            run_id: item.run_id,
            role: item.role === 'assistant' ? 'ai' : item.role,
            content: item.content,
            timestamp: item.created_at,
            event_type: item.event_type
            || (item.role === 'assistant' ? 'assistant_message' : 'user_input'),
            event_data: {
              ...(item.event_data || {}),
              ...(hasAttachments ? attachmentData : {}),
            },
          }
        })
      if (!isWaitingInput || !state.selectedRunId) return mapped
      return [
        ...mapped,
        {
          id: `waiting-input-hint-${state.selectedRunId}`,
          message_id: `waiting-input-hint-${state.selectedRunId}`,
          run_id: state.selectedRunId,
          role: 'ai',
          content: waitingInputPrompt,
          timestamp: new Date().toISOString(),
          event_type: 'assistant_message',
          event_data: { waiting_input: true },
        },
      ]
    },
    [isWaitingInput, state.messages, state.selectedRunId, waitingInputPrompt],
  )

  const resetComposer = () => {
    setMessage('')
    attachments.clear()
    setDuration([defaultDuration])
    setAspectRatio(DEFAULT_VIDEO_OPTIONS.aspectRatio)
    setResolution(DEFAULT_VIDEO_OPTIONS.resolution)
    setSelectedModel(DEFAULT_VIDEO_OPTIONS.selectedModel)
    setImageGenerationTool(DEFAULT_IMAGE_GENERATION_TOOL)
    setLipsyncCoverage(DEFAULT_VIDEO_OPTIONS.lipsyncCoverage)
    setLipsyncVideoModel(DEFAULT_VIDEO_OPTIONS.lipsyncVideoModel)
    setEnableContinuityMode(DEFAULT_VIDEO_OPTIONS.enableContinuityMode)
    setEnableKeyframeReflection(DEFAULT_VIDEO_OPTIONS.enableKeyframeReflection)
    setSelectedSkillName('')
    setPlanningOff(false)
    setCodeVideoMode(defaultCodeVideoMode)
  }

  const startNewSession = () => {
    resetComposer()
    setMobileTab('chat')
    const threadId = workspace.newSession()
    // Give every draft its own route immediately. A bare workspace route is
    // allowed to auto-select the latest run and would overwrite this draft.
    navigate(workspacePath(threadId), { replace: false, state: null })
  }

  const selectSession = (runId: string) => {
    setMessage('')
    attachments.clear()
    setSelectedSkillName('')
    setMobileTab('chat')
    if (runId === workspace.pendingThreadId) {
      navigate(workspacePath(runId), { replace: true, state: null })
      return
    }
    const threadId = state.runs.find(run => run.id === runId)?.thread_id
    workspace.selectRun(runId)
    if (threadId) {
      navigate(workspacePath(threadId), { replace: true, state: null })
    }
  }

  const deleteSession = async (runId: string, event: React.MouseEvent) => {
    event.stopPropagation()
    const run = state.runs.find(item => item.id === runId)
    if (!run) return
    const confirmed = window.confirm(t('da.page.deleteConfirm'))
    if (!confirmed) return
    try {
      const deletingSelected = state.selectedRunId === runId
      await workspace.deleteRun(runId)
      unpinConversation(runId)
      toast.success(t('da.page.deleted'))
      if (deletingSelected) startNewSession()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  // Keep the address bar aligned with the active conversation thread.
  useEffect(() => {
    // Draft conversations have a pending thread id but no durable run yet.
    // Sync only durable runs; the first successful send selects the new run
    // and this effect then attaches its thread id exactly once.
    if (!state.selectedRunId || !activeThreadId) return
    const expected = workspacePath(activeThreadId)
    if (location.pathname === expected) return
    // Avoid fighting an intentional bare /create while a draft without thread is impossible
    // (newSession always allocates one). Sync whenever we know the thread.
    navigate(expected, { replace: true, state: location.state as unknown })
  }, [activeThreadId, location.pathname, location.state, navigate, state.selectedRunId, workspacePath])

  useEffect(() => {
    if (
      initialRequestHandled.current ||
      !shouldStartFromHome ||
      !initialRequest?.initialPrompt
    ) {
      return
    }
    initialRequestHandled.current = true
    const initialPrompt = initialRequest.initialPrompt
    const submitInitialRequest = async () => {
      const files = initialRequest.uploadedFiles || []
      const prepared = initialRequest.inputFiles || []
      if (prepared.length === files.length && files.length > 0) {
        attachments.hydrateReady(files, prepared)
      } else if (files.length > 0) {
        attachments.addFiles(files)
      }
      const inputFiles = files.length ? await attachments.waitUntilReady() : []
      if (initialRequest.workflow_id) setSelectedSkillName(initialRequest.workflow_id)
      if (initialRequest.planning_off) setPlanningOff(true)
      if (initialRequest.code_video_mode) setCodeVideoMode(true)
      await sendWorkspaceMessage(initialPrompt, {
        user_option: initialRequest.userOption,
        input_files: inputFiles,
        automatic_video: initialRequest.automatic_video ?? false,
        planning_off: initialRequest.planning_off,
        code_video_mode: initialRequest.code_video_mode,
        ...(initialRequest.workflow_id ? { workflow_id: initialRequest.workflow_id } : {}),
      })
      attachments.clear()
    }
    void submitInitialRequest().catch((error: unknown) => {
      setMessage(initialRequest.initialPrompt || '')
      toast.error(error instanceof Error ? error.message : String(error))
    })
  }, [
    initialRequest,
    language,
    location.pathname,
    navigate,
    shouldStartFromHome,
    sendWorkspaceMessage,
  ])

  useEffect(() => {
    const controller = new AbortController()
    void deepAgentV2Client.listSkills(controller.signal)
      .then((items) =>{  setSkills(items.filter(item => item.enabled)) })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          toast.error(error instanceof Error ? error.message : String(error))
        }
      })
    return () =>{  controller.abort() }
  }, [])

  useEffect(() => {
    if (!activeThreadId || !state.snapshot?.run.id) {
      setProjectSkillLocks([])
      return
    }
    const controller = new AbortController()
    void deepAgentV2Client.listProjectSkills(activeThreadId, controller.signal)
      .then((locks) => {
        if (!controller.signal.aborted) setProjectSkillLocks(locks)
      })
      .catch((error: unknown) => {
        // A draft URL has no project yet. Do not turn that into a workspace error.
        if (!controller.signal.aborted && !(error instanceof Error && /not found/i.test(error.message))) {
          toast.error(error instanceof Error ? error.message : String(error))
        }
      })
    return () =>{  controller.abort() }
  }, [activeThreadId, state.snapshot?.run.id])

  const setProjectSkill = async (skill: DeepAgentSkill, enabled: boolean) => {
    if (!activeThreadId || !state.snapshot?.run.id) {
      toast.error(t('da.skill.createProjectFirst'))
      return
    }
    try {
      const lock = await deepAgentV2Client.setProjectSkillEnabled(activeThreadId, skill.name, enabled)
      setProjectSkillLocks(previous => [
        ...previous.filter(item => item.skill_id !== lock.skill_id),
        lock,
      ])
      if (enabled) setSelectedSkillName(skill.name)
      if (!enabled && selectedSkillName === skill.name) setSelectedSkillName('')
      toast.success(enabled
        ? interpolate(t('da.skill.enabledForProject'), { name: skillDisplayName(skill.name, t) })
        : interpolate(t('da.skill.disabledForProject'), { name: skillDisplayName(skill.name, t) }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  const installSkillBundle = async (file?: File | null) => {
    if (!file || isInstallingSkill) return
    if (!/\.zip$/i.test(file.name)) {
      toast.error(t('da.skill.uploadZipRequired'))
      return
    }
    setIsInstallingSkill(true)
    try {
      const installed = await deepAgentV2Client.installProjectSkill(file)
      const refreshed = await deepAgentV2Client.listSkills()
      setSkills(refreshed.filter(item => item.enabled))
      setSelectedSkillName(installed.name)
      toast.success(interpolate(t('da.skill.installed'), { name: skillDisplayName(installed.name, t) }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setIsInstallingSkill(false)
      if (skillUploadRef.current) skillUploadRef.current.value = ''
    }
  }

  useEffect(() => {
    const option = state.snapshot?.run.user_option
    if (!option) return
    if (typeof option.duration === 'number') setDuration([option.duration])
    if (option.aspect_ratio === '16:9' || option.aspect_ratio === '1:1' || option.aspect_ratio === '9:16') {
      setAspectRatio(option.aspect_ratio)
    }
    if (option.resolution === '480p' || option.resolution === '720p' || option.resolution === '1080p') {
      setResolution(option.resolution)
    }
    if (typeof option.video_generation_tool === 'string') {
      const label = Object.entries(videoModelValues).find(
        ([, value]) => value === option.video_generation_tool,
      )?.[0]
      if (label) setSelectedModel(label)
    }
    if (
      option.image_generation_tool === 'nano_banana' ||
      option.image_generation_tool === 'nano_banana_2' ||
      option.image_generation_tool === 'nano_banana_pro' ||
      option.image_generation_tool === 'seedream' ||
      option.image_generation_tool === 'gpt_image_2'
    ) {
      setImageGenerationTool(option.image_generation_tool)
    }
    if (typeof option.lipsync_coverage === 'number') setLipsyncCoverage(option.lipsync_coverage)
    if (typeof option.lipsync_video_tool === 'string') setLipsyncVideoModel(option.lipsync_video_tool)
    if (typeof option.enable_continuity_mode === 'boolean') {
      setEnableContinuityMode(option.enable_continuity_mode)
    }
    if (typeof option.enable_keyframe_reflection === 'boolean') {
      setEnableKeyframeReflection(option.enable_keyframe_reflection)
    }
  }, [state.snapshot?.run.id, state.snapshot?.run.user_option])

  const persistedChats = state.runs.map(run => ({
    id: run.id,
    title: run.title || t('da.page.untitledTask'),
    thread_id: run.thread_id,
    conversation_id: 0,
    preview: run.last_response,
    created_at: run.created_at,
    last_active_at: run.updated_at,
    agent_type: 'auto',
  }))
  const chats = workspace.pendingThreadId && !state.selectedRunId
    ? [{
      id: workspace.pendingThreadId,
      title: t('da.page.newConversation'),
      thread_id: workspace.pendingThreadId,
      conversation_id: 0,
      preview: '',
      created_at: new Date().toISOString(),
      last_active_at: new Date().toISOString(),
      agent_type: 'auto',
    }, ...persistedChats]
    : persistedChats

  const currentUserOption = (requestText?: string) => ({
    duration: resolveUserOptionDurationSec(duration[0] ?? DEFAULT_VIDEO_OPTIONS.duration, requestText),
    aspect_ratio: aspectRatio,
    resolution,
    video_generation_tool: videoModelValues[selectedModel] || 'auto',
    image_generation_tool: imageGenerationTool,
    lipsync_coverage: lipsyncCoverage,
    lipsync_video_tool: lipsyncVideoModel,
    enable_continuity_mode: enableContinuityMode,
    enable_keyframe_reflection: enableKeyframeReflection,
  })

  const send = async (content = message) => {
    const hasText = Boolean(content.trim())
    const hasFiles = uploadedFiles.length > 0
    if ((!hasText && !hasFiles) || isSubmitting || state.isSending) return
    const normalizedContent = content.trim() || (
      t('da.page.analyzeAttachment')
    )
    setMessage('')
    setIsSubmitting(true)
    try {
      const selectedKind = selectedSkill?.kind || selectedSkill?.metadata?.kind
      const skillOptions = !planningOff && !codeVideoMode && selectedSkill
        ? selectedKind === 'workflow'
          ? { workflow_id: selectedSkill.name }
          : { activated_skill_ids: [selectedSkill.name] }
        : {}
      const inputFiles = hasFiles ? await attachments.waitUntilReady() : []
      if (hasFiles && inputFiles.length !== uploadedFiles.length) {
        throw new Error(t('da.page.uploadPartialFail'))
      }
      const userOption = currentUserOption(normalizedContent)
      if (userOption.duration !== duration[0]) setDuration([userOption.duration])
      if (isWaitingInput) {
        await workspace.resume(normalizedContent, {
          user_option: userOption,
          input_files: inputFiles,
          planning_off: planningOff,
          code_video_mode: codeVideoMode,
          ...skillOptions,
        })
        attachments.clear()
        return
      }
      await workspace.sendMessage(normalizedContent, {
        user_option: userOption,
        input_files: inputFiles,
        planning_off: planningOff,
        code_video_mode: codeVideoMode,
        ...skillOptions,
      })
      attachments.clear()
    } catch (error) {
      setMessage(content)
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setIsSubmitting(false)
    }
  }

  const messageArea = (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-11 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border/50 px-3 py-1">
        {isMobile && (
          <Button variant="ghost" size="icon" onClick={() =>{  setMobileSidebarOpen(true) }}>
            <PanelLeft className="h-4 w-4" />
          </Button>
        )}
        <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
          <input
            ref={skillUploadRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={event => void installSkillBundle(event.target.files?.[0])}
          />
          <div
            role="toolbar"
            aria-label={t('da.page.creationControls')}
            className="flex max-w-full flex-nowrap items-center justify-end gap-1 rounded-xl border border-border/80 bg-muted/35 p-1 shadow-sm max-sm:grid max-sm:flex-1 max-sm:grid-cols-2"
          >
            <Button
              size="sm"
              variant="outline"
              className={codeVideoMode
                ? 'h-8 shrink-0 gap-1.5 rounded-lg border-foreground bg-foreground px-2 text-xs text-background shadow-sm hover:bg-foreground/90 hover:text-background'
                : 'h-8 shrink-0 gap-1.5 rounded-lg bg-background/80 px-2 text-xs shadow-sm'}
              aria-pressed={codeVideoMode}
              title={t(
                codeVideoMode
                  ? 'da.codeVideo.disable'
                  : wavespeedConfigured === false
                    ? 'da.codeVideo.fallback'
                    : 'da.codeVideo.enable',
              )}
              onClick={() => {
                setCodeVideoMode((value) => {
                  const next = !value
                  if (next) {
                    setPlanningOff(false)
                    setSelectedSkillName('')
                  }
                  return next
                })
              }}
            >
              <FileCode2 className="h-3.5 w-3.5" />
              {t('da.codeVideo.label')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className={planningOff
                ? 'h-8 shrink-0 gap-1.5 rounded-lg border-foreground bg-foreground px-2 text-xs text-background shadow-sm hover:bg-foreground/90 hover:text-background'
                : 'h-8 shrink-0 gap-1.5 rounded-lg bg-background/80 px-2 text-xs shadow-sm'}
              aria-pressed={planningOff}
              title={t(planningOff ? 'da.planningOff.disable' : 'da.planningOff.enable')}
              onClick={() => {
                setPlanningOff((value) => {
                  const next = !value
                  if (next) {
                    setCodeVideoMode(false)
                    setSelectedSkillName('')
                  }
                  return next
                })
              }}
            >
              <ListX className="h-3.5 w-3.5" />
              {t('da.planningOff.label')}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className={selectedSkill
                    ? 'h-8 shrink-0 gap-1.5 rounded-lg border-foreground bg-foreground px-2 text-xs text-background shadow-sm hover:bg-foreground/90 hover:text-background'
                    : 'h-8 shrink-0 gap-1.5 rounded-lg bg-background/80 px-2 text-xs shadow-sm'}
                  disabled={planningOff || codeVideoMode}
                >
                  <WandSparkles className="h-3.5 w-3.5" />
                  <span className="max-w-28 truncate">
                    {selectedSkill ? skillDisplayName(selectedSkill.name, t) : t('da.skill.select')}
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-80">
                <DropdownMenuLabel>
                  {t('da.skill.activate')}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <div className="max-h-[60vh] overflow-y-auto pr-1">
                  <DropdownMenuRadioGroup
                    value={selectedSkillName || '__auto__'}
                    onValueChange={(value) =>{  setSelectedSkillName(value === '__auto__' ? '' : value) }}
                  >
                    <DropdownMenuRadioItem value="__auto__">
                      <div>
                        <div className="font-medium">{t('da.skill.automatic')}</div>
                        <div className="text-xs text-muted-foreground">
                          {t('da.skill.automaticHint')}
                        </div>
                      </div>
                    </DropdownMenuRadioItem>
                    <DropdownMenuLabel className="text-xs">
                      {t('da.skill.workflows')}
                    </DropdownMenuLabel>
                    {workflowSkills.map(skill => (
                      <DropdownMenuRadioItem
                        key={skill.name}
                        value={skill.name}
                        disabled={skill.available === false}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 truncate font-medium">
                            <span>{skillDisplayName(skill.name, t)}</span>
                            <span className="shrink-0 text-[10px] font-normal text-muted-foreground">${skill.name}</span>
                            {enabledProjectSkillIds.has(skill.name) && (
                              <span className="rounded bg-accent-purple/15 px-1 py-0.5 text-[9px] font-medium text-accent-purple">
                                {t('da.skill.projectLocked')}
                              </span>
                            )}
                          </div>
                          <div className="line-clamp-2 text-xs text-muted-foreground">
                            {skillDescription(skill.name, t, skill.description)}
                          </div>
                          {skill.available === false && (
                            <div className="line-clamp-2 text-xs text-amber-600">
                              {skillUnavailableReason(skill.unavailable_reason, t)}
                            </div>
                          )}
                        </div>
                      </DropdownMenuRadioItem>
                    ))}
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className="text-xs">
                      {t('da.skill.helpers')}
                    </DropdownMenuLabel>
                    {helperSkills.map(skill => (
                      <DropdownMenuRadioItem key={skill.name} value={skill.name}>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">
                            {skillDisplayName(skill.name, t)}
                            <span className="ml-1 text-[10px] font-normal text-muted-foreground">${skill.name}</span>
                          </div>
                          <div className="line-clamp-2 text-xs text-muted-foreground">
                            {skillDescription(skill.name, t, skill.description)}
                          </div>
                        </div>
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </div>
                {state.snapshot?.run.id && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className="text-xs">
                      {t('da.skill.projectLocks')}
                    </DropdownMenuLabel>
                    <div className="max-h-40 overflow-y-auto">
                      {skills.map((skill) => {
                        const locked = projectSkillLocks.find(item => item.skill_id === skill.name)
                        const enabled = Boolean(locked?.enabled)
                        return (
                          <DropdownMenuItem
                            key={`lock-${skill.name}`}
                            className="flex items-center justify-between gap-3"
                            onSelect={(event) => {
                              event.preventDefault()
                              void setProjectSkill(skill, !enabled)
                            }}
                          >
                            <span className="truncate text-xs">{skillDisplayName(skill.name, t)}</span>
                            <span className={enabled ? 'text-[10px] text-emerald-600' : 'text-[10px] text-muted-foreground'}>
                              {enabled ? t('da.skill.enabled') : t('da.skill.enable')}
                            </span>
                          </DropdownMenuItem>
                        )
                      })}
                    </div>
                  </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={isInstallingSkill}
                  onSelect={(event) => {
                    event.preventDefault()
                    skillUploadRef.current?.click()
                  }}
                >
                  {isInstallingSkill ? t('da.skill.installing') : t('da.skill.uploadZip')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              size="sm"
              variant="outline"
              className={traceOpen
                ? 'h-8 shrink-0 gap-1.5 rounded-lg border-foreground bg-foreground px-2 text-xs text-background shadow-sm hover:bg-foreground/90 hover:text-background'
                : 'h-8 shrink-0 gap-1.5 rounded-lg bg-background/80 px-2 text-xs shadow-sm'}
              aria-pressed={traceOpen}
              onClick={() =>{  setTraceOpen(value => !value) }}
            >
              <BrainCircuit className="h-3.5 w-3.5" />
              {t('da.page.trace')}
              {state.traceEvents.length > 0 && (
                <span className={
                  traceOpen
                    ? 'rounded-full bg-background/20 px-1.5 text-[10px] text-background'
                    : 'rounded-full bg-accent-purple/15 px-1.5 text-[10px] text-accent-purple'
                }>
                  {state.traceEvents.length}
                </span>
              )}
            </Button>
          </div>
          {isWaitingInput && (
            <Button
              size="sm"
              variant="default"
              onClick={() => void workspace.resume(t('da.page.continue'), { planning_off: planningOff, code_video_mode: codeVideoMode })}
            >
              <Play className="mr-1.5 h-3.5 w-3.5" />
              {t('da.page.continue')}
            </Button>
          )}
          {(status === 'cancelled' || status === 'failed') && (
            <Button size="sm" variant="outline" onClick={() => void workspace.resume(t('da.page.resumeAndContinue'), { planning_off: planningOff, code_video_mode: codeVideoMode })}>
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
              {t('da.page.resume')}
            </Button>
          )}
        </div>
      </div>
      {isWaitingInput && (
        <div className={
          state.notice?.willAutoResume
            ? 'flex flex-wrap items-start gap-3 border-b border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-950 dark:text-sky-100'
            : 'flex flex-wrap items-start gap-3 border-b border-amber-500/40 bg-amber-500/15 px-4 py-3 text-sm text-amber-950 dark:text-amber-100'
        }>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="font-medium">
              {state.notice?.confirmationRequired
                ? t('da.page.interruptNeedsConfirm')
                : state.notice?.willAutoResume
                  ? t('da.page.interruptAutoSoon')
                  : t('da.page.interruptPaused')}
            </p>
            <p className="text-xs opacity-95">
              <span className="font-semibold">{t('da.page.now')}</span>
              {state.notice?.whatHappened || t('da.page.pausedMidway')}
            </p>
            <p className="text-xs opacity-95">
              <span className="font-semibold">{t('da.page.why')}</span>
              {state.notice?.whyInterrupted || t('da.page.pauseToConfirm')}
            </p>
            <p className="text-xs opacity-95">
              <span className="font-semibold">{t('da.page.next')}</span>
              {state.notice?.whyConfirm
                || waitingInputPrompt}
            </p>
            {(state.notice?.skillName || state.notice?.capabilityId || state.notice?.stage) && (
              <p className="text-xs opacity-95">
                <span className="font-semibold">{t('da.page.triggeredBy')}</span>
                {[
                  state.notice.skillName && interpolate(t('da.page.noticeSkill'), { text: skillDisplayName(state.notice.skillName, t) }),
                  state.notice.skillResource,
                  state.notice.capabilityId && interpolate(t('da.page.noticeCapability'), { text: state.notice.capabilityId }),
                  state.notice.stage && interpolate(t('da.page.noticeStage'), { text: state.notice.stage }),
                  state.notice.taskId && interpolate(t('da.page.noticeTask'), { text: state.notice.taskId }),
                ].filter(Boolean).join(' · ')}
              </p>
            )}
            {state.notice?.skillPolicy && (
              <p className="rounded bg-background/40 px-2 py-1 text-[11px] opacity-90">
                <span className="font-semibold">{t('da.page.skillPolicy')}</span>
                {state.notice.skillPolicy}
              </p>
            )}
            <p className="text-[11px] opacity-80">
              {state.notice?.confirmationRequired
                ? t('da.page.verifiedConfirm')
                : t('da.page.noConfirmNeeded')}
            </p>          </div>
          <Button
            size="sm"
            className="shrink-0"
            onClick={() => void workspace.resume(t('da.page.continue'), { planning_off: planningOff, code_video_mode: codeVideoMode })}
          >
            <Play className="mr-1.5 h-3.5 w-3.5" />
            {t('da.page.continue')}
          </Button>
        </div>
      )}
      {state.notice && !isWaitingInput && (
        <div
          className={
            state.notice.severity === 'error'
              ? 'flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive'
              : state.notice.severity === 'warning'
                ? 'flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-200'
                : 'flex items-center gap-2 border-b border-border/60 bg-muted/40 px-4 py-2 text-xs text-muted-foreground'
          }
        >
          {state.notice.severity === 'error' ? (
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          )}
          <div className="min-w-0 flex-1">
            <p className="whitespace-pre-line">{state.notice.message}</p>
            {(state.notice.skillName || state.notice.capabilityId) && (
              <p className="mt-1 text-[10px] opacity-75">
                {[
                  state.notice.skillName && interpolate(t('da.page.noticeSkill'), { text: skillDisplayName(state.notice.skillName, t) }),
                  state.notice.capabilityId && interpolate(t('da.page.noticeCapability'), { text: state.notice.capabilityId }),
                ].filter(Boolean).join(' · ')}
              </p>
            )}
          </div>
          {state.notice.severity !== 'error' && (
            <span className="shrink-0 text-[10px] opacity-70">
              {t('da.page.stillInProgress')}
            </span>
          )}
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        {state.isHydrating && !state.snapshot && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-background">
            <Loader2 className="h-5 w-5 animate-spin text-accent-purple" />
          </div>
        )}
        <div className="flex h-full min-h-0 flex-col">
          <AgentProductionProgress
            status={status}
            isSending={state.isSending || isSubmitting}
            isRunning={isRunning}
            events={state.traceEvents}
            tasks={state.snapshot?.tasks || []}
            runtime={runtimeProgress}
            language={language}
            upload={
              (attachments.hasUnfinished || (isSubmitting && uploadedFiles.length > 0 && attachments.overallPhase !== 'ready'))
                ? {
                  percent: attachments.overallPercent,
                  phase: attachments.overallPhase === 'saving' ? 'saving' : 'uploading',
                }
                : null
            }
          />
          <div className="min-h-0 flex-1">
            <MessageArea
              chatTitle={state.snapshot?.run.title || t('da.page.newTask')}
              messages={chatMessages}
              message={message}
              uploadedFiles={uploadedFiles}
              fileUploadStates={attachments.uploadStates}
              isGenerating={isRunning}
              isInFlight={isRunning}
              showAssistantThinking={status === 'planning' || state.isSending}
              hideHeader
              threadId={activeThreadId}
              conversationId={state.selectedRunId || activeThreadId}
              onMessageChange={setMessage}
              onFileUpload={attachments.addFiles}
              onFileRemove={attachments.removeAt}
              onFileReplace={attachments.replaceAt}
              onSendMessage={() => void send()}
              onSendWithPrompt={prompt => void send(prompt)}
              onActionSuggestionClick={(suggestion) => {
                void workspace.sendSuggestion(suggestion, {
                  user_option: currentUserOption(),
                  planning_off: planningOff,
                  code_video_mode: codeVideoMode,
                }).catch((error: unknown) => toast.error(error instanceof Error ? error.message : String(error)))
              }}
              onCancelGeneration={() => void workspace.cancel().catch((error: unknown) => {
                toast.error(error instanceof Error ? error.message : String(error))
              })}
              showTodoList={false}
              showActionSuggestions
              streamedActionSuggestions={state.suggestions}
              agentType="auto"
              duration={duration}
              aspectRatio={aspectRatio}
              resolution={resolution}
              selectedModel={selectedModel}
              imageGenerationTool={imageGenerationTool}
              lipsyncCoverage={lipsyncCoverage}
              lipsyncVideoModel={lipsyncVideoModel}
              enableContinuityMode={enableContinuityMode}
              enableKeyframeReflection={enableKeyframeReflection}
              onDurationChange={setDuration}
              onAspectRatioChange={setAspectRatio}
              onResolutionChange={setResolution}
              onModelChange={setSelectedModel}
              onImageGenerationToolChange={setImageGenerationTool}
              onLipsyncCoverageChange={setLipsyncCoverage}
              onLipsyncVideoModelChange={setLipsyncVideoModel}
              onEnableContinuityModeChange={setEnableContinuityMode}
              onEnableKeyframeReflectionChange={setEnableKeyframeReflection}
              isInputDisabled={state.isHydrating && !state.snapshot}
            />
          </div>
        </div>
      </div>
    </div>
  )

  const artifactsArea = state.snapshot ? (
    <DeepAgentArtifacts
      key={state.snapshot.run.project_id}
      snapshot={state.snapshot}
      onSelectArtifact={id => void workspace.selectArtifact(id)}
      onExtractFrame={options => workspace.extractFrame(options)}
      onRefresh={() => void workspace.refresh()}
      onRuntimeProgress={setRuntimeProgress}
    />
  ) : (
    <div className="flex h-full items-center justify-center bg-white px-8 text-center text-sm text-muted-foreground dark:bg-black">
      {state.isHydrating
        ? <Loader2 className="h-5 w-5 animate-spin" />
        : t('da.workspace.begin')}
    </div>
  )

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden bg-background">
      {!isMobile && (
        <ChatSidebar
          collapsed={sidebarCollapsed}
          selectedChat={state.selectedRunId || workspace.pendingThreadId}
          chats={chats}
          userInfo={null}
          userCredits={null}
          isLoadingChats={state.isLoadingRuns}
          hasMoreChats={false}
          showConversationActions={false}
          showDeleteAction
          onToggleCollapse={() =>{  setSidebarCollapsed(value => !value) }}
          onNewTask={startNewSession}
          onSelectChat={selectSession}
          onDeleteChat={(id, event) => void deleteSession(id, event)}
          onTogglePin={(_, event) =>{  event.stopPropagation() }}
        />
      )}

      {isMobile ? (
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className={mobileTab === 'chat' ? 'h-full min-h-0 pb-16' : 'hidden'}>{messageArea}</div>
          <div className={mobileTab === 'artifacts' ? 'h-full min-h-0 pb-16' : 'hidden'}>{artifactsArea}</div>
          <div className="fixed bottom-3 left-1/2 z-40 flex -translate-x-1/2 rounded-full border border-border/60 bg-background/90 p-1 shadow-lg backdrop-blur">
            <Button size="sm" variant={mobileTab === 'chat' ? 'secondary' : 'ghost'} onClick={() =>{  setMobileTab('chat') }}>
              {t('da.page.chat')}
            </Button>
            <Button size="sm" variant={mobileTab === 'artifacts' ? 'secondary' : 'ghost'} onClick={() =>{  setMobileTab('artifacts') }}>
              {t('da.page.create')}
            </Button>
          </div>
          {mobileSidebarOpen && (
            <div className="fixed inset-0 z-50 flex">
              <div className="w-80 max-w-[86vw] bg-background">
                <ChatSidebar
                  collapsed={false}
                  selectedChat={state.selectedRunId || workspace.pendingThreadId}
                  chats={chats}
                  userInfo={null}
                  userCredits={null}
                  isLoadingChats={state.isLoadingRuns}
                  hasMoreChats={false}
                  showConversationActions={false}
                  showDeleteAction
                  onToggleCollapse={() =>{  setMobileSidebarOpen(false) }}
                  onNewTask={() => { startNewSession(); setMobileSidebarOpen(false) }}
                  onSelectChat={(id) => { selectSession(id); setMobileSidebarOpen(false) }}
                  onDeleteChat={(id, event) => void deleteSession(id, event)}
                  onTogglePin={(_, event) =>{  event.stopPropagation() }}
                  isMobileFullScreen
                />
              </div>
              <button className="flex-1 bg-black/50" aria-label={t('da.page.closeSidebar')} onClick={() =>{  setMobileSidebarOpen(false) }} />
            </div>
          )}
        </div>
      ) : (
        <ResizablePanelGroup direction="horizontal" className="min-w-0 flex-1">
          <ResizablePanel defaultSize={38} minSize={25} maxSize={52} className="min-w-0">
            {messageArea}
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={62} minSize={48} className="min-w-0">
            {artifactsArea}
          </ResizablePanel>
        </ResizablePanelGroup>
      )}
      <DeepAgentTracePanel
        events={state.traceEvents}
        tokenUsage={tokenUsage}
        open={traceOpen}
        language={language}
        onClose={() =>{  setTraceOpen(false) }}
      />
    </div>
  )
}
