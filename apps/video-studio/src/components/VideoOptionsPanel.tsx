/**
 * 首页 GenerationBox 与 Create 页 MessageArea 共用的视频选项面板。
 * 样式与逻辑统一，修改一处即可同步两边。
 * 分辨率/宽高比选项由后端 capabilities 接口按当前 image/video 工具返回，Create 与首页共用同一套逻辑。
 */
import { useEffect, useMemo } from 'react'
import { useLanguage } from '@/i18n/LanguageContext'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { RectangleHorizontal, RectangleVertical, Square, ChevronDown } from 'lucide-react'
import {
  useVideoOptionsCapabilities,
  getEffectiveResolutionOptions,
  getEffectiveAspectRatioOptions,
} from '@/hooks/useVideoOptionsCapabilities'
// ⚠️ 非组件常量与映射放在 .constants.ts 中，避免 .tsx 组件文件混 export 非组件
//    导致 vite-plugin-react-swc Fast Refresh 失败（详见 VideoOptionsPanel.constants.ts 注释）
import { VIDEO_MODEL_OPTIONS } from './VideoOptionsPanel.constants'
import type { ImageGenerationToolType } from '@/constants/defaults'

const IMAGE_MODEL_OPTIONS = [
  { value: 'seedream', label: 'Seedream' },
  { value: 'nano_banana', label: 'Nano Banana' },
  { value: 'nano_banana_2', label: 'Nano Banana 2' },
  { value: 'nano_banana_pro', label: 'Nano Banana Pro' },
  { value: 'gpt_image_2', label: 'GPT Image 2' },
] as const

const LIPSYNC_VIDEO_MODEL_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'ltx_2_3', label: 'LTX 2.3 Lipsync' },
  { value: 'kling_v2_ai_avatar_pro', label: 'Kling V2 AI Avatar Pro' },
  { value: 'wan_2_2_speech_to_video', label: 'WAN 2.2 Speech-to-Video' },
  { value: 'wan_2_6_flash', label: 'Wan 2.6 Flash' },
] as const

/** 口型下拉展示名：与 capabilities 接口返回解耦，去掉 WaveSpeed 等供应商前缀 */
const LIPSYNC_DISPLAY_LABEL_BY_VALUE: Record<string, string> = Object.fromEntries(
  LIPSYNC_VIDEO_MODEL_OPTIONS.map(o => [o.value, o.label]),
)

function normalizeLipsyncSelectOption(opt: { value: string; label: string }): { value: string; label: string } | null {
  if (opt.value === 'wan_2_5') return null
  const byValue = LIPSYNC_DISPLAY_LABEL_BY_VALUE[opt.value]
  if (byValue) return { value: opt.value, label: byValue }
  const stripped = opt.label.replace(/^WaveSpeed\s+/i, '').trim()
  return { value: opt.value, label: stripped || opt.label }
}

interface VideoOptionsPanelProps {
  duration: number[]
  onDurationChange: (value: number[]) => void
  resolution: '480p' | '720p' | '1080p'
  onResolutionChange: (value: '480p' | '720p' | '1080p') => void
  aspectRatio: '16:9' | '1:1' | '9:16'
  onAspectRatioChange: (value: '16:9' | '1:1' | '9:16') => void
  lipsyncCoverage: number
  onLipsyncCoverageChange: (value: number) => void
  /** 是否自动推荐（true=只显示按钮，false=展开图像+视频两个 Select），两边一致 */
  isAutoModel: boolean
  onAutoModelChange: (value: boolean) => void
  imageGenerationTool: ImageGenerationToolType
  onImageGenerationToolChange: (value: ImageGenerationToolType) => void
  /** 视频模型 value（seedance_1_0_pro_fast 等），两边一致 */
  videoModel: string
  onVideoModelChange: (value: string) => void
  /** 口型视频模型 value（ltx_2_3 / wan_2_6_flash 等），仅对口型镜头生效 */
  lipsyncVideoModel: string
  onLipsyncVideoModelChange: (value: string) => void
  enableContinuityMode: boolean
  onEnableContinuityModeChange: (value: boolean) => void
  enableKeyframeReflection: boolean
  onEnableKeyframeReflectionChange: (value: boolean) => void
  isGenerating?: boolean
  /** 是否显示托管方式（完全托管/部分托管），Create 页传 true */
  showRunMode?: boolean
  autoContinueOnInterrupt?: boolean
  onAutoContinueOnInterruptChange?: (value: boolean) => void
  /** 选择 Sora 时由父组件打开确认框，参数为 "Sora2" | "Sora2 Pro" */
  onSoraSelect?: (model: string) => void
}

