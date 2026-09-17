import { asyncEvent } from '../utils/asyncEvent'
import { useState, useRef, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useLanguage } from '@/i18n/LanguageContext'
import { toast } from 'sonner'
import { validateFiles, createDragDropHandler, normalizeClipboardFile } from '@/utils/fileUploadUtils'
import { getAudioFileDurationSec, smartCropUploadedAudioFiles } from '@/utils/audioCrop'
import { isAudioFile } from '@/utils/fileUploadUtils'
import { resolveAutoCropTargetDurationSec, resolveSendDurationPlan } from '@/utils/targetVideoDuration'
import { FilePreview } from '@/components/FilePreview'
import { AudioCropDialog } from '@/components/AudioCropDialog'
import CharacterSelectPopover from '@/components/CharacterSelectDialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { DEFAULT_IMAGE_GENERATION_TOOL, DEFAULT_VIDEO_OPTIONS, type ImageGenerationToolType } from '@/constants/defaults'
import { useComposerAttachments } from '@/features/deep-agent-v2/useComposerAttachments'
import { VideoOptionsPanel } from '@/components/VideoOptionsPanel'
import {
  Image,
  Video,
  Music,
  Upload,
  Send,
  X,
  User,
  Plus,
  ArrowRight,
} from 'lucide-react'

interface GenerationBoxProps {
  title?: string
  subtitle?: string
  className?: string
  variant?: 'default' | 'landing'
  placeholder?: string
  selectedWorkflowId?: string
  selectedWorkflowLabel?: string
  onClearWorkflow?: () => void
  externalPrompt?: string // External prompt to fill into the input
  externalFiles?: File[] // External files to pre-upload
  /** 内容模版：如 "Lip-Sync MV"（点 Lip-sync 卡片时），默认不传为 Default */
  externalContentCategory?: string
  /** 当此值变化且 > 0 时，播放发送按钮动效并自动发送（如从卡片1上传头像后） */
  autoSendTrigger?: number
}

// Options 按钮图标：两行圆+横线样式
const OptionsIconCustom = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className={className}>
    <circle cx="6" cy="7" r="2" />
    <line x1="11" y1="7" x2="20" y2="7" />
    <line x1="4" y1="17" x2="13" y2="17" />
    <circle cx="18" cy="17" r="2" />
  </svg>
)