export function VideoOptionsPanel({
  duration,
  onDurationChange,
  resolution,
  onResolutionChange,
  aspectRatio,
  onAspectRatioChange,
  lipsyncCoverage,
  onLipsyncCoverageChange,
  isAutoModel,
  onAutoModelChange,
  imageGenerationTool,
  onImageGenerationToolChange,
  videoModel,
  onVideoModelChange,
  lipsyncVideoModel,
  onLipsyncVideoModelChange,
  enableContinuityMode,
  onEnableContinuityModeChange,
  enableKeyframeReflection,
  onEnableKeyframeReflectionChange,
  isGenerating = false,
  showRunMode = false,
  autoContinueOnInterrupt = true,
  onAutoContinueOnInterruptChange,
  onSoraSelect,
}: VideoOptionsPanelProps) {
  const { t } = useLanguage()
  const imageToolForApi = isAutoModel ? 'auto' : imageGenerationTool
  const videoToolForApi = isAutoModel ? 'auto' : videoModel
  const { capabilities } = useVideoOptionsCapabilities(imageToolForApi, videoToolForApi, lipsyncVideoModel)
  const resolutionOptions = getEffectiveResolutionOptions(capabilities)
  const aspectRatioOptions = getEffectiveAspectRatioOptions(capabilities)
  const lipsyncSelectOptions = useMemo<{ value: string; label: string }[]>(() => {
    const raw: { value: string; label: string }[] =
      capabilities?.lipsync_video_tools && capabilities.lipsync_video_tools.length > 0
        ? capabilities.lipsync_video_tools
        : [...LIPSYNC_VIDEO_MODEL_OPTIONS]
    const normalized = raw
      .map(o => normalizeLipsyncSelectOption(o))
      .filter((o): o is { value: string; label: string } => o != null)
    return normalized.length > 0 ? normalized : [...LIPSYNC_VIDEO_MODEL_OPTIONS]
  }, [capabilities?.lipsync_video_tools])

  useEffect(() => {
    if (resolutionOptions.length && !resolutionOptions.some(r => r.value === resolution)) {
      const first = resolutionOptions[0]
      if (first) onResolutionChange(first.value as '480p' | '720p' | '1080p')
    }
  }, [resolutionOptions, resolution, onResolutionChange])

  useEffect(() => {
    if (aspectRatioOptions.length && !aspectRatioOptions.some(r => r.value === aspectRatio)) {
      const first = aspectRatioOptions[0]
      if (first) onAspectRatioChange(first.value as '16:9' | '1:1' | '9:16')
    }
  }, [aspectRatioOptions, aspectRatio, onAspectRatioChange])

  useEffect(() => {
    if (lipsyncVideoModel === 'wan_2_5') {
      onLipsyncVideoModelChange('wan_2_6_flash')
    }
  }, [lipsyncVideoModel, onLipsyncVideoModelChange])

  return (
    <div className="flex flex-col rounded-lg" style={{ maxHeight: 'min(65vh, 480px)' }}>
      {/* Duration - 固定在顶部 */}
      <div className="flex-shrink-0 pb-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('duration')}</h4>
            <span className="text-xs font-medium">{duration[0]}s</span>
          </div>
          <Slider
            value={duration}
            onValueChange={onDurationChange}
            min={5}
            max={300}
            step={5}
            thumbStyle="minimal"
            className="flex-1 [&_.bg-primary]:bg-gradient-to-r [&_.bg-primary]:from-pink-500 [&_.bg-primary]:via-purple-500 [&_.bg-primary]:to-violet-600"
            disabled={isGenerating}
          />
        </div>
      </div>

      <div className="border-t border-border flex-shrink-0" />

      <div
        className="overflow-y-auto overflow-x-hidden overscroll-contain -mx-4 px-4 flex-1 min-h-0"
        style={{ maxHeight: 'min(calc(65vh - 120px), 360px)' }}
      >
        {/* Resolution：由 capabilities 驱动，Create 与首页共用 */}
        <div className="space-y-2 py-4">
          <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('resolution')}</h4>
          <div className="flex rounded-lg overflow-hidden bg-muted p-0.5 dark:bg-[oklch(24%_0.02_265)]">
            {resolutionOptions.map((opt, i) => (
              <button
                key={opt.value}
                type="button"
                onClick={() =>{  onResolutionChange(opt.value as '480p' | '720p' | '1080p') }}
                disabled={isGenerating}
                className={`flex-1 min-w-0 py-1.5 text-xs font-medium transition-colors ${
                  i === 0 ? 'rounded-l-md' : i === resolutionOptions.length - 1 ? 'rounded-r-md' : ''
                } ${
                  resolution === opt.value
                    ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 text-white shadow-sm'
                    : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {capabilities?.warnings.length ? (
            <p className="text-[10px] text-muted-foreground dark:text-gray-500 mt-1">
              {capabilities.warnings.join(' ')}
            </p>
          ) : null}
        </div>

        <div className="border-t border-border" />

        {/* Orientation：由 capabilities 驱动 */}
        <div className="space-y-2 py-4">
          <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('orientation')}</h4>
          <div className="flex rounded-lg overflow-hidden bg-muted p-0.5 dark:bg-[oklch(24%_0.02_265)]">
            {aspectRatioOptions.map((opt, i) => (
              <button
                key={opt.value}
                type="button"
                disabled={isGenerating}
                onClick={() =>{  onAspectRatioChange(opt.value as '16:9' | '1:1' | '9:16') }}
                className={`flex-1 min-w-0 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium transition-colors ${
                  i === 0 ? 'rounded-l-md' : i === aspectRatioOptions.length - 1 ? 'rounded-r-md' : ''
                } ${
                  aspectRatio === opt.value
                    ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 text-white shadow-sm'
                    : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                }`}
              >
                {opt.value === '16:9' ? (
                  <RectangleHorizontal className="w-4 h-4 flex-shrink-0" />
                ) : opt.value === '1:1' ? (
                  <Square className="w-4 h-4 flex-shrink-0" />
                ) : (
                  <RectangleVertical className="w-4 h-4 flex-shrink-0" />
                )}
                <span>
                  {opt.value === '16:9' ? t('landscape') : opt.value === '1:1' ? t('square') : t('portrait')}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="border-t border-border" />

        {/* Lipsync */}
        <div className="space-y-2 py-4">
          <div className="flex items-center justify-between">
            <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('lipsyncRatio')}</h4>
            <span className="text-xs font-medium">{lipsyncCoverage}%</span>
          </div>
          <Slider
            value={[lipsyncCoverage]}
            onValueChange={(v) => { if (v[0] !== undefined) onLipsyncCoverageChange(v[0]) }}
            min={0}
            max={100}
            step={1}
            thumbStyle="minimal"
            className="flex-1 [&_.bg-primary]:bg-gradient-to-r [&_.bg-primary]:from-pink-500 [&_.bg-primary]:via-purple-500 [&_.bg-primary]:to-violet-600"
            disabled={isGenerating}
          />
        </div>

        <div className="border-t border-border" />

        {/* Model - 两边一致：自动推荐按钮 + 展开后并排图像模型、视频模型两个 Select，z-[200] 避免被遮挡 */}
        <div className="space-y-2 py-4">
          <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('model')}</h4>
          <button
            type="button"
            disabled={isGenerating}
            onClick={() =>{  onAutoModelChange(!isAutoModel) }}
            className={`w-full px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-between transition-colors ${
              isAutoModel
                ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 text-white'
                : 'bg-muted text-foreground hover:bg-muted/80 dark:bg-[oklch(24%_0.02_265)] dark:text-gray-300 dark:hover:bg-[oklch(28%_0.02_265)]'
            }`}
          >
            <span>{t('autoRecommended')}</span>
            <ChevronDown className={`w-4 h-4 shrink-0 transition-transform duration-200 ${!isAutoModel ? 'rotate-180' : ''}`} />
          </button>
          {!isAutoModel && (
            <div className="flex gap-3 pt-2">
              <div className="flex-1 min-w-0 space-y-1.5">
                <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('imageModel')}</h4>
                <Select
                  value={imageGenerationTool}
                  onValueChange={(v) =>{  onImageGenerationToolChange(v as ImageGenerationToolType) }}
                  disabled={isGenerating}
                >
                  <SelectTrigger className="h-8 rounded-lg border border-input bg-muted text-foreground text-xs [&>svg]:size-3.5 dark:border-white/10 dark:bg-[oklch(24%_0.02_265)] dark:text-gray-300">
                    <SelectValue placeholder={t('imageModelPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent className="z-[200] border border-border bg-popover text-foreground dark:border-white/10 dark:bg-[oklch(13%_0.006_265)] dark:text-gray-300">
                    {IMAGE_MODEL_OPTIONS.map(model => (
                      <SelectItem
                        key={model.value}
                        value={model.value}
                        className="text-xs focus:bg-muted focus:text-foreground dark:focus:bg-[oklch(24%_0.02_265)] dark:focus:text-gray-100"
                      >
                        {model.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 min-w-0 space-y-1.5">
                <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('videoModel')}</h4>
                <Select
                  value={videoModel}
                  onValueChange={(v) => {
                    if (v === 'sora' || v === 'sora2_pro') {
                      onSoraSelect?.(v === 'sora' ? 'Sora2' : 'Sora2 Pro')
                    } else {
                      onVideoModelChange(v)
                    }
                  }}
                  disabled={isGenerating}
                >
                  <SelectTrigger className="h-8 rounded-lg border border-input bg-muted text-foreground text-xs [&>svg]:size-3.5 dark:border-white/10 dark:bg-[oklch(24%_0.02_265)] dark:text-gray-300">
                    <SelectValue placeholder={t('videoModelPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent className="z-[200] border border-border bg-popover text-foreground dark:border-white/10 dark:bg-[oklch(13%_0.006_265)] dark:text-gray-300">
                    {VIDEO_MODEL_OPTIONS.map(model => (
                      <SelectItem
                        key={model.value}
                        value={model.value}
                        className="text-xs focus:bg-muted focus:text-foreground dark:focus:bg-[oklch(24%_0.02_265)] dark:focus:text-gray-100"
                      >
                        {model.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 min-w-0 space-y-1.5">
                <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('lipsyncVideoModel')}</h4>
                <Select
                  value={lipsyncVideoModel}
                  onValueChange={(v) =>{  onLipsyncVideoModelChange(v) }}
                  disabled={isGenerating}
                >
                  <SelectTrigger className="h-8 rounded-lg border border-input bg-muted text-foreground text-xs [&>svg]:size-3.5 dark:border-white/10 dark:bg-[oklch(24%_0.02_265)] dark:text-gray-300">
                    <SelectValue placeholder={t('lipsyncVideoModelPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent className="z-[200] border border-border bg-popover text-foreground dark:border-white/10 dark:bg-[oklch(13%_0.006_265)] dark:text-gray-300">
                    {lipsyncSelectOptions.map(model => (
                      <SelectItem
                        key={model.value}
                        value={model.value}
                        className="text-xs focus:bg-muted focus:text-foreground dark:focus:bg-[oklch(24%_0.02_265)] dark:focus:text-gray-100"
                      >
                        {model.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-border" />

        {/* Continuous Mode */}
        <div className="space-y-2 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('continuousMode')}</h4>
              <p className="text-xs text-muted-foreground dark:text-gray-500 mt-0.5">{t('continuousModeDesc')}</p>
            </div>
            <Switch
              checked={enableContinuityMode}
              onCheckedChange={onEnableContinuityModeChange}
              disabled={isGenerating}
              className="shrink-0"
            />
          </div>
        </div>

        <div className="border-t border-border" />

        {/* Reflection Mode */}
        {/* ⚠️ 反思模式开关：不锁 disabled={isGenerating}。
            原因：MessageArea 传入的 isGenerating = effectiveIsGenerating = isGenerating || isTodoTaskRunning，
            只要 todo 还在 running/queued/pending（如刚发完一条消息），整个面板就全锁，
            用户无法切换反思模式（用户反馈「create页面 点击还是没反应」即此）。
            而反思模式仅在下次 submit 时通过 user_option.enable_keyframe_reflection 读取（后端
            keyframe_reflection_service.keyframe_reflection_node 从 run 启动时的 state 快照里取），
            当前 run 的 user_option 已 immutable，中途切换不会影响正在运行的反思节点。 */}
        <div className="space-y-2 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('reflectionMode')}</h4>
              <p className="text-xs text-muted-foreground dark:text-gray-500 mt-0.5">{t('reflectionModeDesc')}</p>
            </div>
            <Switch
              checked={enableKeyframeReflection}
              onCheckedChange={onEnableKeyframeReflectionChange}
              className="shrink-0"
            />
          </div>
        </div>

        {showRunMode && onAutoContinueOnInterruptChange != null && (
          <>
            <div className="border-t border-border" />
            <div className="space-y-2 py-4">
              <h4 className="font-medium text-xs text-muted-foreground dark:text-gray-400">{t('runMode')}</h4>
              <div className="flex rounded-lg overflow-hidden bg-muted p-0.5 dark:bg-[oklch(24%_0.02_265)]">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      disabled={isGenerating}
                      onClick={() =>{  onAutoContinueOnInterruptChange(true) }}
                      className={`flex-1 min-w-0 py-1.5 text-xs font-medium transition-colors rounded-l-md ${
                        autoContinueOnInterrupt
                          ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 text-white shadow-sm'
                          : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                      }`}
                    >
                      {t('fullAuto')}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} className="z-[210] max-w-[16rem]">
                    {t('fullAutoDesc')}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      disabled={isGenerating}
                      onClick={() =>{  onAutoContinueOnInterruptChange(false) }}
                      className={`flex-1 min-w-0 py-1.5 text-xs font-medium transition-colors rounded-r-md ${
                        !autoContinueOnInterrupt
                          ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 text-white shadow-sm'
                          : 'text-foreground hover:bg-muted-foreground/10 dark:text-gray-300 dark:hover:bg-white/5'
                      }`}
                    >
                      {t('stepByStep')}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} className="z-[210] max-w-[16rem]">
                    {t('stepByStepDesc')}
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </>
        )}

        <div className="border-t border-border" />
      </div>

      {/* Summary bar */}
      <div className="pt-2 border-t border-border flex-shrink-0 mt-2">
        <div className="flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-muted text-foreground text-xs dark:bg-[oklch(24%_0.02_265)] dark:text-white">
          <span className="font-medium">{duration[0]}s</span>
          <span className="font-medium">{resolution}</span>
          {aspectRatio === '16:9' ? (
            <RectangleHorizontal className="w-3 h-3 flex-shrink-0" />
          ) : aspectRatio === '1:1' ? (
            <Square className="w-3 h-3 flex-shrink-0" />
          ) : (
            <RectangleVertical className="w-3 h-3 flex-shrink-0" />
          )}
          <span className="font-medium">{isAutoModel ? t('auto') : t('manual')}</span>
        </div>
      </div>
    </div>
  )
}