const GenerationBox = ({
  title = '',
  subtitle = '',
  className = '',
  variant = 'default',
  placeholder,
  selectedWorkflowId,
  selectedWorkflowLabel,
  onClearWorkflow,
  externalPrompt,
  externalFiles,
  externalContentCategory,
  autoSendTrigger,
}: GenerationBoxProps) => {
  const { t, language } = useLanguage()
  const navigate = useNavigate()
  const { lang: routeLang } = useParams<{ lang: string }>()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const characterFileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const characterNameInputRef = useRef<HTMLInputElement>(null)
  const lastExternalPromptRef = useRef<string>('')
  const lastAutoSendTriggerRef = useRef(0)

  // 读取环境变量配置，默认为 false（不显示 image/music）
  const showImageMusicCreation = import.meta.env.VITE_SHOW_IMAGE_MUSIC_CREATION === 'true'
  // 读取环境变量配置，默认为 false（不显示 instant 模式切换）
  const showInstantMode = import.meta.env.VITE_SHOW_INSTANT_MODE === 'true'

  // Generation states
  const [prompt, setPrompt] = useState('')
  const [selectedMediaType, setSelectedMediaType] = useState<'image' | 'video' | 'music' | 'character'>('video')
  const [isInstantMode, setIsInstantMode] = useState(false)
  const [duration, setDuration] = useState([DEFAULT_VIDEO_OPTIONS.duration])
  const durationExplicitlySetRef = useRef(false)
  const [aspectRatio, setAspectRatio] = useState<'16:9' | '1:1' | '9:16'>(DEFAULT_VIDEO_OPTIONS.aspectRatio)
  const [resolution, setResolution] = useState<'480p' | '720p' | '1080p'>(DEFAULT_VIDEO_OPTIONS.resolution)
  const [lipsyncRatio, setLipsyncRatio] = useState([DEFAULT_VIDEO_OPTIONS.lipsyncCoverage])
  const [isGenerating, setIsGenerating] = useState(false)
  const attachments = useComposerAttachments()
  const uploadedFiles = attachments.files
  const [audioCropOpen, setAudioCropOpen] = useState(false)
  const [audioCropTarget, setAudioCropTarget] = useState<{ index: number; file: File } | null>(null)

  // 拖拽上传状态
  const [isDragOver, setIsDragOver] = useState(false)
  const [isFocused, setIsFocused] = useState(false)

  // Sora 模型选择确认对话框状态
  const [showSoraDialog, setShowSoraDialog] = useState(false)
  const [pendingSoraModel, setPendingSoraModel] = useState<string>('')

  const [characterName, setCharacterName] = useState('')
  const [characterImages, setCharacterImages] = useState<File[]>([])
  const [isUploadingCharacter] = useState(false)

  // Character selection
  const [selectedCharacters, setSelectedCharacters] = useState<Array<{
    id: string
    name: string
    image: string
    isDefault?: boolean
  }>>([])

  // Auto/Manual model selection（图片模型默认与 constants 一致）
  const [isAutoModel, setIsAutoModel] = useState(true)
  const [imageModel, setImageModel] = useState<ImageGenerationToolType>(DEFAULT_IMAGE_GENERATION_TOOL)
  const [videoModel, setVideoModel] = useState('seedance_1_0_pro_fast')
  const [lipsyncVideoModel, setLipsyncVideoModel] = useState(DEFAULT_VIDEO_OPTIONS.lipsyncVideoModel)

  // Continuous Mode: all frames linked end-to-end throughout the entire video（与 Create 页默认一致）
  const [isContinuousMode, setIsContinuousMode] = useState(DEFAULT_VIDEO_OPTIONS.enableContinuityMode)
  // Reflection Mode: AI 检查关键帧角色一致性并自动优化（默认关闭）
  const [enableReflectionMode, setEnableReflectionMode] = useState(DEFAULT_VIDEO_OPTIONS.enableKeyframeReflection)

  // Run mode: true = Full Auto, false = Step-by-Step
  const [isFullAuto, setIsFullAuto] = useState(true)

  /** 发送按钮动效：idle | 放大 | 点击 */
  const [sendButtonAnim, setSendButtonAnim] = useState<'idle' | 'enlarge' | 'click'>('idle')
  const [landingExpanded, setLandingExpanded] = useState(false)

  const sizeLandingTextarea = (textarea: HTMLTextAreaElement) => {
    const line = parseFloat(getComputedStyle(textarea).lineHeight) || 24
    textarea.style.height = 'auto'
    const next = Math.max(Math.min(textarea.scrollHeight, line * 8), line)
    textarea.style.height = `${next}px`
    return next > line + 1
  }

  // Auto-resize textarea based on content
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    if (variant === 'landing') {
      const grew = sizeLandingTextarea(textarea)
      setLandingExpanded(grew && prompt.trim().length > 0)
      return
    }
    textarea.style.height = 'auto'
    const newHeight = Math.max(Math.min(textarea.scrollHeight, 300), 100)
    textarea.style.height = `${newHeight}px`
  }, [prompt, variant, selectedWorkflowLabel])

  // 如果配置为不显示 image/music，且当前选中了这些类型，则切换到 video
  useEffect(() => {
    if (!showImageMusicCreation && (selectedMediaType === 'image' || selectedMediaType === 'music')) {
      setSelectedMediaType('video')
    }
  }, [showImageMusicCreation, selectedMediaType])

  // 强制移除 character tab 选项后，如果当前选中了 character，则切换回 video（默认模式）
  useEffect(() => {
    if (selectedMediaType === 'character') {
      setSelectedMediaType('video')
    }
  }, [selectedMediaType])

  // 如果配置为不显示 instant 模式，则强制使用 master 模式
  useEffect(() => {
    if (!showInstantMode && isInstantMode) {
      setIsInstantMode(false)
    }
  }, [showInstantMode, isInstantMode])

  // Fill external prompt into input when it changes
  useEffect(() => {
    if (externalPrompt && externalPrompt.trim() && externalPrompt !== lastExternalPromptRef.current) {
      setPrompt(externalPrompt)
      lastExternalPromptRef.current = externalPrompt
      // Auto-resize textarea after setting prompt
      setTimeout(() => {
        const textarea = textareaRef.current
        if (textarea) {
          if (variant === 'landing') {
            setLandingExpanded(sizeLandingTextarea(textarea))
          } else {
            textarea.style.height = 'auto'
            textarea.style.height = `${Math.max(Math.min(textarea.scrollHeight, 300), 100)}px`
          }
          textarea.focus()
        }
      }, 0)
    }
  }, [externalPrompt])

  const lastExternalFilesRef = useRef<File[] | null>(null)
  useEffect(() => {
    if (!externalFiles || externalFiles.length === 0 || lastExternalFilesRef.current === externalFiles) return
    lastExternalFilesRef.current = externalFiles
    attachments.clear()
    attachments.addFiles(externalFiles)
    // Hook methods are not referentially stable; only react to a new file list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalFiles])

  // 外部触发：发送按钮放大 -> 点击动效 -> 自动发送
  useEffect(() => {
    if (autoSendTrigger == null || autoSendTrigger <= 0 || autoSendTrigger === lastAutoSendTriggerRef.current) return
    lastAutoSendTriggerRef.current = autoSendTrigger
    setSendButtonAnim('enlarge')
    const t1 = setTimeout(() => {
      setSendButtonAnim('click')
    }, 450)
    const t2 = setTimeout(() => {
      setSendButtonAnim('idle')
      void handleSendMessage()
    }, 650)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [autoSendTrigger])

  // 页面加载时自动聚焦到输入框
  useEffect(() => {
    // 延迟一小段时间确保 DOM 已渲染
    const timer = setTimeout(() => {
      if (selectedMediaType === 'character') {
        // Character 模式：聚焦到 characterName 输入框
        characterNameInputRef.current?.focus()
      } else {
        // 其他模式：聚焦到 textarea
        textareaRef.current?.focus()
      }
    }, 100)

    return () =>{  clearTimeout(timer) }
  }, []) // 只在组件挂载时执行一次

  const autoCropUploadedAudioFiles = async (files: File[], targetDurationSec?: number | null) =>
    smartCropUploadedAudioFiles(files, targetDurationSec)

  const getUploadAutoCropTargetSec = () =>
    resolveAutoCropTargetDurationSec(
      (duration[0] || DEFAULT_VIDEO_OPTIONS.duration),
      prompt,
      { panelDurationExplicit: durationExplicitlySetRef.current },
    )

  const syncDurationFromUploadedAudio = async (files: File[]) => {
    const audioFile = files.find(file => isAudioFile(file))
    if (!audioFile) return
    try {
      const sec = await getAudioFileDurationSec(audioFile)
      setDuration([sec])
    } catch (error) {
      console.warn('Failed to read uploaded audio duration:', error)
    }
  }

  const appendUploadedFilesAndOpenAudioCrop = async (files: File[]) => {
    if (files.length === 0) return
    const audioIndex = files.findIndex(file => file.type.startsWith('audio/'))
    const nextAudioFile = audioIndex >= 0 ? files[audioIndex] : null
    const startIndex = attachments.addFiles(files)
    await syncDurationFromUploadedAudio(files)
    if (nextAudioFile) {
      setAudioCropTarget({ index: startIndex + audioIndex, file: nextAudioFile })
      setAudioCropOpen(true)
    }
  }

  // 创建拖拽处理器
  const dragDropHandler = createDragDropHandler(
    setIsDragOver,
    asyncEvent(async (files: File[]) => {
      const { validFiles } = validateFiles(files, uploadedFiles, t)
      if (validFiles.length > 0) {
        await appendUploadedFilesAndOpenAudioCrop(validFiles)
      }
    }),
    () => isGenerating,
    t,
  )

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files)
      const { validFiles } = validateFiles(files, uploadedFiles, t)
      if (validFiles.length > 0) {
        await appendUploadedFilesAndOpenAudioCrop(validFiles)
      }
      e.target.value = ''
    }
  }

  const handleFileRemove = (index: number) => {
    attachments.removeAt(index)
  }

  const handleOpenAudioCrop = (index: number, file: File) => {
    setAudioCropTarget({ index, file })
    setAudioCropOpen(true)
  }

  const handleApplyAudioCrop = (nextFile: File) => {
    if (!audioCropTarget) return
    attachments.replaceAt(audioCropTarget.index, nextFile)
  }

  const handleCharacterImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files)

      const validFiles: File[] = []
      for (const file of files) {
        const fileType = file.type.toLowerCase()
        const fileSize = file.size

        if (!['image/jpeg', 'image/jpg', 'image/png', 'image/webp'].includes(fileType)) {
          toast.error(`${file.name}: ${t('unsupportedFormat')}`)
          continue
        }

        if (fileSize > 10 * 1024 * 1024) {
          toast.error(`${file.name}: ${t('fileSizeLimit')}`)
          continue
        }

        validFiles.push(file)
      }

      setCharacterImages(prev => [...prev, ...validFiles])
      e.target.value = ''
    }
  }

  const handleCharacterImageRemove = (index: number) => {
    setCharacterImages(prev => prev.filter((_, i) => i !== index))
  }

  const handleCharacterUpload = async () => {
    if (!characterName.trim()) {
      toast.error(t('nameRequired'))
      return
    }

    if (characterImages.length === 0) {
      toast.error(t('imagesRequired'))
      return
    }

    toast.error('Character upload is not available in the local agent build.')
  }

  const handleSendMessage = async () => {
    if (!prompt.trim() || isGenerating) {
      return
    }

    setIsGenerating(true)

    let sendDurationPlan: Awaited<ReturnType<typeof resolveSendDurationPlan>>
    try {
      sendDurationPlan = await resolveSendDurationPlan(
        uploadedFiles,
        (duration[0] || DEFAULT_VIDEO_OPTIONS.duration),
        prompt,
        {
          panelDurationExplicit: durationExplicitlySetRef.current,
          messageTexts: [prompt],
        },
      )
    } catch (error) {
      setIsGenerating(false)
      toast.error(error instanceof Error ? error.message : String(error))
      return
    }
    const processedUploadedFiles =
      sendDurationPlan.cropTargetSec != null && uploadedFiles.some(file => isAudioFile(file))
        ? await autoCropUploadedAudioFiles(uploadedFiles, sendDurationPlan.cropTargetSec)
        : uploadedFiles
    processedUploadedFiles.forEach((file, index) => {
      if (file !== uploadedFiles[index]) attachments.replaceAt(index, file)
    })
    let inputFiles
    try {
      inputFiles = await attachments.waitUntilReady()
    } catch (error) {
      setIsGenerating(false)
      toast.error(error instanceof Error ? error.message : t('da.page.uploadPartialFail'))
      return
    }
    const userOptionDurationSec = sendDurationPlan.userOptionDurationSec
    if (
      sendDurationPlan.panelDurationSec != null &&
      sendDurationPlan.panelDurationSec !== duration[0]
    ) {
      setDuration([sendDurationPlan.panelDurationSec])
    }

    // Determine backend tools based on Auto/Manual mode
    const backendVideoTool = isAutoModel
      ? 'auto'
      : (videoModel === 'seedance_1_0_pro_fast' ? 'pollo_seedance'
        : videoModel === 'seedance_1_5_pro_fast' ? 'pollo_seedance_v1_5'
          : videoModel === 'seedance_2_i2v' ? 'seedance_2_i2v'
            : videoModel === 'seedance_2_i2v_turbo' ? 'seedance_2_i2v_turbo'
              : videoModel === 'seedance_2_fast_i2v' ? 'seedance_2_fast_i2v'
                : videoModel === 'seedance_2_fast_i2v_turbo' ? 'seedance_2_fast_i2v_turbo'
                  : videoModel === 'kling_v3_std' ? 'kling_v3_std'
                    : videoModel === 'happyhorse_1_0_i2v' ? 'happyhorse_1_0_i2v'
                      : videoModel === 'happyhorse_1_1_i2v' ? 'happyhorse_1_1_i2v'
                        : videoModel === 'sora' ? 'openai_sora'
                          : 'openai_sora_pro')

    const backendImageTool = isAutoModel ? 'auto' : imageModel

    if (!isInstantMode) {
      const createState: Record<string, unknown> = {
        initialPrompt: prompt,
        uploadedFiles: processedUploadedFiles,
        inputFiles,
        userOption: {
          aspect_ratio: aspectRatio,
          resolution: resolution,
          duration: userOptionDurationSec,
          video_generation_tool: backendVideoTool,
          // auto 时不写入 navigate state，避免 history 里快照旧默认 wan_2_6；Create 页保持 DEFAULT_VIDEO_OPTIONS.lipsyncVideoModel
          ...(lipsyncVideoModel !== 'auto' ? { lipsync_video_tool: lipsyncVideoModel } : {}),
          image_generation_tool: backendImageTool === 'auto'
            ? DEFAULT_IMAGE_GENERATION_TOOL
            : backendImageTool === 'seedream'
              ? 'seedream'
              : backendImageTool === 'nano_banana_pro'
                ? 'nano_banana_pro'
                : backendImageTool === 'nano_banana_2'
                  ? 'nano_banana_2'
                  : backendImageTool === 'gpt_image_2'
                    ? 'gpt_image_2'
                    : 'nano_banana',
          // 首页/create 默认 Default，点模版（如 Lip-sync Music Video）时传模版值
          content_category: externalContentCategory?.trim() ? externalContentCategory : 'Default',
          lipsync_coverage: lipsyncRatio[0],
          continuous_mode: isContinuousMode,
          // ⚠️ 必须传 enable_keyframe_reflection：与 continuous_mode / full_auto 同级，
          //    否则 CreateVideoPage 的 userOption useEffect (line 7398) 因 undefined 跳过更新，
          //    导致首页打开的「反思模式」开关在 create 页被默认值 false 覆盖（看起来像点击没反应）。
          enable_keyframe_reflection: enableReflectionMode,
          full_auto: isFullAuto,
        },
        shouldAutoSend: true,
        automatic_video: Boolean(selectedWorkflowId),
      }
      if (selectedWorkflowId) createState.workflow_id = selectedWorkflowId
      // 与 create 页一致：video 传 auto 由后端路由分析决定类型，image/music 传具体类型
      createState.agentType = selectedMediaType === 'video' ? 'auto' : selectedMediaType
      const lang = routeLang || language
      navigate(`/${lang}/create`, { state: createState })
      setIsGenerating(false)
      return
    }

    const instantState: Record<string, unknown> = {
      prompt,
      uploadedFiles: uploadedFiles,
      aspectRatio: aspectRatio,
      resolution: resolution,
      duration: duration[0],
      videoGenerationTool: backendVideoTool,
      skipGeneration: false,
      imageGenerationTool: backendImageTool === 'auto' ? DEFAULT_IMAGE_GENERATION_TOOL : backendImageTool === 'seedream' ? 'seedream' : backendImageTool === 'nano_banana_pro' ? 'nano_banana_pro' : backendImageTool === 'nano_banana_2' ? 'nano_banana_2' : backendImageTool === 'gpt_image_2' ? 'gpt_image_2' : 'nano_banana',
      nanoBananaModel: backendImageTool === 'nano_banana_pro' ? 'gemini-3-pro-image-preview' : backendImageTool === 'nano_banana_2' ? 'gemini-3.1-flash-image-preview' : backendImageTool === 'gpt_image_2' ? 'gpt-image-2' : 'gemini-2.5-flash-image',
      continuousMode: isContinuousMode,
      enableKeyframeReflection: enableReflectionMode,
      fullAuto: isFullAuto,
    }
    instantState.agentType = selectedMediaType === 'video' ? 'auto' : selectedMediaType
    navigate('/instant-generation', { state: instantState })
    setIsGenerating(false)
  }

  const landingPlaceholder = placeholder || t('homePromptPlaceholder')
  const landingPromptHandlers = {
    onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => setPrompt(e.target.value),
    onFocus: () => setIsFocused(true),
    onBlur: () => setIsFocused(false),
    onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const target = e.target as HTMLTextAreaElement & { composing?: boolean }
      const isComposing = e.nativeEvent?.isComposing || target.composing
      if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
        e.preventDefault()
        handleSendMessage()
      }
    },
    onCompositionStart: (e: React.CompositionEvent<HTMLTextAreaElement>) => {
      const target = e.target as HTMLTextAreaElement & { composing?: boolean }
      target.composing = true
    },
    onCompositionEnd: (e: React.CompositionEvent<HTMLTextAreaElement>) => {
      const target = e.target as HTMLTextAreaElement & { composing?: boolean }
      target.composing = false
    },
    onPaste: async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (isGenerating) return
      const clipboardData = e.clipboardData
      if (!clipboardData) return
      const pasted: File[] = []
      for (let i = 0; i < clipboardData.items.length; i++) {
        const item = clipboardData.items[i]
        if (item.kind !== 'file') continue
        const f = item.getAsFile()
        if (f) pasted.push(normalizeClipboardFile(f))
      }
      if (pasted.length === 0) return
      e.preventDefault()
      const { validFiles } = validateFiles(pasted, uploadedFiles, t)
      if (validFiles.length > 0) {
        await appendUploadedFilesAndOpenAudioCrop(validFiles)
        toast.success(
          validFiles.length === 1
            ? t('pastedImage')
            : t('pastedImages').replace('{count}', String(validFiles.length)),
        )
      }
    },
  }

  if (variant === 'landing') {
    return (
      <div className={`w-full ${className}`}>
        <div
          className={`home-composer relative overflow-hidden ${
            uploadedFiles.length > 0 || landingExpanded ? 'home-composer-expanded' : ''
          } ${isDragOver ? 'border-white/40' : isFocused ? 'border-white/[0.18]' : ''}`}
          onDragOver={dragDropHandler.handleDragOver}
          onDragLeave={dragDropHandler.handleDragLeave}
          onDrop={dragDropHandler.handleDrop}
        >
          {isDragOver && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[inherit] bg-white/10">
              <p className="text-sm font-medium text-white">{t('dropFilesHere')}</p>
            </div>
          )}
          {uploadedFiles.length > 0 && (
            <div className="relative z-[1] flex flex-wrap gap-1.5 px-5 pt-4">
              {uploadedFiles.map((file, index) => (
                <FilePreview
                  key={index}
                  file={file}
                  index={index}
                  onRemove={handleFileRemove}
                  onCropAudio={handleOpenAudioCrop}
                  uploadPercent={attachments.uploadStates[index]?.percent}
                  uploadPhase={attachments.uploadStates[index]?.phase}
                />
              ))}
            </div>
          )}
          <div className="home-composer-row">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isGenerating}
              aria-label={t('uploadFiles')}
              className="home-landing-hit home-composer-disc flex items-center justify-center disabled:opacity-40"
            >
              <Plus className="h-[45%] w-[45%]" strokeWidth={1.3} />
            </button>
            <div className="home-composer-divider" />
            {selectedWorkflowLabel && (
              <button
                type="button"
                className="home-composer-skill"
                onClick={onClearWorkflow}
                aria-label={`${t('homeSkillClear')}: ${selectedWorkflowLabel}`}
              >
                <span className="home-composer-skill-mark">$</span>
                <span className="home-composer-skill-name">{selectedWorkflowLabel}</span>
              </button>
            )}
            <textarea
              ref={textareaRef}
              value={prompt}
              {...landingPromptHandlers}
              placeholder={landingPlaceholder}
              rows={1}
              disabled={isGenerating}
              className="home-composer-input"
            />
            <button
              type="button"
              onClick={handleSendMessage}
              disabled={isGenerating || !prompt.trim()}
              aria-label={t('generate')}
              className={`home-landing-hit home-composer-send flex items-center justify-center disabled:cursor-not-allowed ${
                sendButtonAnim === 'enlarge' ? 'scale-125' : ''
              } ${sendButtonAnim === 'click' ? 'scale-90' : ''}`}
            >
              <ArrowRight className="h-[42%] w-[42%]" strokeWidth={1.9} />
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".jpg,.jpeg,.png,.webp,.wav,.mp3,.aiff,.aac,.ogg,.flac,.mp4,.mpeg,.mov,.avi,.flv,.mpg,.webm,.wmv,.3gpp,audio/mpeg,audio/wav,audio/aiff,audio/aac,audio/ogg,audio/flac,image/png,image/jpeg,image/webp,video/mp4,video/mpeg,video/quicktime,video/avi,video/x-msvideo,video/x-flv,video/mpg,video/webm,video/wmv,video/3gpp"
            className="hidden"
            onChange={handleFileSelect}
          />
        </div>
        <AudioCropDialog
          open={audioCropOpen}
          file={audioCropTarget?.file || null}
          suggestedDurationSec={getUploadAutoCropTargetSec()}
          onOpenChange={setAudioCropOpen}
          onApply={handleApplyAudioCrop}
        />
      </div>
    )
  }

  return (
    <div className={`text-center ${className}`}>
      <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold mb-3 sm:mb-4 text-foreground px-4">
        {title}
      </h1>
      <p className="text-muted-foreground text-base sm:text-lg mb-6 sm:mb-8 px-4">
        {subtitle}
      </p>

      {/* Main Prompt Input */}
      <div className="max-w-4xl mx-auto mt-8 sm:mt-10 md:mt-12">
        {/* Media Type Tabs */}
        {(() => {
          const availableTabs = [
            { type: 'image' as const, icon: Image, label: t('image') },
            { type: 'video' as const, icon: Video, label: t('video') },
            { type: 'music' as const, icon: Music, label: t('music') },
            { type: 'character' as const, icon: User, label: t('character') },
          ]
            .filter(({ type }) => {
            // 去除 Visual element (character) 和 Video 选项
              if (type === 'character' || type === 'video') {
                return false
              }
              // 如果配置为不显示 image/music，则过滤掉这些选项
              if (!showImageMusicCreation) {
                return false
              }
              return true
            })

          // 如果没有可用的tab选项，则不显示tab选择器
          if (availableTabs.length === 0) {
            return null
          }

          return (
            <div className="relative flex justify-around sm:justify-start gap-2 sm:gap-4 md:gap-6 mb-3 sm:mb-4 border-b border-border/30">
              {availableTabs.map(({ type, icon: IconComponent, label }) => (
                <button
                  key={type}
                  onClick={() =>{  setSelectedMediaType(type) }}
                  className={`relative pb-2 sm:pb-3 text-xs sm:text-sm font-medium transition-all duration-300 whitespace-nowrap flex-shrink-0 ${
                    selectedMediaType === type
                      ? 'text-foreground scale-105 sm:scale-110'
                      : 'text-muted-foreground hover:text-foreground hover:scale-102'
                  }`}
                >
                  <div className="flex items-center gap-1 sm:gap-1.5 md:gap-2">
                    <IconComponent
                      className={`w-3.5 h-3.5 sm:w-4 sm:h-4 transition-all duration-500 ease-out ${
                        selectedMediaType === type ? 'scale-110 sm:scale-125 rotate-12' : ''
                      }`}
                      strokeWidth={selectedMediaType === type ? 2.5 : 2}
                    />
                    <span className={`transition-all duration-300 ${
                      selectedMediaType === type ? 'font-semibold text-xs sm:text-sm md:text-base' : ''
                    }`}>
                      {label}
                    </span>
                  </div>
                  {selectedMediaType === type && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-foreground rounded-full" />
                  )}
                </button>
              ))}
            </div>
          )
        })()}

        {/* Input Card */}
        <Card
          className={`relative bg-card/50 backdrop-blur-xl rounded-3xl border-2 overflow-hidden transition-all duration-300 w-full ${
            isDragOver
              ? 'border-pink-400 shadow-xl shadow-pink-500/30 scale-[1.01]'
              : isFocused
                ? 'border-fuchsia-400 shadow-lg shadow-pink-500/20'
                : 'border-fuchsia-400'
          }`}
          onDragOver={dragDropHandler.handleDragOver}
          onDragLeave={dragDropHandler.handleDragLeave}
          onDrop={dragDropHandler.handleDrop}
        >
          {/* Focus glow overlay - lovable style */}
          {isFocused && (
            <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-purple-500/5 via-transparent to-pink-500/5 pointer-events-none" />
          )}

          {/* 拖拽上传提示覆盖层 */}
          {isDragOver && (
            <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary/50 rounded-lg flex items-center justify-center z-10">
              <div className="text-center">
                <Upload className="w-8 h-8 text-primary mx-auto mb-2" />
                <p className="text-sm font-medium text-primary">
                  {t('dropFilesHere')}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t('supportedFormats')}
                </p>
              </div>
            </div>
          )}
          {selectedMediaType === 'character' ? (
            <div className="space-y-4">
              <div>
                <Label htmlFor="characterName" className="text-sm font-medium mb-2 block">
                  {t('characterName')}
                </Label>
                <Input
                  ref={characterNameInputRef}
                  id="characterName"
                  type="text"
                  value={characterName}
                  onChange={(e) =>{  setCharacterName(e.target.value) }}
                  placeholder={t('characterNamePlaceholder')}
                  disabled={isUploadingCharacter}
                  className="text-lg"
                />
              </div>

              <div>
                <Label className="text-sm font-medium mb-2 block">
                  {t('selectImages')}
                </Label>
                <div
                  onClick={() => characterFileInputRef.current?.click()}
                  className="border-2 border-dashed border-border/50 rounded-lg p-8 text-center cursor-pointer hover:border-primary/50 hover:bg-muted/30 transition-all"
                >
                  <Upload className="w-12 h-12 mx-auto mb-3 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground mb-1">
                    {t('describeCharacterContent')}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t('imageFormats')}
                  </p>
                </div>
                <input
                  ref={characterFileInputRef}
                  type="file"
                  multiple
                  accept="image/jpeg,image/jpg,image/png,image/webp"
                  className="hidden"
                  onChange={handleCharacterImageSelect}
                />
              </div>

              {characterImages.length > 0 && (
                <div>
                  <p className="text-sm text-muted-foreground mb-2">
                    {t('imagesSelected').replace('{count}', characterImages.length.toString())}
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
                    {characterImages.map((file, index) => (
                      <div
                        key={index}
                        className="relative group aspect-square rounded-lg overflow-hidden bg-muted"
                      >
                        <img
                          src={URL.createObjectURL(file)}
                          alt={file.name}
                          className="w-full h-full object-cover"
                        />
                        <button
                          onClick={() =>{  handleCharacterImageRemove(index) }}
                          className="absolute top-1 right-1 w-6 h-6 rounded-full bg-destructive/90 hover:bg-destructive flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100"
                          title={t('removeImage')}
                        >
                          <X className="w-3 h-3 text-white" />
                        </button>
                        <div className="absolute bottom-0 left-0 right-0 bg-black/50 p-1">
                          <p className="text-xs text-white truncate">{file.name}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <Button
                onClick={asyncEvent(handleCharacterUpload)}
                disabled={isUploadingCharacter || !characterName.trim() || characterImages.length === 0}
                className="w-full h-12 text-base font-medium"
                size="lg"
              >
                {isUploadingCharacter ? (
                  <>
                    <Upload className="w-5 h-5 mr-2 animate-pulse" />
                    {t('uploading')}
                  </>
                ) : (
                  <>
                    <Upload className="w-5 h-5 mr-2" />
                    {t('uploadCharacter')}
                  </>
                )}
              </Button>
            </div>
          ) : (
            <>
              <div className="px-3 sm:px-6 pt-3 sm:pt-5 pb-2 sm:pb-3 relative z-10">
                <textarea
                  ref={textareaRef}
                  value={prompt}
                  onChange={(e) =>{  setPrompt(e.target.value) }}
                  onFocus={() =>{  setIsFocused(true) }}
                  onBlur={() =>{  setIsFocused(false) }}
                  onKeyDown={(e) => {
                    const target = e.target as HTMLTextAreaElement & { composing?: boolean }
                    const isComposing = e.nativeEvent.isComposing || target.composing
                    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
                      e.preventDefault()
                      void handleSendMessage()
                    }
                  }}
                  onCompositionStart={(e) => {
                    const target = e.target as HTMLTextAreaElement & { composing?: boolean }
                    target.composing = true
                  }}
                  onCompositionEnd={(e) => {
                    const target = e.target as HTMLTextAreaElement & { composing?: boolean }
                    target.composing = false
                  }}
                  onPaste={asyncEvent(async (e) => {
                    if (isGenerating) return
                    const clipboardData = e.clipboardData
                    const pasted: File[] = []
                    for (let i = 0; i < clipboardData.items.length; i++) {
                      const item = clipboardData.items[i]
                      if (!item) continue
                      if (item.kind !== 'file') continue
                      const f = item.getAsFile()
                      if (f) pasted.push(normalizeClipboardFile(f))
                    }
                    if (pasted.length === 0) return
                    e.preventDefault()
                    const { validFiles } = validateFiles(pasted, uploadedFiles, t)
                    if (validFiles.length > 0) {
                      await appendUploadedFilesAndOpenAudioCrop(validFiles)
                      toast.success(
                        validFiles.length === 1
                          ? t('pastedImage')
                          : t('pastedImages').replace('{count}', String(validFiles.length)),
                      )
                    }
                  })}
                  placeholder={
                    selectedMediaType === 'image'
                      ? t('describeImageContent')
                      : selectedMediaType === 'music'
                        ? t('describeMusicContent')
                        : (selectedMediaType as string) === 'character'
                          ? t('describeCharacterContent')
                          : t('describeYourIdeasHere')
                  }
                  className="min-h-[60px] sm:min-h-[80px] border-0 bg-transparent resize-none text-sm sm:text-base placeholder:text-muted-foreground/60 focus-visible:ring-0 focus-visible:ring-offset-0 focus:outline-none outline-none w-full"
                  disabled={isGenerating}
                />

                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".jpg,.jpeg,.png,.webp,.wav,.mp3,.aiff,.aac,.ogg,.flac,.mp4,.mpeg,.mov,.avi,.flv,.mpg,.webm,.wmv,.3gpp,audio/mpeg,audio/wav,audio/aiff,audio/aac,audio/ogg,audio/flac,image/png,image/jpeg,image/webp,video/mp4,video/mpeg,video/quicktime,video/avi,video/x-msvideo,video/x-flv,video/mpg,video/webm,video/wmv,video/3gpp"
                  className="hidden"
                  onChange={asyncEvent(handleFileSelect)}
                />
              </div>

              {/* Uploaded Files Display with Previews */}
              {uploadedFiles.length > 0 && (
                <div className="px-3 sm:px-6 flex flex-wrap gap-1.5 sm:gap-2 pb-2 overflow-x-auto">
                  {uploadedFiles.map((file, index) => (
                    <FilePreview
                      key={index}
                      file={file}
                      index={index}
                      onRemove={handleFileRemove}
                      onCropAudio={handleOpenAudioCrop}
                      uploadPercent={attachments.uploadStates[index]?.percent}
                      uploadPhase={attachments.uploadStates[index]?.phase}
                    />
                  ))}
                </div>
              )}
              <AudioCropDialog
                open={audioCropOpen}
                file={audioCropTarget?.file || null}
                suggestedDurationSec={getUploadAutoCropTargetSec()}
                onOpenChange={setAudioCropOpen}
                onApply={handleApplyAudioCrop}
              />
            </>
          )}

          {/* Bottom Toolbar - lovable style */}
          {selectedMediaType !== 'character' && (
            <div className="px-2 sm:px-4 pb-3 sm:pb-4 flex items-center justify-between gap-1">
              {/* Left: Attachment + Character */}
              <div className="flex items-center gap-2 sm:gap-3 shrink-0">
                {/* Attachment button */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isGenerating}
                      className="flex items-center gap-2 sm:gap-2.5 px-3 sm:px-4 py-2 sm:py-2.5 rounded-full bg-gradient-to-br from-blue-600/90 via-purple-600/90 to-indigo-700/90 hover:from-blue-500/90 hover:via-purple-500/90 hover:to-indigo-600/90 text-white transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg"
                    >
                      <Upload className="w-4 h-4 sm:w-5 sm:h-5 flex-shrink-0" />
                      <span className="text-xs sm:text-sm font-medium whitespace-nowrap">{t('uploadSongOrCharacters')}</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} className="z-[9999]">
                    {t('uploadSongOrCharacters')}
                  </TooltipContent>
                </Tooltip>

                {/* Character Select button */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex">
                      <CharacterSelectPopover
                        onSelect={asyncEvent(async (characters) => {
                          const prevIds = new Set(selectedCharacters.map(c => c.id))
                          const newIds = new Set(characters.map(c => c.id))
                          const added = characters.filter(c => !prevIds.has(c.id))
                          const removed = selectedCharacters.filter(c => !newIds.has(c.id))

                          setSelectedCharacters(characters)

                          if (removed.length > 0) {
                            const removedIds = new Set(removed.map(c => c.id))
                            attachments.removeWhere((file) => {
                              const match = file.name.match(/^character-(.+)\.(png|jpg|jpeg|webp)$/i)
                              return Boolean(match?.[1] && removedIds.has(match[1]))
                            })
                          }

                          if (added.length > 0) {
                            const newFiles: File[] = []
                            for (const c of added) {
                              try {
                                const res = await fetch(c.image)
                                const blob = await res.blob()
                                const ext = blob.type === 'image/jpeg' ? '.jpg' : '.png'
                                const file = new File([blob], `character-${c.id}${ext}`, { type: blob.type })
                                newFiles.push(file)
                              } catch (e) {
                                console.warn('Failed to fetch character image:', c.name, e)
                              }
                            }
                            if (newFiles.length > 0) {
                              attachments.addFiles(newFiles)
                            }
                          }
                        })}
                        selectedCharacters={selectedCharacters}
                      >
                        <button
                          type="button"
                          disabled={isGenerating}
                          className="flex items-center gap-2 sm:gap-2.5 px-3 sm:px-4 py-2 sm:py-2.5 rounded-full bg-gradient-to-br from-purple-600/90 via-pink-600/90 to-rose-700/90 hover:from-purple-500/90 hover:via-pink-500/90 hover:to-rose-600/90 text-white transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg"
                        >
                          <User className="w-4 h-4 sm:w-5 sm:h-5 flex-shrink-0" />
                          <span className="text-xs sm:text-sm font-medium whitespace-nowrap">{t('pickCharacter')}</span>
                        </button>
                      </CharacterSelectPopover>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} className="z-[9999]">
                    {t('pickCharacter')}
                  </TooltipContent>
                </Tooltip>
              </div>

              {/* Right: Mode switch (capsule) + Options + Send */}
              <div className="flex items-center gap-1 sm:gap-1.5 min-w-0">
                <span className="inline-flex rounded-full border border-border bg-muted p-0.5 dark:bg-[oklch(24%_0.02_265)] dark:border-white/10 shrink min-w-0">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        disabled={isGenerating}
                        onClick={() =>{  setIsFullAuto(true) }}
                        className={`min-w-0 px-1.5 sm:px-2.5 py-2 sm:py-2.5 rounded-full text-[10px] sm:text-xs font-medium transition-colors truncate ${
                          isFullAuto
                            ? 'bg-white/50 backdrop-blur-sm text-foreground shadow-[inset_0_1px_0_0_rgba(255,255,255,0.4)] dark:bg-white/15 dark:backdrop-blur-sm dark:text-gray-200 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]'
                            : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                        }`}
                      >
                        {t('fullAuto')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={6} className="z-[9999] max-w-[16rem]">
                      {t('fullAutoDesc')}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        disabled={isGenerating}
                        onClick={() =>{  setIsFullAuto(false) }}
                        className={`min-w-0 px-1.5 sm:px-2.5 py-2 sm:py-2.5 rounded-full text-[10px] sm:text-xs font-medium transition-colors truncate ${
                          !isFullAuto
                            ? 'bg-white/50 backdrop-blur-sm text-foreground shadow-[inset_0_1px_0_0_rgba(255,255,255,0.4)] dark:bg-white/15 dark:backdrop-blur-sm dark:text-gray-200 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]'
                            : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                        }`}
                      >
                        {t('stepByStep')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={6} className="z-[9999] max-w-[16rem]">
                      {t('stepByStepDesc')}
                    </TooltipContent>
                  </Tooltip>
                </span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex">
                      <Popover>
                        <PopoverTrigger asChild>
                          <button className="flex items-center justify-center h-10 sm:h-11 w-10 sm:w-11 rounded-full border border-border bg-transparent hover:bg-muted/50 hover:border-border/80 text-muted-foreground hover:text-foreground transition-all duration-200">
                            <OptionsIconCustom className="w-4 h-4" />
                          </button>
                        </PopoverTrigger>
                        <PopoverContent
                          side="bottom"
                          align="end"
                          sideOffset={6}
                          collisionPadding={16}
                          className="w-[min(20rem,92vw)] bg-popover/95 backdrop-blur-xl border border-border shadow-lg dark:bg-[#121212]/95 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.06)] z-50 p-4 rounded-xl text-foreground dark:text-gray-300"
                        >
                          <VideoOptionsPanel
                            duration={duration}
                            onDurationChange={setDuration}
                            resolution={resolution}
                            onResolutionChange={setResolution}
                            aspectRatio={aspectRatio}
                            onAspectRatioChange={setAspectRatio}
                            lipsyncCoverage={lipsyncRatio[0] ?? 100}
                            onLipsyncCoverageChange={(v) =>{  setLipsyncRatio([v]) }}
                            isAutoModel={isAutoModel}
                            onAutoModelChange={setIsAutoModel}
                            imageGenerationTool={imageModel}
                            onImageGenerationToolChange={setImageModel}
                            videoModel={videoModel}
                            onVideoModelChange={(v) =>{  setVideoModel(v) }}
                            lipsyncVideoModel={lipsyncVideoModel}
                            onLipsyncVideoModelChange={(v) =>{  setLipsyncVideoModel(v) }}
                            enableContinuityMode={isContinuousMode}
                            onEnableContinuityModeChange={setIsContinuousMode}
                            enableKeyframeReflection={enableReflectionMode}
                            onEnableKeyframeReflectionChange={setEnableReflectionMode}
                            isGenerating={isGenerating}
                            onSoraSelect={(model) => {
                              setPendingSoraModel(model === 'Sora2' ? 'sora' : 'sora2_pro')
                              setShowSoraDialog(true)
                            }}
                          />
                        </PopoverContent>
                      </Popover>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} className="z-[9999]">
                    {t('options')}
                  </TooltipContent>
                </Tooltip>
                {/* Send Button */}
                <Button
                  onClick={asyncEvent(handleSendMessage)}
                  disabled={isGenerating || !prompt.trim()}
                  size="icon"
                  className={`h-10 sm:h-11 w-10 sm:w-11 rounded-full bg-gradient-to-br from-pink-500 via-purple-500 to-violet-600 text-white shadow-lg hover:shadow-xl hover:scale-105 hover:opacity-95 transition-all duration-200 disabled:opacity-50 disabled:hover:scale-100 ${
                    sendButtonAnim === 'enlarge' ? 'scale-125 shadow-xl' : ''
                  } ${sendButtonAnim === 'click' ? 'scale-90' : ''}`}
                >
                  <Send className="w-4 h-4" />
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Sora 模型选择确认对话框 */}
      <AlertDialog open={showSoraDialog} onOpenChange={setShowSoraDialog}>
        <AlertDialogContent className="max-w-[90vw] sm:max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('soraModelWarningTitle') || 'Sora Model Notice'}</AlertDialogTitle>
            <AlertDialogDescription className="text-left">
              {t('soraRealPersonWarning') ||
                'Note: Sora models currently do not support generating videos with real people. Please use other models for real person content.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() =>{  setShowSoraDialog(false) }}>
              {t('cancel') || 'Cancel'}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setVideoModel(pendingSoraModel)
                setIsAutoModel(false)
                setShowSoraDialog(false)
                setPendingSoraModel('')
              }}
            >
              {t('continue') || 'Continue'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export default GenerationBox
