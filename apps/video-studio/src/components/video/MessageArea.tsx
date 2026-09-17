import { asyncEvent } from '../../utils/asyncEvent'
import { displayValue } from '@/utils/displayValue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { validateFiles, createDragDropHandler, normalizeClipboardFile } from '@/utils/fileUploadUtils'
import {
  isPaymentTopUpAction,
  parseActionSuggestions,
  stripActionSuggestionsFromChatContent,
  type ActionSuggestionItem,
} from '@/utils/actionSuggestions'
import { extractGeneratedVideoItems } from '@/utils/videoGenResults'
import { remainingSecondsUntil } from '@/utils/interruptAutoResume'
import { interpolate } from '@/features/deep-agent-v2/labels'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { VideoOptionsPanel } from '@/components/VideoOptionsPanel'
// ⚠️ 非组件映射必须从 .constants 文件 import，避免触发 vite-plugin-react-swc Fast Refresh 失败
import { VIDEO_MODEL_LABEL_TO_VALUE, VIDEO_MODEL_VALUE_TO_LABEL } from '@/components/VideoOptionsPanel.constants'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { VideoWithCleanup } from '@/components/ui/VideoWithCleanup'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { splitCollage, downloadBlob, downloadAllTiles, addLogoToImage, type TileInfo } from '@/utils/collageSplitter'
import { MobileSplitCard } from './MobileSplitCard'
import { resolveKeyframeDisplayMetrics } from './keyframeDisplayUtils'
import {
  SmartClipPanel,
  type SmartClipPayload,
  type SmartClipDecision,
  isSmartClipReadyForInterrupt,
  buildRecommendedSmartClipDecision,
} from './SmartClipPanel'
import { resolveAutoCropTargetDurationSec } from '@/utils/targetVideoDuration'
import ReactMarkdown from 'react-markdown'
import { Send, MessageSquare, X, Loader2, Square, Clock, ChevronDown, Upload, CheckCircle2, CheckCircle, Plus, Download, Share2, Scissors, ZoomIn, Minus, Copy, ArrowLeft, ArrowRight, MessageCircle, Sparkles, AlertTriangle } from 'lucide-react'
import { useRef, useState, useEffect, useCallback, useMemo } from 'react'
import { useLanguage } from '@/i18n/LanguageContext'
import { getDisplayPromptForUserMessage, PROMPT_MAPPINGS, PROMPT_MAPPINGS_FOR_CREATE_PAGE } from '@/utils/promptMapping'
import { toast } from 'sonner'
import { FilePreview } from '@/components/FilePreview'
import { AudioCropDialog } from '@/components/AudioCropDialog'
import { TaskStatus } from '@/types/api'
import { DEFAULT_IMAGE_GENERATION_TOOL, DEFAULT_VIDEO_OPTIONS } from '@/constants/defaults'
import { agentApi } from '@/services/api'
import aiAvatar from '@/assets/ai-avatar-capybara.png'
import userPromptAvatar from '@/assets/user-prompt-avatar.png'

import type {
  ChatMessage as Message, ChatEventData, InterruptData, MediaRecord, MediaVersion,
  KeyframeData, VideoData, CharacterData, MusicData, RegenerationItem,
} from './chatTypes'
import type { ComponentProps } from 'react'
import type { TranslationKey } from '@/i18n/translations'

/** 暂停点倒计时：依赖后端 auto_resume_at，与 worker 入队延迟对齐。 */
function InterruptCountdown({
  deadlineAt,
  onZero,
  labelAfter,
}: {
  deadlineAt?: string | null
  onZero: () => void
  labelAfter?: string
}) {
  const onZeroRef = useRef(onZero)
  onZeroRef.current = onZero
  const firedRef = useRef(false)

  const [left, setLeft] = useState<number | null>(() =>
    deadlineAt ? remainingSecondsUntil(deadlineAt) : null,
  )

  useEffect(() => {
    firedRef.current = false
    if (!deadlineAt) {
      setLeft(null)
      return
    }
    const tick = () => {
      const next = remainingSecondsUntil(deadlineAt)
      setLeft(next)
      if (next <= 0 && !firedRef.current) {
        firedRef.current = true
        onZeroRef.current()
      }
    }
    tick()
    const id = setInterval(tick, 1000)
    return () =>{  clearInterval(id) }
  }, [deadlineAt])

  if (!deadlineAt || left == null) {
    return (
      <span className="text-sm text-amber-700 dark:text-amber-300">
        …
      </span>
    )
  }
  if (left <= 0) return <span className="text-sm text-amber-600">{labelAfter || ''}</span>
  return (
    <span className="text-sm text-amber-700 dark:text-amber-300">
      {left}s {labelAfter || ''}
    </span>
  )
}

/** 与 LazyStoryboardsSection 同源：keyframes-by-thread 轮询数据，供 todo 在 DB 无 keyframe_generation_progress 时回填分母/分子 */
function keyframeTodoFallbackFromApi(keyframesData: KeyframeData | undefined): {
  completed: number
  total: number
} | null {
  const list = keyframesData?.keyframes
  if (!Array.isArray(list) || list.length === 0) return null
  const { expectedRecordTotal: expectedTotal } = resolveKeyframeDisplayMetrics(keyframesData)
  if (expectedTotal <= 0) return null
  let completed = 0
  for (const kf of list) {
    const cur = kf.versions?.[kf.current_version_index ?? 0]
    if (cur?.keyframe_url) completed += 1
  }
  return { completed, total: expectedTotal }
}

/** 与 LazyShotsSection 同源：video-generations-by-thread 轮询数据，todo「镜头」行以 DB 为准，避免 mergeExistingTodoProgress 保留过期 SSE 的 11/11 */
function videoTodoFallbackFromApi(videosData: VideoData | undefined, scenesCount?: number): {
  completed: number
  total: number
} | null {
  const videos = videosData?.video_generations || []
  const totalVideos =
    typeof videosData?.total === 'number' && Number.isFinite(videosData.total) && videosData.total > 0
      ? videosData.total
      : typeof scenesCount === 'number' && Number.isFinite(scenesCount) && scenesCount > 0
        ? scenesCount
        : videos.length
  if (totalVideos <= 0) return null
  const videoMap = new Map<number, MediaRecord>()
  videos.forEach((video, idx: number) => {
    const shotNumber = video.shot_number ?? idx + 1
    if (!videoMap.has(shotNumber)) {
      videoMap.set(shotNumber, video)
    }
  })
  const displayVideos = Array.from({ length: totalVideos }, (_, index) =>
    videoMap.get(index + 1) || { shot_number: index + 1, versions: [] },
  )
  let completed = 0
  for (const v of displayVideos) {
    const vers = v.versions || []
    if (vers.some(ver => !!ver.video_url)) completed += 1
  }
  return { completed, total: totalVideos }
}

type WorkflowPathEntry = { id: string; label_key?: string; est_seconds?: number }

/**
 * 用于底部 todo 的 path：优先匹配 currentRunId；若无（例如 getLatestTask 取到较新的 resume 子 run，
 * 而 workflow_state 只挂在 VA 主 run），则使用本会话内最新一条 workflow_state，与 detail 一致。
 */
function pickWorkflowStateMessageForTodo(
  messages: Message[] | undefined,
  currentRunId: string | null | undefined,
): Message | null {
  const wfList = [...(messages ?? [])].reverse().filter(m => m.event_type === 'workflow_state')
  if (wfList.length === 0) return null
  if (currentRunId != null && currentRunId !== '') {
    const hit = wfList.find((m) => {
      const rid = m.event_data?.run_id ?? m.run_id
      return rid != null && rid === currentRunId
    })
    if (hit) return hit
  }
  return wfList[0] ?? null
}

function buildVideoTodoStepsFromPath(
  pathEntries: WorkflowPathEntry[] | null | undefined,
  t: (key: string) => string,
  hasAnyOrCompleted: (types: string[]) => boolean,
  storyboardsActuallyDone: boolean,
  musicData: MusicData | undefined,
): { id: string; name: string; done: boolean; est_seconds?: number }[] {
  const legacySteps = [
    { id: 'analysis', name: t('analysis') || 'Analysis', done: hasAnyOrCompleted(['video_analysis']) },
    { id: 'story_style', name: `${t('storySection') || 'Story'} + ${t('styleSection') || 'Style'}`, done: hasAnyOrCompleted(['story_outline_generated']) },
    { id: 'visual', name: t('characterSection') || 'Visual Elements', done: hasAnyOrCompleted(['characters_designed']) },
    { id: 'scenes', name: t('sceneSection') || 'Scenes', done: hasAnyOrCompleted(['scenes_generated']) },
    { id: 'storyboards', name: t('storyboardsSection') || 'Storyboards', done: storyboardsActuallyDone },
    { id: 'shots', name: t('shotsSection') || 'Shots', done: hasAnyOrCompleted(['video_segments_generated']) },
    { id: 'final', name: t('finalVideoSection') || 'Final Video', done: hasAnyOrCompleted(['video_completed']) },
  ]
  if (!pathEntries?.length) return legacySteps

  return pathEntries.map((entry) => {
    const id = entry.id
    let name = ''
    if (entry.label_key) {
      const tr = t(entry.label_key)
      name = tr !== entry.label_key ? tr : ''
    }
    if (!name) {
      if (id === 'music') name = t('workflow.node.music') || t('backgroundMusic') || 'Music'
      else if (id === 'analysis') name = t('analysis') || 'Analysis'
      else if (id === 'story_style') name = `${t('storySection') || 'Story'} + ${t('styleSection') || 'Style'}`
      else if (id === 'visual') name = t('characterSection') || 'Visual Elements'
      else if (id === 'scenes') name = t('sceneSection') || 'Scenes'
      else if (id === 'storyboards') name = t('storyboardsSection') || 'Storyboards'
      else if (id === 'narration') name = t('workflow.node.narration') || t('narrationSection') || 'Narration'
      else if (id === 'shots') name = t('shotsSection') || 'Shots'
      else if (id === 'final') name = t('finalVideoSection') || 'Final Video'
      else name = id
    }
    let done = false
    if (id === 'music') {
      done =
        hasAnyOrCompleted(['music_generated']) ||
        !!(musicData?.music_generations?.length) ||
        !!musicData?._noMusic
    } else if (id === 'analysis') {
      done = hasAnyOrCompleted(['video_analysis'])
    } else if (id === 'story_style') {
      done = hasAnyOrCompleted(['story_outline_generated'])
    } else if (id === 'visual') {
      done = hasAnyOrCompleted(['characters_designed'])
    } else if (id === 'scenes') {
      done = hasAnyOrCompleted(['scenes_generated'])
    } else if (id === 'storyboards') {
      done = storyboardsActuallyDone
    } else if (id === 'narration') {
      done = hasAnyOrCompleted(['narrations_generated'])
    } else if (id === 'shots') {
      done = hasAnyOrCompleted(['video_segments_generated'])
    } else if (id === 'final') {
      done = hasAnyOrCompleted(['video_completed'])
    }
    const est =
      typeof entry.est_seconds === 'number' && entry.est_seconds > 0
        ? entry.est_seconds
        : undefined
    return { id, name, done, est_seconds: est }
  })
}

/** 与后端 workflow path / gate_after_music payload（music_mode、paused_intent_key）对齐 */
function resolveVideoInterruptDisplayText(
  interruptData: InterruptData | undefined,
  t: (k: string) => string,
  variant: 'pause' | 'pausedIntent',
): string {
  if (!interruptData) return t('continue')
  if (variant === 'pausedIntent' && interruptData.paused_intent_key) {
    const fromIntent = t(interruptData.paused_intent_key)
    if (fromIntent !== interruptData.paused_intent_key) return fromIntent
  }
  if (interruptData.message_key) {
    const fromKey = t(interruptData.message_key)
    if (fromKey !== interruptData.message_key) return fromKey
  }
  if (interruptData.message_default) return interruptData.message_default
  return t('continue')
}

function versionUuidMatches(v: MediaVersion, versionUuid: string): boolean {
  const u = (versionUuid || '').trim()
  if (!u) return false
  const vu = (v.uuid ?? '').trim()
  const vid = displayValue(v.id ?? '').trim()
  return vu === u || vid === u
}

function completionPredicate(eventTypes: ReadonlySet<string>, completedSteps: ReadonlySet<string>) {
  return (types: string[]) => types.some(type => completedSteps.has(type) || eventTypes.has(type))
}

function displayVersionNumber(ver: MediaVersion | undefined, versions: MediaVersion[]): number {
  if (!ver) return versions.length || 1
  const n = Number(ver.version_number)
  if (Number.isFinite(n) && n > 0) return Math.floor(n)
  const needle = displayValue(ver.uuid ?? ver.id ?? '').trim()
  if (!needle) return 1
  const idx = versions.findIndex(v => versionUuidMatches(v, needle))
  return idx >= 0 ? idx + 1 : 1
}

function frameSlotLabel(shot: number, frameIndex: number | null | undefined, isZh: boolean): string {
  const fi = frameIndex == null || Number.isNaN(frameIndex) ? 0 : frameIndex
  if (isZh) {
    if (fi === -1) return `镜头${shot}·尾帧`
    if (fi === 0) return `镜头${shot}·首帧`
    return `镜头${shot}·第${fi + 1}帧`
  }
  if (fi === -1) return `Shot ${shot} · end frame`
  if (fi === 0) return `Shot ${shot} · first frame`
  return `Shot ${shot} · frame ${fi + 1}`
}

function joinSummaryParts(parts: string[], isZh: boolean, maxParts: number = 4): string {
  const clean = parts.map(p => (p || '').trim()).filter(Boolean)
  if (clean.length === 0) return ''
  const max = maxParts > 0 ? maxParts : 4
  const sep = isZh ? '；' : '; '
  if (clean.length <= max) return clean.join(sep)
  const more = clean.length - max
  return isZh
    ? `${clean.slice(0, max).join(sep)}…等共${clean.length}处`
    : `${clean.slice(0, max).join(sep)}… (${more} more)`
}

/** §2.3.3：payload 锚点 + 已加载列表 join；摘要只含镜头/帧位/版本号，不用 prompt。 */
function buildPostRegenerateSummarySlot(params: {
  kind: string
  items: RegenerationItem[]
  keyframesData?: KeyframeData
  videosData?: VideoData
  charactersData?: CharacterData
  language: string
}): string {
  const { kind, items, keyframesData, videosData, charactersData, language } = params
  const list = Array.isArray(items) ? items.filter(x => typeof x === 'object') : []
  const isZh = language === 'zh'

  if (kind === 'regenerate_keyframes' && keyframesData?.keyframes?.length) {
    const parts: string[] = []
    for (const it of list) {
      const kfu = ((it).keyframe_uuid || '').trim()
      const nvu = ((it).new_version_uuid || '').trim()
      if (!kfu) continue
      const kf = keyframesData.keyframes.find(
        k => (k.uuid || '') === kfu || displayValue(k.id || '') === kfu,
      )
      if (!kf?.versions?.length) continue
      const ver =
        (nvu ? kf.versions.find(v => versionUuidMatches(v, nvu)) : null) ||
        kf.versions[typeof kf.current_version_index === 'number' && Number.isFinite(kf.current_version_index) ? kf.current_version_index : kf.versions.length - 1]
      const shotRaw =
        (it).shot_number != null && (it).shot_number !== ''
          ? Number((it).shot_number)
          : Number(kf.shot_number)
      const shot = Number.isFinite(shotRaw) ? shotRaw : NaN
      if (!Number.isFinite(shot)) continue
      const fi = (it).frame_index
      const vnum = displayVersionNumber(ver, kf.versions)
      const label = frameSlotLabel(shot, fi, isZh)
      parts.push(isZh ? `${label}（v${vnum}）` : `${label} (v${vnum})`)
    }
    return joinSummaryParts(parts, isZh)
  }

  if (kind === 'regenerate_videos' && videosData?.video_generations?.length) {
    const parts: string[] = []
    for (const it of list) {
      const vgu = ((it).video_uuid || '').trim()
      const nvu = ((it).new_version_uuid || '').trim()
      if (!vgu) continue
      const vg = videosData.video_generations.find(
        v => (v.uuid || '') === vgu || displayValue(v.id || '') === vgu,
      )
      if (!vg?.versions?.length) continue
      const ver =
        (nvu ? vg.versions.find(v => versionUuidMatches(v, nvu)) : null) ||
        vg.versions[typeof vg.current_version_index === 'number' && Number.isFinite(vg.current_version_index) ? vg.current_version_index : vg.versions.length - 1]
      const shotRaw =
        (it).shot_number != null && (it).shot_number !== ''
          ? Number((it).shot_number)
          : Number(vg.shot_number)
      const shot = Number.isFinite(shotRaw) ? shotRaw : NaN
      if (!Number.isFinite(shot)) continue
      const vnum = displayVersionNumber(ver, vg.versions)
      parts.push(isZh ? `镜头${shot}视频（v${vnum}）` : `Shot ${shot} video (v${vnum})`)
    }
    return joinSummaryParts(parts, isZh)
  }

  if (kind === 'regenerate_characters' && charactersData?.characters?.length) {
    const parts: string[] = []
    for (const it of list) {
      const cu = ((it).character_uuid || '').trim()
      const nvu = ((it).new_version_uuid || '').trim()
      if (!cu) continue
      const ch = charactersData.characters.find(
        c => (c.uuid || '') === cu || displayValue(c.id || '') === cu,
      )
      if (!ch?.versions?.length) continue
      const ver =
        (nvu ? ch.versions.find(v => versionUuidMatches(v, nvu)) : null) ||
        ch.versions[typeof ch.current_version_index === 'number' && Number.isFinite(ch.current_version_index) ? ch.current_version_index : ch.versions.length - 1]
      const name = (ch.name || '').trim() || (isZh ? '角色' : 'Character')
      const vnum = displayVersionNumber(ver, ch.versions)
      parts.push(isZh ? `「${name}」v${vnum}` : `"${name}" v${vnum}`)
    }
    return joinSummaryParts(parts, isZh)
  }

  return ''
}

/** payload.propagate.items（后端在 regenerate 完成写 msg 时附上）+ 面板 join；表示「点同步后会跑什么」，与 items 表示「刚改了什么」对称。 */
function buildPostRegeneratePropagateSummarySlot(params: {
  kind: string
  propagateItems: RegenerationItem[]
  keyframesData?: KeyframeData
  videosData?: VideoData
  language: string
  maxParts?: number
}): string {
  const { kind, propagateItems, keyframesData, videosData, language, maxParts } = params
  const list = Array.isArray(propagateItems) ? propagateItems.filter(x => typeof x === 'object') : []
  const isZh = language === 'zh'
  const cap = maxParts ?? 4
  if (list.length === 0) return ''

  if (kind === 'regenerate_characters' && keyframesData?.keyframes?.length) {
    const parts: string[] = []
    for (const it of list) {
      const kfu = ((it).keyframe_uuid || '').trim()
      const kvu = ((it).keyframe_version_uuid || '').trim()
      const shotRaw = Number((it).shot_number)
      const fi = (it).frame_index
      const kf = kfu
        ? keyframesData.keyframes.find(k => (k.uuid || '') === kfu || displayValue(k.id || '') === kfu)
        : null
      if (kf?.versions?.length && kvu) {
        const ver = kf.versions.find(v => versionUuidMatches(v, kvu))
        if (!ver) continue
        const shot = Number.isFinite(shotRaw) ? shotRaw : Number(kf.shot_number)
        if (!Number.isFinite(shot)) continue
        const vnum = displayVersionNumber(ver, kf.versions)
        const label = frameSlotLabel(shot, fi, isZh)
        parts.push(isZh ? `${label}（v${vnum}）` : `${label} (v${vnum})`)
      } else if (Number.isFinite(shotRaw)) {
        parts.push(frameSlotLabel(shotRaw, fi, isZh))
      }
    }
    return joinSummaryParts(parts, isZh, cap)
  }

  if (kind === 'regenerate_characters') {
    const parts: string[] = []
    for (const it of list) {
      const shotRaw = Number((it).shot_number)
      if (Number.isFinite(shotRaw)) {
        parts.push(frameSlotLabel(shotRaw, (it).frame_index, isZh))
      }
    }
    return joinSummaryParts(parts, isZh, cap)
  }

  if (kind === 'regenerate_keyframes') {
    const shots = list
      .map(r => Number((r).shot_number))
      .filter(n => Number.isFinite(n))
      .sort((a, b) => a - b)
    const uniq = [...new Set(shots)]
    if (uniq.length === 0) return ''
    const sstr = uniq.join(isZh ? '、' : ', ')
    return isZh ? `镜头 ${sstr} 的视频` : `Shot ${sstr} video`
  }

  if (kind === 'regenerate_videos' && videosData?.video_generations?.length) {
    const parts: string[] = []
    for (const it of list) {
      const vgu = ((it).video_generation_uuid || '').trim()
      const nvu = ((it).video_generation_version_uuid || '').trim()
      if (!vgu) continue
      const vg = videosData.video_generations.find(
        v => (v.uuid || '') === vgu || displayValue(v.id || '') === vgu,
      )
      if (!vg?.versions?.length) continue
      const ver = nvu ? vg.versions.find(v => versionUuidMatches(v, nvu)) : null
      if (!ver) continue
      const shotRaw =
        (it).shot_number != null && (it).shot_number !== ''
          ? Number((it).shot_number)
          : Number(vg.shot_number)
      const shot = Number.isFinite(shotRaw) ? shotRaw : NaN
      if (!Number.isFinite(shot)) continue
      const vnum = displayVersionNumber(ver, vg.versions)
      parts.push(isZh ? `镜头${shot}视频（v${vnum}）` : `Shot ${shot} video (v${vnum})`)
    }
    return joinSummaryParts(parts, isZh, cap)
  }

  if (kind === 'regenerate_videos') {
    const shots = list
      .map(r => Number((r).shot_number))
      .filter(n => Number.isFinite(n))
      .sort((a, b) => a - b)
    const uniq = [...new Set(shots)]
    if (uniq.length === 0) return ''
    const sstr = uniq.join(isZh ? '、' : ', ')
    return isZh ? `时间线镜头 ${sstr}` : `Timeline shots ${sstr}`
  }

  return ''
}

/** 与 LazyStoryboardsSection 的 dice key 一致；仅用于 post-regenerate regenerate_characters（下游关键帧 I2I） */
function computeKeyframeDiceKeysFromPropagate(
  kind: string,
  propagateItems: RegenerationItem[],
  keyframesData?: KeyframeData  ,
): string[] {
  const keys: string[] = []
  const list = Array.isArray(propagateItems) ? propagateItems : []
  const kfs = keyframesData?.keyframes
  if (!kfs?.length) return keys

  if (kind === 'regenerate_characters') {
    for (const row of list) {
      const kfu = ((row).keyframe_uuid || '').trim()
      const kvu = ((row).keyframe_version_uuid || '').trim()
      if (!kfu || !kvu) continue
      const kf = kfs.find(k => (k.uuid || '') === kfu || displayValue(k.id || '') === kfu)
      if (!kf?.versions?.length) continue
      const vIdx = kf.versions.findIndex(v => versionUuidMatches(v, kvu))
      if (vIdx < 0) continue
      const sn = Number(
        (row).shot_number != null && (row).shot_number !== ''
          ? (row).shot_number
          : kf.shot_number,
      )
      if (!Number.isFinite(sn)) continue
      keys.push(`${sn}-${vIdx}`)
    }
  }
  return [...new Set(keys)]
}

/** 与 LazyShotsSection 的 dice key `${shotNumber}-${vIdx}` 对齐。propagate 仅 shot_number（关键帧卡下游→regenerate_videos）或含 video_uuid + version。 */
function computeVideoDiceKeysFromPropagate(propagateItems: RegenerationItem[], videosData?: VideoData  ): string[] {
  const keys: string[] = []
  const list = Array.isArray(propagateItems) ? propagateItems : []
  const vgs = videosData?.video_generations
  if (!vgs?.length) return keys
  for (const row of list) {
    const vgu = ((row).video_generation_uuid || (row).video_uuid || '').trim()
    const vvru = ((row).video_generation_version_uuid || (row).version_uuid || '').trim()
    let shot = Number((row).shot_number)
    let vg = vgu ? vgs.find(v => (v.uuid || '') === vgu) : null
    if (!vg && Number.isFinite(shot)) {
      vg = vgs.find(v => Number(v.shot_number) === shot)
    }
    if (!vg?.versions?.length) continue
    if (!vvru) {
      if (!Number.isFinite(shot)) shot = Number(vg.shot_number)
      if (!Number.isFinite(shot)) continue
      const ci = Number.isFinite(Number(vg.current_version_index))
        ? Number(vg.current_version_index)
        : vg.versions.length - 1
      const vIdx = Math.max(0, Math.min(ci, vg.versions.length - 1))
      keys.push(`${shot}-${vIdx}`)
      continue
    }
    const vIdx = vg.versions.findIndex(v => versionUuidMatches(v, vvru))
    if (vIdx < 0) continue
    const sn = Number.isFinite(shot) ? shot : Number(vg.shot_number)
    if (!Number.isFinite(sn)) continue
    keys.push(`${sn}-${vIdx}`)
  }
  return [...new Set(keys)]
}

function buildPostRegeneratePropagateConfirmBody(
  kind: string,
  shotsStr: string,
  t: (key: string) => string,
  /** 由 payload.propagate.items + 面板 join，表示同步下游将作用范围 */
  propagateScopeSummary: string,
): string {
  const shots = shotsStr.trim()
  let base: string
  if (kind === 'regenerate_keyframes') {
    base = shots
      ? t('postRegeneratePropagateKeyframes').replace('{{shots}}', shots)
      : t('postRegeneratePropagateKeyframesNoShots')
  } else if (kind === 'regenerate_characters') {
    base = t('postRegeneratePropagateCharacters')
  } else if (kind === 'regenerate_videos') {
    base = t('postRegeneratePropagateVideos')
  } else {
    base = t('postRegeneratePropagateKeyframesNoShots')
  }
  const detail = (propagateScopeSummary || '').trim()
  if (!detail) return base
  return `${base}\n\n${t('postRegeneratePropagateScopeHeading')}\n${detail}`
}

function postRegenerateConfirmTitleKey(kind: string): string {
  if (kind === 'regenerate_keyframes') return 'postRegenerateConfirmTitleKeyframes'
  if (kind === 'regenerate_characters') return 'postRegenerateConfirmTitleCharacters'
  if (kind === 'regenerate_videos') return 'postRegenerateConfirmTitleVideos'
  return 'postRegenerateConfirmTitleKeyframes'
}

function postRegenerateOptionSyncKey(kind: string): string {
  if (kind === 'regenerate_keyframes') return 'postRegenerateOptionSyncKeyframes'
  if (kind === 'regenerate_characters') return 'postRegenerateOptionSyncCharacters'
  if (kind === 'regenerate_videos') return 'postRegenerateOptionSyncVideos'
  return 'postRegenerateOptionSyncKeyframes'
}

/** Regenerate 完成后的「继续 / 同步下游」卡片（interaction_post_regenerate） */
function PostRegenerateMessageBlock({
  msg,
  conversationId,
  t,
  onRefresh,
  onPostRegenerateKeyframeDiceKeys,
  onPostRegenerateVideoDiceKeys,
  onPostRegenerateTimelineMergeBusy,
  keyframesData,
  videosData,
  charactersData,
}: {
  msg: Message
  conversationId: string | null
  t: (key: string) => string
  onRefresh?: () => void | Promise<void>
  /** regenerate_characters 同步下游 → 故事板关键帧 dice */
  onPostRegenerateKeyframeDiceKeys?: (keys: string[]) => void
  /** regenerate_keyframes 同步下游实际跑 propagate 的 regenerate_videos → 镜头区视频 dice */
  onPostRegenerateVideoDiceKeys?: (keys: string[]) => void
  /** regenerate_videos 同步下游：时间线合并，镜头区「合并视频」loading */
  onPostRegenerateTimelineMergeBusy?: (busy: boolean) => void
  keyframesData?: KeyframeData
  videosData?: VideoData
  charactersData?: CharacterData
}) {
  const { language } = useLanguage()
  const [busy, setBusy] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const ev = msg.event_data || {}
  const interaction = ev.interaction || {}
  const payload = interaction.payload || {}
  const kind = (payload.kind || '')
  const items = Array.isArray(payload.items) ? payload.items : []
  const propagateItems = Array.isArray((payload).propagate?.items)
    ? (payload).propagate.items
    : []
  const mid = msg.message_id ?? (msg as { id?: number }).id
  const cid = conversationId ? parseInt(conversationId, 10) : NaN

  const shotSummary = () => {
    const sep = language === 'zh' ? '、' : ', '
    const shots = [
      ...new Set(
        items
          .map((x: { shot_number?: number }) => x.shot_number)
          .filter((n: unknown) => n != null && n !== ''),
      ),
    ] as number[]
    return shots.length ? shots.sort((a, b) => a - b).join(sep) : ''
  }

  const joinedSummary = buildPostRegenerateSummarySlot({
    kind,
    items,
    keyframesData,
    videosData,
    charactersData,
    language,
  })
  const shotsStr = shotSummary()
  const summarySlot =
    joinedSummary ||
    (shotsStr
      ? t('postRegenerateShotsOnly').replace('{{shots}}', shotsStr)
      : t('postRegenerateSummaryFallback'))
  const lead = t('postRegenerateAgentLead').replace('{{summary}}', summarySlot)
  /** 弹窗内展示完整作用范围；不在聊天按钮上重复，避免窄屏裁切与「…等共 N 处」观感差 */
  const propagateScopeForDialog = buildPostRegeneratePropagateSummarySlot({
    kind,
    propagateItems,
    keyframesData,
    videosData,
    language,
    maxParts: 99,
  })
  const propagateBody = buildPostRegeneratePropagateConfirmBody(kind, shotsStr, t, propagateScopeForDialog)
  const syncBaseLabel = t(postRegenerateOptionSyncKey(kind))

  const runAction = async (action: 'continue_edit' | 'sync_downstream') => {
    if (!cid || mid == null || Number.isNaN(cid)) {
      toast.error(t('postRegenerateMissingIds'))
      return
    }
    setBusy(true)
    let didPresetKeyframeCompanion = false
    let didPresetVideoCompanion = false
    let didPresetTimelineMergeBusy = false
    if (action === 'sync_downstream') {
      toast.info(
        kind === 'regenerate_videos'
          ? t('postRegenerateSyncStartedVideos')
          : t('postRegenerateSyncStarted'),
      )
      /** regenerate_videos：下游 regenerate_timeline →「合并视频」同款 busy */
      if (kind === 'regenerate_videos') {
        onPostRegenerateTimelineMergeBusy?.(true)
        didPresetTimelineMergeBusy = true
      }
      /** regenerate_keyframes：卡片 kind 是关键帧，但同步跑的是 propagate 的镜头视频 regenerate → 镜头 dice */
      if (kind === 'regenerate_keyframes') {
        const preVid = computeVideoDiceKeysFromPropagate(propagateItems, videosData)
        if (preVid.length > 0) {
          onPostRegenerateVideoDiceKeys?.(preVid)
          didPresetVideoCompanion = true
        }
      }
      /** regenerate_characters：下游关键帧 I2I → 故事板 dice */
      if (kind === 'regenerate_characters') {
        const preKfKeys = computeKeyframeDiceKeysFromPropagate(kind, propagateItems, keyframesData)
        if (preKfKeys.length > 0) {
          onPostRegenerateKeyframeDiceKeys?.(preKfKeys)
          didPresetKeyframeCompanion = true
        }
      }
      setConfirmOpen(false)
    }
    try {
      const res = { code: 1, message: 'Regenerate is not available in the local agent build.' }
      if (res.code !== 0) {
        if (didPresetKeyframeCompanion) {
          onPostRegenerateKeyframeDiceKeys?.([])
        }
        if (didPresetVideoCompanion) {
          onPostRegenerateVideoDiceKeys?.([])
        }
        if (didPresetTimelineMergeBusy) {
          onPostRegenerateTimelineMergeBusy?.(false)
        }
        toast.error((res as { message?: string }).message || 'Request failed')
        return
      }
      toast.success(
        action === 'continue_edit'
          ? t('postRegenerateContinueOk')
          : kind === 'regenerate_videos'
            ? t('postRegenerateSyncOkVideos')
            : t('postRegenerateSyncOk'),
      )
      if (action === 'sync_downstream') {
        /** 后端在返回前 await 完整下游（含 segment 同步与成片拼接），任务已终态，companion 轮询未必会跑 — 须与手动「合并视频」一样在此处结束 loading */
        if (didPresetTimelineMergeBusy) {
          onPostRegenerateTimelineMergeBusy?.(false)
        }
        if (didPresetVideoCompanion) {
          onPostRegenerateVideoDiceKeys?.([])
        }
        if (didPresetKeyframeCompanion) {
          onPostRegenerateKeyframeDiceKeys?.([])
        }
        if (onRefresh) void Promise.resolve(onRefresh())
      }
      if (action === 'continue_edit') setConfirmOpen(false)
    } catch (e) {
      if (didPresetKeyframeCompanion) {
        onPostRegenerateKeyframeDiceKeys?.([])
      }
      if (didPresetVideoCompanion) {
        onPostRegenerateVideoDiceKeys?.([])
      }
      if (didPresetTimelineMergeBusy) {
        onPostRegenerateTimelineMergeBusy?.(false)
      }
      toast.error(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <p className="text-sm leading-relaxed font-inter whitespace-pre-wrap">{lead}</p>
      <div className="flex flex-wrap gap-2 mt-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void runAction('continue_edit')}
        >
          {t('postRegenerateOptionContinue')}
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() =>{  setConfirmOpen(true) }}>
          {syncBaseLabel}
        </Button>
      </div>
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-lg" hideCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t(postRegenerateConfirmTitleKey(kind))}</DialogTitle>
            <DialogDescription className="text-sm whitespace-pre-wrap text-muted-foreground font-inter text-left max-h-[min(50vh,22rem)] overflow-y-auto overscroll-contain pr-1">
              {propagateBody}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex flex-row justify-end gap-2 sm:gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() =>{  setConfirmOpen(false) }}>
              {t('postRegenerateCancel')}
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                void runAction('sync_downstream')
              }}
            >
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" aria-hidden />
                  {t('postRegenerateConfirmSync')}
                </span>
              ) : (
                t('postRegenerateConfirmSync')
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

interface MessageAreaProps {
  chatTitle: string
  messages: Message[]
  message: string
  isGenerating: boolean
  threadId?: string
  scenesCount?: number
  uploadedFiles?: File[]
  fileUploadStates?: Array<{ percent: number; phase: 'uploading' | 'saving' | 'ready' | 'error' }>
  onMessageChange: (value: string) => void
  onSendMessage: () => void
  /** 点击提示词引导按钮时，用 display 文案直接发送（前端展示 display，后端会按 promptMapping 转为长 prompt）。不传则点击仅填入输入框。 */
  onSendWithPrompt?: (displayPrompt: string) => void
  onActionSuggestionClick?: (item: ActionSuggestionItem) => void
  onCancelGeneration?: () => void
  onFileUpload?: (files: File[]) => void
  onFileRemove?: (index: number) => void
  onFileReplace?: (index: number, file: File) => void
  onInterruptOptionClick?: (option: string | {
    type: string
    run_id: string | null
    interrupt_msgid?: string | number
    smart_clip?: SmartClipDecision
  }, threadId: string) => void
  isInputDisabled?: boolean
  showAssistantThinking?: boolean
  hideHeader?: boolean
  /** 当前有一轮 in-flight（思考 / 流式 / 生成），用于展示停止按钮 */
  isInFlight?: boolean
  // ✅ 配置选项
  duration?: number[]
  aspectRatio?: '16:9' | '1:1' | '9:16'
  resolution?: '480p' | '720p' | '1080p'
  selectedModel?: string
  imageGenerationTool?: 'nano_banana' | 'nano_banana_2' | 'nano_banana_pro' | 'seedream' | 'gpt_image_2'
  lipsyncCoverage?: number
  enableContinuityMode?: boolean
  enableKeyframeReflection?: boolean
  /** 暂停点是否自动倒计时后继续（默认关闭，不展示倒计时） */
  autoContinueOnInterrupt?: boolean
  onAutoContinueOnInterruptChange?: (value: boolean) => void
  onDurationChange?: (value: number[]) => void
  /** User changed video duration in panel (not default-only). Used for optional crop hint. */
  durationPanelExplicit?: boolean
  onAspectRatioChange?: (value: '16:9' | '1:1' | '9:16') => void
  onResolutionChange?: (value: '480p' | '720p' | '1080p') => void
  onModelChange?: (value: string) => void
  onImageGenerationToolChange?: (value: 'nano_banana' | 'nano_banana_2' | 'nano_banana_pro' | 'seedream' | 'gpt_image_2') => void
  onLipsyncCoverageChange?: (value: number) => void
  lipsyncVideoModel?: string
  onLipsyncVideoModelChange?: (value: string) => void
  onEnableContinuityModeChange?: (value: boolean) => void
  onEnableKeyframeReflectionChange?: (value: boolean) => void
  // Storyboard chat props
  storyboardChatMessage?: string
  selectedStoryboard?: MediaRecord
  onStoryboardChatMessageChange?: (value: string) => void
  onStoryboardChatSend?: () => void
  // ✅ 控制 todo list 显示
  showTodoList?: boolean
  // ✅ Agent Type - 用于区分不同的生成类型
  agentType?: string
  // ✅ 点击容器时的回调（用于收起 sidebar）
  onContainerClick?: () => void
  // ✅ 当前对话的 run_id（用于视频步骤「继续」时拼 resumeData）
  currentRunId?: string | null
  /** 详情轮询的关键帧数据（与右侧故事板同源），用于 todo 分镜进度在 DB 无 progress 事件时回填 */
  keyframesData?: KeyframeData
  /** 详情轮询的镜头视频数据（与右侧镜头区同源），用于 todo「镜头」行与 (8/11) 一致，避免仅信 SSE 合并值 */
  videosData?: VideoData
  /** 角色区数据：post_regenerate 卡片用锚点 join 展示摘要（§2.3.3） */
  charactersData?: CharacterData
  /** 音乐区 / DB 数据：todo「背景音乐」完成态与 music_generations、_noMusic 对齐 */
  musicData?: MusicData
  /** 当前对话 id（conversations.id），用于 post-regenerate-action */
  conversationId?: string | null
  /** Regenerate 同步下游成功后刷新右侧/数据（建议拉 conversation/detail 以更新消息与任务） */
  onPostRegenerateRefresh?: () => void | Promise<void>
  /** 同步下游将触发的关键帧 dice（仅 regenerate_characters → 故事板） */
  onPostRegenerateKeyframeDiceKeys?: (keys: string[]) => void
  /** regenerate_keyframes 同步下游实际为镜头视频任务 → 镜头区 dice */
  onPostRegenerateVideoDiceKeys?: (keys: string[]) => void
  /** regenerate_videos 同步下游（时间线/成片合并）时，镜头区「合并视频」按钮同款 busy */
  onPostRegenerateTimelineMergeBusy?: (busy: boolean) => void
  // ✅ 手机端右滑回调（返回对话列表）
  onSwipeRight?: () => void
  /** 手机端图片类型：true 时图片结果直接显示在对话气泡中，而非创作空间 */
  showImageResultsInChat?: boolean
  /** 手机端视频直生类型：true 时视频结果直接显示在对话气泡中，而非创作空间 */
  showVideoResultsInChat?: boolean
  /** 需求已确认完成、等待用户点「直接生成」时展示输入区上方提示 */
  showClickDirectGenerateHint?: boolean
  /** 为 false 时隐藏创作确认阶段推荐动作（积分不足通知的推荐仍展示） */
  showActionSuggestions?: boolean
  /** SSE 流式解析完成、落库前的推荐动作（见到 END token 后展示） */
  streamedActionSuggestions?: ActionSuggestionItem[]
}

function getAssistantBubbleDisplayText(msg: Message): string {
  const raw = (msg.content).trim()
  if (!raw && msg.event_type) {
    return msg.event_type
  }
  return stripActionSuggestionsFromChatContent(raw)
}

export const MessageArea = ({
  chatTitle,
  messages,
  message,
  isGenerating,
  threadId,
  scenesCount,
  uploadedFiles = [],
  fileUploadStates = [],
  onMessageChange,
  onSendMessage,
  onSendWithPrompt,
  onActionSuggestionClick,
  onCancelGeneration,
  onFileUpload,
  onFileRemove,
  onFileReplace,
  onInterruptOptionClick,
  isInputDisabled = false,
  showAssistantThinking = false,
  hideHeader = false,
  isInFlight = false,
  // ✅ 配置选项（默认值与首页一致，见 constants/defaults.ts DEFAULT_VIDEO_OPTIONS）
  duration = [DEFAULT_VIDEO_OPTIONS.duration],
  aspectRatio = DEFAULT_VIDEO_OPTIONS.aspectRatio,
  resolution = DEFAULT_VIDEO_OPTIONS.resolution,
  selectedModel = DEFAULT_VIDEO_OPTIONS.selectedModel,
  imageGenerationTool = DEFAULT_IMAGE_GENERATION_TOOL,
  lipsyncCoverage = DEFAULT_VIDEO_OPTIONS.lipsyncCoverage,
  lipsyncVideoModel = DEFAULT_VIDEO_OPTIONS.lipsyncVideoModel,
  onLipsyncVideoModelChange,
  enableContinuityMode = DEFAULT_VIDEO_OPTIONS.enableContinuityMode,
  enableKeyframeReflection = DEFAULT_VIDEO_OPTIONS.enableKeyframeReflection,
  autoContinueOnInterrupt = DEFAULT_VIDEO_OPTIONS.autoContinueOnInterrupt,
  onAutoContinueOnInterruptChange,
  onDurationChange,
  durationPanelExplicit = false,
  onAspectRatioChange,
  onResolutionChange,
  onModelChange,
  onImageGenerationToolChange,
  onLipsyncCoverageChange,
  onEnableContinuityModeChange,
  onEnableKeyframeReflectionChange,
  // Storyboard chat props
  storyboardChatMessage = '',
  selectedStoryboard,
  onStoryboardChatMessageChange,
  onStoryboardChatSend,
  // ✅ 控制 todo list 显示，默认为 true（保持向后兼容）
  showTodoList = true,
  // ✅ Agent Type
  agentType,
  // ✅ 点击容器时的回调
  onContainerClick,
  currentRunId = null,
  keyframesData,
  videosData,
  charactersData,
  musicData,
  onSwipeRight,
  showImageResultsInChat = false,
  showVideoResultsInChat = false,
  conversationId = null,
  onPostRegenerateRefresh,
  onPostRegenerateKeyframeDiceKeys,
  onPostRegenerateVideoDiceKeys,
  onPostRegenerateTimelineMergeBusy,
  showClickDirectGenerateHint = false,
  showActionSuggestions = true,
  streamedActionSuggestions,
}: MessageAreaProps) => {
  const composingRef = useRef(false)
  const { t, language } = useLanguage()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const formatChatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp)
    const locale = language === 'zh' ? 'zh-CN' : 'en-US'
    const parts = new Intl.DateTimeFormat(locale, {
      month: language === 'zh' ? 'numeric' : 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(date)
    const getPart = (type: string) => parts.find(part => part.type === type)?.value ?? ''
    const month = getPart('month')
    const day = getPart('day')
    const hour = getPart('hour')
    const minute = getPart('minute')
    return language === 'zh'
      ? `${month}月${day}日 ${hour}:${minute}`
      : `${month} ${day} at ${hour}:${minute}`
  }
  const assistantThinkingText = t('da.composer.thinking')

  // 用消息中的 generation_todo 作为聊天区生成阶段的权威来源，
  // 避免父层 isGenerating 与 SSE/detail 短暂不同步时 UI 来回切换。
  const latestTodoMessage = (() => {
    // 检查消息列表中是否有取消事件
    const hasCancelledEvent = messages.some(msg =>
      msg.event_type === 'generation_cancelled' ||
      msg.event_type === 'cancelled' ||
      msg.event_data?.status === TaskStatus.CANCELLED,
    )

    if (hasCancelledEvent) {
      console.log('⏹️ Task was cancelled (found cancel event), hiding todo list')
      return null
    }

    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (!m) continue
      if (m.event_type === 'generation_todo') {
        // ✅ 检查任务是否被取消
        const status = m.event_data?.status
        if (status === 'cancelled') {
          console.log('⏹️ Task was cancelled (todo status), hiding todo list')
          return null
        }
        return m
      }
    }
    return null
  })()
  // ✅ 方案B：将 todo list 固定在聊天滚动区域底部（sticky），避免被最新消息顶走
  // ✅ 如果 showTodoList 为 false，则不显示 todo list
  const todoMessage = showTodoList ? latestTodoMessage : null
  // generation_todo / workflow_state 只通过底部 sticky todo 展示；关闭 todo 时也不应回退成普通消息气泡
  const displayMessages = messages.filter(
    m => m.event_type !== 'generation_todo' && m.event_type !== 'workflow_state',
  )
  const messageScrollRootRef = useRef<HTMLDivElement>(null)
  const shouldFollowMessagesRef = useRef(true)
  const lastDisplayMessage = displayMessages[displayMessages.length - 1]
  const messageRenderSignature = `${displayMessages.length}:${lastDisplayMessage?.id ?? lastDisplayMessage?.message_id ?? ''}:${lastDisplayMessage?.content.length ?? 0}`

  useEffect(() => {
    const viewport = messageScrollRootRef.current?.querySelector(
      '[data-radix-scroll-area-viewport]',
    ) as HTMLElement | null
    if (!viewport) return
    const updateFollowState = () => {
      shouldFollowMessagesRef.current =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 160
    }
    updateFollowState()
    viewport.addEventListener('scroll', updateFollowState, { passive: true })
    return () =>{  viewport.removeEventListener('scroll', updateFollowState) }
  }, [threadId])

  useEffect(() => {
    const viewport = messageScrollRootRef.current?.querySelector(
      '[data-radix-scroll-area-viewport]',
    ) as HTMLElement | null
    if (!viewport) return
    const latestIsUser = lastDisplayMessage?.role === 'user' || lastDisplayMessage?.role === 'human'
    if (!shouldFollowMessagesRef.current && !latestIsUser) return
    const frame = requestAnimationFrame(() => {
      viewport.scrollTop = viewport.scrollHeight
      shouldFollowMessagesRef.current = true
    })
    return () =>{  cancelAnimationFrame(frame) }
  }, [messageRenderSignature, lastDisplayMessage?.role])
  const isActionSuggestionsMessage = useCallback((m: Message) => {
    if (m.role !== 'ai' || m.event_type === 'welcome') return false
    return showActionSuggestions
  }, [showActionSuggestions])

  const latestActionSuggestions = (() => {
    for (let i = displayMessages.length - 1; i >= 0; i--) {
      const m = displayMessages[i]
      if (!m) continue
      if (!isActionSuggestionsMessage(m)) continue
      const parsed = parseActionSuggestions(m.event_data?.action_suggestions)
      if (parsed.length === 0) continue
      return parsed
    }
    return [] as ActionSuggestionItem[]
  })()

  const agentSuggestionsEverReceived = useMemo(() => {
    for (let i = displayMessages.length - 1; i >= 0; i--) {
      const m = displayMessages[i]
      if (!m) continue
      if (!isActionSuggestionsMessage(m)) continue
      if (parseActionSuggestions(m.event_data?.action_suggestions).length > 0) return true
    }
    return false
  }, [displayMessages, isActionSuggestionsMessage])

  const getLatestSuggestionSourceKey = useCallback((msgs: typeof displayMessages) => {
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i]
      if (!m) continue
      if (!isActionSuggestionsMessage(m)) continue
      if (parseActionSuggestions(m.event_data?.action_suggestions).length === 0) continue
      return displayValue(m.message_id ?? `${m.timestamp ?? ''}-${i}`)
    }
    return null
  }, [isActionSuggestionsMessage])

  const suppressSuggestionsKeyRef = useRef<string | null>(null)
  const [suppressActionSuggestionsUI, setSuppressActionSuggestionsUI] = useState(false)

  useEffect(() => {
    if (!suppressActionSuggestionsUI) return
    const cur = getLatestSuggestionSourceKey(displayMessages)
    const frozen = suppressSuggestionsKeyRef.current
    if (cur != null && frozen != null && cur !== frozen) {
      setSuppressActionSuggestionsUI(false)
      suppressSuggestionsKeyRef.current = null
    }
  }, [displayMessages, suppressActionSuggestionsUI, getLatestSuggestionSourceKey])

  useEffect(() => {
    setSuppressActionSuggestionsUI(false)
    suppressSuggestionsKeyRef.current = null
  }, [conversationId, threadId])

  const streamedSuggestions =
    streamedActionSuggestions && streamedActionSuggestions.length > 0
      ? streamedActionSuggestions
      : null
  const effectiveActionSuggestions = (suppressActionSuggestionsUI
    ? []
    : (streamedSuggestions ?? latestActionSuggestions)
  ).filter(item => !isPaymentTopUpAction(item))
  const suggestionsEverReceived =
    agentSuggestionsEverReceived || (streamedSuggestions?.length ?? 0) > 0

  const handleActionSuggestionButtonClick = (item: ActionSuggestionItem) => {
    const key = getLatestSuggestionSourceKey(displayMessages)
    if (key) {
      suppressSuggestionsKeyRef.current = key
      setSuppressActionSuggestionsUI(true)
    }
    if (onActionSuggestionClick) {
      onActionSuggestionClick(item)
    } else {
      onMessageChange(item.message || item.label)
    }
  }

  const [todoCollapsed, setTodoCollapsed] = useState(true)
  /** 本次 interrupt 已关闭 15s 自动继续（前端停表 + 后端 Redis 跳过 auto_resume） */
  const [dismissedAutoResumeByMsgId, setDismissedAutoResumeByMsgId] = useState<Record<number, boolean>>({})
  const activeTodoMessage = showTodoList ? latestTodoMessage : null
  const todoStatus = ((activeTodoMessage)?.event_data?.status || '').toLowerCase()
  const isTodoPendingUserInput = (activeTodoMessage)?.event_data?.todo_pending_user_input === true
  const isTodoTaskRunning = todoStatus === 'running' || todoStatus === 'queued' || todoStatus === 'resume_queued' || todoStatus === 'pending'
  const effectiveIsGenerating = isGenerating || isTodoTaskRunning
  const latestVisibleMessage = displayMessages[displayMessages.length - 1]
  const latestAssistantHasContent =
    latestVisibleMessage?.role !== 'user' &&
    latestVisibleMessage?.role !== 'human' &&
    Boolean(latestVisibleMessage?.content.trim())
  const shouldShowAssistantThinking = showAssistantThinking && !latestAssistantHasContent
  const shouldShowCancelButton =
    isInFlight &&
    !!onCancelGeneration &&
    todoStatus !== 'interrupted' &&
    !isTodoPendingUserInput
  const todoStickyRef = useRef<HTMLDivElement>(null)
  // ✅ 关键帧/反思进度更新时自动滚动到底部（仅当用户处于底部附近时，避免打断上翻查看）
  // 防抖动：每次进度 tick 最多 500ms 内只触发一次 scrollIntoView
  const lastKeyframeProgressRef = useRef<{ kf?: number; refl?: number }>({})
  const progressScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!todoMessage || !effectiveIsGenerating || agentType !== 'video') return
    const kfFb = keyframeTodoFallbackFromApi(keyframesData)
    const kf =
      (todoMessage).event_data?.keyframe_completed ??
      kfFb?.completed ??
      (todoMessage).event_data?.keyframe_progress_percent
    const refl = (todoMessage).event_data?.keyframe_reflection_completed ?? (todoMessage).event_data?.keyframe_reflection_progress_percent
    const prev = lastKeyframeProgressRef.current
    const changed = (kf != null && prev.kf !== kf) || (refl != null && prev.refl !== refl)
    if (changed) {
      lastKeyframeProgressRef.current = { kf: kf ?? prev.kf, refl: refl ?? prev.refl }
      // 节流：若已有排队的滚动，不再重复排队
      if (progressScrollTimerRef.current) return
      progressScrollTimerRef.current = setTimeout(() => {
        progressScrollTimerRef.current = null
        const el = todoStickyRef.current
        if (!el) return
        const viewport = el.closest('[data-radix-scroll-area-viewport]')
        if (viewport) {
          const nearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 150
          if (!nearBottom) return
        }
        el.scrollIntoView({ behavior: 'smooth', block: 'end' })
      }, 500)
    }
  }, [
    todoMessage,
    todoMessage?.event_data?.keyframe_completed,
    todoMessage?.event_data?.keyframe_total,
    todoMessage?.event_data?.keyframe_reflection_completed,
    todoMessage?.event_data?.keyframe_reflection_total,
    todoMessage?.event_data?.keyframe_progress_percent,
    todoMessage?.event_data?.keyframe_reflection_progress_percent,
    effectiveIsGenerating,
    agentType,
    keyframesData,
  ])
  // 刷新后恢复 todo 折叠状态（按 thread 维度）
  useEffect(() => {
    if (!threadId) return
    const saved = localStorage.getItem(`todoCollapsed:${threadId}`)
    if (saved === '1') setTodoCollapsed(true)
    else if (saved === '0') setTodoCollapsed(false)
  }, [threadId])

  useEffect(() => {
    if (!threadId) return
    localStorage.setItem(`todoCollapsed:${threadId}`, todoCollapsed ? '1' : '0')
  }, [threadId, todoCollapsed])
  // 组件卸载时清除 timer
  useEffect(() => {
    return () => {
      if (progressScrollTimerRef.current) clearTimeout(progressScrollTimerRef.current)
    }
  }, [])

  // ✅ 时间追踪：记录整个生成过程的开始时间
  const generationStartTimeRef = useRef<number | null>(null)
  const [elapsedTime, setElapsedTime] = useState(0)
  const lastProgressRef = useRef(0)
  const lastRemainingRef = useRef<number | null>(null)
  const lastElapsedTimeRef = useRef(0)

  // ✅ 读取后端 workflow_state 下发的耗时预估（缺失时回退本地经验公式）
  const getBackendWorkflowTimeSource = useCallback((): ChatEventData | null => {
    try {
      const wfMsg = pickWorkflowStateMessageForTodo(messages, currentRunId)
      return wfMsg ? (wfMsg.event_data ?? wfMsg) : null
    } catch {
      return null
    }
  }, [currentRunId, messages])
  const getBackendStepEstSeconds = useCallback((stepId: string): number | null => {
    const src = getBackendWorkflowTimeSource()
    const path = src?.path
    if (Array.isArray(path)) {
      const entry = path.find(p => p.id === stepId)
      if (entry && typeof entry.est_seconds === 'number' && entry.est_seconds > 0) {
        return entry.est_seconds
      }
    }
    return null
  }, [getBackendWorkflowTimeSource])

  // ✅ 计算总预计生成时间（秒）- 优先用后端 total_est_seconds，缺失回退本地经验公式
  const calculateTotalEstimatedTime = (videoDuration: number = 30): number => {
    const src = getBackendWorkflowTimeSource()
    const backendTotal = src?.total_est_seconds
    if (typeof backendTotal === 'number' && backendTotal > 0) {
      return backendTotal
    }

    // 固定耗时部分（约 4 分钟，覆盖 Analysis + Story/Style + Visual Elements）
    const fixedTime = 240

    // 场景数量（每 15 秒一个场景）
    const sceneCount = Math.ceil(videoDuration / 15)

    // 可变耗时
    const keyframeTime = sceneCount * 90      // 每个关键帧 90 秒（Storyboards）
    const videoSegmentTime = sceneCount * 80  // 每个视频片段 80 秒（Shots）
    const musicTime = 180                     // 音乐固定 3 分钟
    const assemblyTime = 60                   // 拼接固定 1 分钟

    return fixedTime + keyframeTime + musicTime + videoSegmentTime + assemblyTime
  }

  // ✅ 格式化时间显示（MM:SS）
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const MUSIC_COUNTDOWN_SECONDS = 180
  const [musicCountdown, setMusicCountdown] = useState(MUSIC_COUNTDOWN_SECONDS)
  const isVideoMusicStepActive = (() => {
    if (agentType !== 'video' || !effectiveIsGenerating || !activeTodoMessage) return false
    const todoStatus = ((activeTodoMessage).event_data?.status || '').toLowerCase()
    if (todoStatus === 'cancelled' || todoStatus === 'failed' || todoStatus === 'interrupted') return false

    const eventTypes = new Set(messages.map(m => m.event_type).filter(Boolean) as string[])
    const completedSteps = new Set<string>((activeTodoMessage).event_data?.completed_steps || [])
    const hasAnyOrCompleted = completionPredicate(eventTypes, completedSteps)
    const reflTotal = (activeTodoMessage).event_data?.keyframe_reflection_total
    const reflDone = (activeTodoMessage).event_data?.keyframe_reflection_completed ?? 0
    const storyboardsActuallyDone =
      hasAnyOrCompleted(['keyframes_generated']) &&
      !(Number(reflTotal) > 0 && reflDone < Number(reflTotal))
    const wfMsg = pickWorkflowStateMessageForTodo(messages, currentRunId)
    const wfSrc = wfMsg ? (wfMsg.event_data ?? wfMsg) : null
    const pathEntries =
      wfSrc && Array.isArray(wfSrc.path) && wfSrc.path.length > 0
        ? wfSrc.path
        : null
    const steps = buildVideoTodoStepsFromPath(
      pathEntries,
      t,
      hasAnyOrCompleted,
      storyboardsActuallyDone,
      musicData,
    )
    const firstNotDone = steps.findIndex(s => !s.done)
    const activeIdx = firstNotDone === -1 ? steps.length - 1 : firstNotDone
    return steps[activeIdx]?.id === 'music'
  })()

  useEffect(() => {
    if (!isVideoMusicStepActive) {
      // 优先用后端 music step 的 est_seconds，缺失回退 180s
      setMusicCountdown(getBackendStepEstSeconds('music') ?? MUSIC_COUNTDOWN_SECONDS)
      return
    }
    const timer = setInterval(() => {
      setMusicCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () =>{  clearInterval(timer) }
  }, [getBackendStepEstSeconds, isVideoMusicStepActive])

  // ✅ 简单 agent（image/music/story/video_gen）整体倒计时：优先后端 total_est_seconds，回退每 agent 经验值
  const IMAGE_COUNTDOWN_SECONDS = 60
  const SIMPLE_AGENT_FALLBACK_SECONDS: Record<string, number> = {
    image: IMAGE_COUNTDOWN_SECONDS,
    music: MUSIC_COUNTDOWN_SECONDS,
    story: 30,
    video_gen: 120,
  }
  const isSimpleAgentType =
    agentType === 'image' || agentType === 'music' || agentType === 'story' || agentType === 'video_gen'
  const simpleAgentEstSeconds = (() => {
    const src = getBackendWorkflowTimeSource()
    const backend = src?.total_est_seconds
    if (typeof backend === 'number' && backend > 0) return backend
    return SIMPLE_AGENT_FALLBACK_SECONDS[agentType as string] ?? IMAGE_COUNTDOWN_SECONDS
  })()
  const [imageCountdown, setImageCountdown] = useState(IMAGE_COUNTDOWN_SECONDS)
  useEffect(() => {
    if (!effectiveIsGenerating || !isSimpleAgentType) {
      setImageCountdown(simpleAgentEstSeconds)
      return
    }
    const timer = setInterval(() => {
      setImageCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () =>{  clearInterval(timer) }
  }, [effectiveIsGenerating, isSimpleAgentType, simpleAgentEstSeconds])

  // ✅ 追踪已用时间和生成开始时间（每秒更新，仅在 video 模式下）
  useEffect(() => {
    if (!effectiveIsGenerating || agentType !== 'video') {
      // 生成停止时重置
      if (!effectiveIsGenerating) {
        setElapsedTime(0)
        generationStartTimeRef.current = null
        lastRemainingRef.current = null
        lastElapsedTimeRef.current = 0
      }
      return
    }

    // 记录生成开始时间
    if (!generationStartTimeRef.current) {
      generationStartTimeRef.current = Date.now()
    }

    const timer = setInterval(() => {
      setElapsedTime(prev => prev + 1)
    }, 1000)

    return () =>{  clearInterval(timer) }
  }, [effectiveIsGenerating, agentType])

  const [showCutiAvatarLightbox, setShowCutiAvatarLightbox] = useState(false)
  // Sora 模型选择确认对话框状态
  const [showSoraDialog, setShowSoraDialog] = useState(false)
  const [pendingSoraModel, setPendingSoraModel] = useState<string>('')
  // 对话中点击结果图打开的详情（放大、下载、分享、分格）
  const [chatImageDetail, setChatImageDetail] = useState<{ url: string; title: string } | null>(null)
  const [chatShareDialog, setChatShareDialog] = useState(false)
  const [chatShareMode, setChatShareMode] = useState<'normal' | 'gift'>('normal')
  const [chatSplitMode, setChatSplitMode] = useState(false)
  const [chatSplitRows, setChatSplitRows] = useState(3)
  const [chatSplitCols, setChatSplitCols] = useState(4)
  const [chatSplitTiles, setChatSplitTiles] = useState<TileInfo[] | null>(null)
  const [chatSplitSplitting, setChatSplitSplitting] = useState(false)
  const [chatSplitError, setChatSplitError] = useState<string | null>(null)
  const [chatPreviewTile, setChatPreviewTile] = useState<TileInfo | null>(null)
  /** 带 logo 水印的分享图 dataUrl / blob */
  const [chatShareWatermarkedUrl, setChatShareWatermarkedUrl] = useState<string | null>(null)
  const [chatShareWatermarkedBlob, setChatShareWatermarkedBlob] = useState<Blob | null>(null)

  // 配置面板展开状态
  // 拖拽上传状态
  const [isDragOver, setIsDragOver] = useState(false)
  const [audioCropOpen, setAudioCropOpen] = useState(false)
  const [audioCropTarget, setAudioCropTarget] = useState<{ index: number; file: File } | null>(null)
  const previousUploadedFilesLengthRef = useRef(uploadedFiles.length || 0)
  const suggestedCropDurationSec = useMemo(
    () =>
      resolveAutoCropTargetDurationSec(
        (duration[0] ?? DEFAULT_VIDEO_OPTIONS.duration),
        message,
        { panelDurationExplicit: durationPanelExplicit },
      ),
    [duration, message, durationPanelExplicit],
  )
  const pillWrapperRef = useRef<HTMLDivElement>(null)
  const spotlightRef = useRef<HTMLDivElement>(null)

  const SPOTLIGHT_GRADIENT = (x: number, y: number) =>
    `radial-gradient(circle 280px at ${x}px ${y}px, rgba(236,72,153,0.75) 0%, rgba(168,85,247,0.45) 30%, rgba(192,132,252,0.2) 55%, transparent 75%)`

  const resetChatImageDetail = () => {
    setChatImageDetail(null)
    setChatShareDialog(false)
    setChatShareMode('normal')
    setChatSplitMode(false)
    setChatSplitTiles(null)
    setChatSplitError(null)
    setChatPreviewTile(null)
    setChatShareWatermarkedUrl(null)
    setChatShareWatermarkedBlob(null)
  }

  // 分享弹窗打开时，为原图生成带 logo 水印的图片
  useEffect(() => {
    if (!chatShareDialog || !chatImageDetail) {
      setChatShareWatermarkedUrl(null)
      setChatShareWatermarkedBlob(null)
      return
    }
    let cancelled = false
    const isCancelled = () => cancelled
    void (async () => {
      try {
        if (chatPreviewTile) {
          // tile 已经在 splitCollage 时带了水印，直接复用
          if (!isCancelled()) {
            setChatShareWatermarkedUrl(chatPreviewTile.dataUrl)
            setChatShareWatermarkedBlob(chatPreviewTile.blob)
          }
        } else {
          const { blob, dataUrl } = await addLogoToImage(chatImageDetail.url)
          if (!isCancelled()) {
            setChatShareWatermarkedUrl(dataUrl)
            setChatShareWatermarkedBlob(blob)
          }
        }
      } catch (e) {
        console.error('Failed to generate watermarked share image:', e)
      }
    })()
    return () => { cancelled = true }
  }, [chatImageDetail, chatPreviewTile, chatShareDialog])

  const handleChatImageDownload = async (img: { url: string; title: string }) => {
    try {
      // 添加 logo 水印后下载
      const { blob } = await addLogoToImage(img.url)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${img.title.replace(/\s+/g, '_')}.png`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (e) {
      console.error('Download failed:', e)
      toast.error(t('download') + ' failed')
    }
  }

  const handleChatSplitCollage = async () => {
    if (!chatImageDetail) return
    setChatSplitSplitting(true)
    setChatSplitError(null)
    try {
      const tiles = await splitCollage(chatImageDetail.url, {
        rows: chatSplitRows,
        cols: chatSplitCols,
        padding: 0,
        watermark: { url: 'watermark.png', scale: 0.2, margin: 10, opacity: 0.8 },
      })
      setChatSplitTiles(tiles)
    } catch (e) {
      setChatSplitError(
        e instanceof Error && e.message.includes('cross-origin')
          ? (t('splitCorsError') || 'Image does not support cross-origin access.')
          : (t('splitError') || 'Failed to split image.'),
      )
    } finally {
      setChatSplitSplitting(false)
    }
  }

  const handleCopyLink = async () => {
    if (!chatImageDetail) return
    try {
      const basePath = (import.meta.env.BASE_URL || '').replace(/\/$/, '')
      const shareUrl = `${window.location.origin}${basePath}/${language}/share/image?mode=normal&image=${encodeURIComponent(chatImageDetail.url)}&title=${encodeURIComponent(chatImageDetail.title)}`
      await navigator.clipboard.writeText(shareUrl)
      toast.success(t('copyLinkSuccess'))
    } catch (e) {
      toast.error(displayValue(e))
    }
  }

  const handleShareDirectly = async () => {
    if (!chatImageDetail) return
    const shareTitle = chatImageDetail.title
    const shareText = t('shareImageDescription') || 'Check out this image'
    const basePath = (import.meta.env.BASE_URL || '').replace(/\/$/, '')
    const shareUrl = `${window.location.origin}${basePath}/${language}/share/image?mode=normal&image=${encodeURIComponent(chatImageDetail.url)}&title=${encodeURIComponent(shareTitle)}`
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title: shareTitle, text: shareText, url: shareUrl })
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          try { await navigator.clipboard.writeText(shareUrl); toast.success(t('copyLinkSuccess')) } catch { toast.error(displayValue(e)) }
        }
      }
    } else {
      try { await navigator.clipboard.writeText(shareUrl); toast.success(t('copyLinkSuccess')) } catch (e) { toast.error(displayValue(e)) }
    }
  }

  const CHAT_GRID_PRESETS = [
    { label: '1×1', rows: 1, cols: 1 },
    { label: '2×3', rows: 2, cols: 3 },
    { label: '3×5', rows: 3, cols: 5 },
  ]

  // 创建拖拽处理器
  const dragDropHandler = createDragDropHandler(
    setIsDragOver,
    (files: File[]) => {
      const { validFiles } = validateFiles(files, uploadedFiles, t)
      if (validFiles.length > 0 && onFileUpload) {
        onFileUpload(validFiles)
      }
    },
    () => effectiveIsGenerating,
    t,
  )

  const validateAndUploadFiles = (files: File[]) => {
    if (!onFileUpload) return

    const { validFiles } = validateFiles(files, uploadedFiles, t)
    if (validFiles.length > 0) {
      onFileUpload(validFiles)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files)
      validateAndUploadFiles(files)
      // Reset input value to allow selecting the same file again
      e.target.value = ''
    }
  }

  const handleOpenAudioCrop = (index: number, file: File) => {
    setAudioCropTarget({ index, file })
    setAudioCropOpen(true)
  }

  useEffect(() => {
    const files = uploadedFiles
    const previousLength = previousUploadedFilesLengthRef.current
    if (files.length > previousLength) {
      const addedFiles = files.slice(previousLength)
      const audioIndex = addedFiles.findIndex(file => file.type.startsWith('audio/'))
      if (audioIndex >= 0) {
        const index = previousLength + audioIndex
        const file = files[index]
        if (!file) return
        setAudioCropTarget({ index, file })
        setAudioCropOpen(true)
      }
    }
    previousUploadedFilesLengthRef.current = files.length
  }, [uploadedFiles])

  const handleApplyAudioCrop = (nextFile: File) => {
    if (!audioCropTarget || !onFileReplace) return
    onFileReplace(audioCropTarget.index, nextFile)
  }


  // 空态一行；多行自动长高，超出后在框内滚动（不要用 stadium 圆角，否则会长成胶囊切字）
  const INPUT_MIN_H = 24
  const INPUT_MAX_H = 240
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    const lineCount = (message || '').split('\n').length
    if (lineCount <= 1 && !message.trim()) {
      textarea.style.height = `${INPUT_MIN_H}px`
      return
    }
    textarea.style.height = 'auto'
    const newHeight = Math.max(INPUT_MIN_H, Math.min(textarea.scrollHeight, INPUT_MAX_H))
    textarea.style.height = `${newHeight}px`
  }, [message])

  // 手机端右滑返回对话列表
  const swipeStartRef = useRef<{ x: number; y: number } | null>(null)
  const SWIPE_THRESHOLD = 80
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!onSwipeRight) return
    const t = e.touches[0]
    if (!t) return
    swipeStartRef.current = { x: t.clientX, y: t.clientY }
  }, [onSwipeRight])
  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!onSwipeRight || !swipeStartRef.current) return
    const t = e.changedTouches[0]
    if (!t) return
    const dx = t.clientX - swipeStartRef.current.x
    const dy = t.clientY - swipeStartRef.current.y
    swipeStartRef.current = null
    if (dx > SWIPE_THRESHOLD && Math.abs(dy) < Math.abs(dx) * 1.5) {
      onSwipeRight()
    }
  }, [onSwipeRight])

  return (
    <div
      className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background"
      onClick={() => {
        if (onContainerClick) {
          onContainerClick()
        }
      }}
      onTouchStart={onSwipeRight ? handleTouchStart : undefined}
      onTouchEnd={onSwipeRight ? handleTouchEnd : undefined}
    >
      {/* Chat Header - px-4 与侧栏 padding 一致，避免红框处空白错位 */}
      {!hideHeader && <div className="sticky top-0 z-10 flex-shrink-0 bg-background/85 px-4 py-3 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[760px] items-center gap-3 min-w-0">
          <div className="h-9 w-9 shrink-0" />
          <div className="flex-1 min-w-0">
            <TooltipProvider delayDuration={300}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <h2 className="truncate text-center text-[15px] font-semibold text-foreground">{chatTitle}</h2>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-sm">
                  <p className="break-words">{chatTitle}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            {/*
            <p className="text-sm text-muted-foreground font-inter">
              {messages.length > 0
                ? agentType === "image"
                  ? t('imageCreationChatInProgress')
                  : agentType === "music"
                  ? t('musicCreationChatInProgress')
                  : agentType === "story"
                  ? t('storyCreationChatInProgress')
                  : t('videoCreationChatInProgress')
                : agentType === "image"
                ? t('startNewImageProject')
                : agentType === "music"
                ? t('startNewMusicProject')
                : agentType === "story"
                ? t('startNewStoryProject')
                : t('startNewVideoProject')}
            </p>
            */}
          </div>
          <div className="h-9 w-9 shrink-0" />
        </div>
      </div>}

      {/* Messages */}
      <ScrollArea
        ref={messageScrollRootRef}
        type="always"
        className="flex-1 min-h-0 px-4 py-4 max-sm:pb-2 min-w-0 overflow-x-hidden"
        viewportClassName="[&>div]:!block [&>div]:!min-w-0 [scrollbar-gutter:stable]"
      >
        {displayMessages.length > 0 ? (
          <div className={`mx-auto w-full max-w-[760px] space-y-5 min-w-0 overflow-x-hidden ${todoMessage ? (todoCollapsed ? 'pb-20' : 'pb-44') : ''}`}>
            {displayMessages.map((msg, index) => {
              return (
              // ✅ Typewriter: only animate the latest AI message while generating (prevents re-typing old history)
                <div
                  key={msg.id ?? msg.message_id ?? `${msg.run_id ?? 'message'}-${msg.timestamp ?? index}`}
                  className={`flex ${
                    msg.role === 'user' || msg.role === 'human'
                      ? 'justify-end'
                      : 'justify-start'
                  } min-w-0 items-start gap-2.5`}
                >
                  {msg.role !== 'user' && msg.role !== 'human' && (
                    <button
                      type="button"
                      onClick={() =>{  setShowCutiAvatarLightbox(true) }}
                      className="mt-1 flex-shrink-0 rounded-full focus:outline-none focus:ring-2 focus:ring-primary/50"
                      title={t('da.composer.viewAvatar')}
                    >
                      <img
                        src={aiAvatar}
                        alt="AI"
                        className="h-10 w-10 rounded-full object-cover"
                      />
                    </button>
                  )}
                  <div
                    className={`min-w-0 overflow-hidden [overflow-wrap:anywhere] [box-shadow:var(--chat-shadow-bubble)] max-w-[78%] rounded-3xl px-4 py-3 text-[15px] leading-[1.55] ${
                      msg.role === 'user' || msg.role === 'human'
                        ? 'rounded-tr-md bg-[var(--chat-bubble-user)] text-[var(--chat-bubble-user-foreground)]'
                        : 'rounded-tl-md bg-[var(--chat-bubble-ai)] text-foreground'
                    }`}
                  >
                    {/* Display video analysis details - 使用后端提供的消息 */}
                    {msg.event_type === 'video_analysis' ? (
                      msg.event_data ? (
                        <>
                          <p className="text-sm leading-relaxed font-inter whitespace-pre-wrap">
                            {msg.content || t('videoAnalysisCompleted')}
                          </p>
                          {msg.timestamp && (
                            <p className="text-[10px] opacity-70 mt-2 font-inter">
                              {new Date(msg.timestamp).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                hour12: false,
                              })}
                            </p>
                          )}
                        </>
                      ) : (
                      // Loading state for video_analysis
                        <div className="flex items-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <p className="text-sm font-inter">
                            {t('analyzingVideo')}
                          </p>
                        </div>
                      )
                    ) : msg.event_type === 'story_agent_generated' ? (
                    // 特殊处理故事生成事件，显示完整故事内容
                      <>
                        <div className="text-sm leading-relaxed font-inter">
                          {msg.event_data?.story_content && (
                            <div className="bg-white/5 p-4 rounded-lg border border-white/10">
                              <ReactMarkdown
                                className="prose prose-invert prose-sm max-w-none"
                                components={{
                                  h1: ({ children }) => <h1 className="text-base font-bold text-accent-cyan mb-2">{children}</h1>,
                                  h2: ({ children }) => <h2 className="text-sm font-semibold text-accent-cyan mb-2">{children}</h2>,
                                  h3: ({ children }) => <h3 className="text-sm font-medium text-accent-cyan mb-1">{children}</h3>,
                                  p: ({ children }) => <p className="text-sm leading-relaxed mb-2">{children}</p>,
                                  strong: ({ children }) => <strong className="font-semibold text-white dark:text-foreground">{children}</strong>,
                                  em: ({ children }) => <em className="italic text-gray-300 dark:text-gray-400">{children}</em>,
                                }}
                              >
                                {msg.event_data.story_content}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : msg.event_type === 'music_agent_generated' ? (
                    // 特殊处理音乐生成事件
                      <>
                        <div className="text-sm leading-relaxed font-inter">
                          {/* 显示 music_content 字段 */}
                          {msg.event_data?.music_content && (
                            <div className="mb-2 prose prose-sm max-w-none dark:prose-invert">
                              <ReactMarkdown
                                components={{
                                // 自定义链接组件，添加 target="_blank" 和 rel="noopener noreferrer"
                                  a: ({ href, children, ...props }) => (
                                    <a
                                      href={href}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-400 hover:text-blue-300 underline"
                                      {...props}
                                    >
                                      {children}
                                    </a>
                                  ),
                                  // 自定义图片组件
                                  img: ({ src, alt, ...props }) => (
                                    <img
                                      src={src}
                                      alt={alt}
                                      className="max-w-full h-auto rounded-lg my-2"
                                      {...props}
                                    />
                                  ),
                                  // 自定义音频组件（支持 HTML audio 标签）
                                  audio: ({ src, children, ...props }: ComponentProps<'audio'>) => (
                                    <audio
                                      controls
                                      className="w-full my-2"
                                      {...props}
                                    >
                                      {src && <source src={src} type="audio/mpeg" />}
                                      {children}
                                      {t('da.composer.audioUnsupported')}
                                    </audio>
                                  ),
                                  // 自定义 source 组件（用于 audio 标签内部）
                                  source: ({ src, type, ...props }: ComponentProps<'source'>) => (
                                    <source src={src} type={type || 'audio/mpeg'} {...props} />
                                  ),
                                  // 自定义音频链接，转换为可播放的音频组件
                                  p: ({ children, ...props }) => {
                                  // 检查是否包含音频链接
                                    const text = typeof children === 'string' ? children : ''
                                    const audioMatch = text.match(/\[([^\]]+)\]\((https:\/\/[^)]+\.mp3[^)]*)\)/)

                                    if (audioMatch) {
                                      const [, linkText, audioUrl] = audioMatch
                                      return (
                                        <div className="my-2">
                                          <p className="mb-2">{linkText}</p>
                                          <audio controls className="w-full">
                                            <source src={audioUrl} type="audio/mpeg" />
                                            {t('da.composer.audioUnsupported')}
                                          </audio>
                                        </div>
                                      )
                                    }

                                    return <p {...props}>{children}</p>
                                  },
                                }}
                              >
                                {msg.event_data.music_content}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : msg.event_type === 'video_agent_generated' ? (
                    // ✅ 视频直生完成：手机端 showVideoResultsInChat 时在对话中直接显示视频；否则仅文案，视频在右侧创作空间
                      (() => {
                        const videos = extractGeneratedVideoItems({
                          ...(msg.event_data || {}),
                          content: msg.content,
                        })
                        const successText = (msg.event_data?.message as string) || t('videosGeneratedSuccess')
                        return (
                          <>
                            {showVideoResultsInChat && videos.length > 0 ? (
                              <div className="space-y-3">
                                <div className="text-sm leading-relaxed font-inter flex items-center gap-2">
                                  <CheckCircle className="w-4 h-4 text-green-500 shrink-0" />
                                  <span>{successText}</span>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                  {videos.map((v, idx: number) => (
                                    v.video_url ? (
                                      <div key={idx} className="overflow-hidden rounded-lg border border-white/20 dark:border-gray-700/50 bg-black shadow-lg">
                                        <video
                                          src={v.video_url}
                                          poster={v.cover_image_url || undefined}
                                          controls
                                          playsInline
                                          preload="metadata"
                                          className="w-full h-auto object-contain max-h-64"
                                        />
                                      </div>
                                    ) : null
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <div className="text-sm leading-relaxed font-inter flex items-center gap-2">
                                <CheckCircle className="w-4 h-4 text-green-500" />
                                <span>{successText}</span>
                              </div>
                            )}
                            {msg.timestamp && (
                              <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-2">
                                {formatChatTimestamp(msg.timestamp)}
                              </p>
                            )}
                          </>
                        )
                      })()
                    ) : msg.event_type === 'image_agent_generated' ? (
                    // ✅ 图片生成完成：手机端 showImageResultsInChat 时在对话中直接显示图片；否则仅文案，图片在右侧创作空间
                      (() => {
                        const content = msg.event_data?.image_content
                        const urls: string[] = []
                        if (content && showImageResultsInChat) {
                          const markdownRegex = /!?\[([^\]]*)\]\(([^\s)]+\.(jpg|jpeg|png|gif|webp)[^\s)]*)\)/gi
                          let m: RegExpExecArray | null
                          while ((m = markdownRegex.exec(content)) !== null) {
                            if (m[2]) urls.push(m[2].trim())
                          }
                          if (urls.length === 0) {
                            const directRegex = /((?:https?:\/\/)?[^\s]+\.(jpg|jpeg|png|gif|webp))/gi
                            let d: RegExpExecArray | null
                            while ((d = directRegex.exec(content)) !== null) {
                              if (d[1]) urls.push(d[1].trim())
                            }
                          }
                        }
                        return (
                          <>
                            {showImageResultsInChat && urls.length > 0 ? (
                              <div className="space-y-3">
                                <div className="text-sm leading-relaxed font-inter flex items-center gap-2">
                                  <CheckCircle className="w-4 h-4 text-green-500 shrink-0" />
                                  <span>{t('imagesGeneratedSuccess')}</span>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                  {urls.map((src, idx) => (
                                    <div key={idx} className="group relative overflow-hidden rounded-lg border border-white/20 dark:border-gray-700/50 bg-black/5 dark:bg-black/20 shadow-lg hover:shadow-xl transition-all duration-300 flex items-center justify-center">
                                      <img
                                        src={src}
                                        alt=""
                                        className="w-full h-auto object-contain max-h-64 cursor-pointer hover:opacity-90 transition-opacity"
                                        onClick={() =>{  setChatImageDetail({ url: src, title: t('generatedImage') + ` ${idx + 1}` }) }}
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <div className="text-sm leading-relaxed font-inter flex items-center gap-2">
                                <CheckCircle className="w-4 h-4 text-green-500" />
                                <span>{t('imagesGeneratedSuccess')}</span>
                              </div>
                            )}
                            {msg.timestamp && (
                              <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-2">
                                {formatChatTimestamp(msg.timestamp)}
                              </p>
                            )}
                          </>
                        )
                      })()
                    ) : msg.event_type === 'image_agent_generated_OLD' ? (
                    // 保留旧版本的显示逻辑作为备份（使用 _OLD 后缀以禁用）
                      <>
                        <div className="text-sm leading-relaxed font-inter">
                          {/* 显示 image_content 字段 */}
                          {msg.event_data?.image_content && (
                            <div className="mb-2 prose prose-sm max-w-none dark:prose-invert">
                              <ReactMarkdown
                                components={{
                                // 自定义链接组件，添加 target="_blank" 和 rel="noopener noreferrer"
                                  a: ({ href, children, ...props }) => (
                                    <a
                                      href={href}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-400 hover:text-blue-300 underline"
                                      {...props}
                                    >
                                      {children}
                                    </a>
                                  ),
                                  // 自定义图片组件，增强显示效果
                                  img: ({ src, alt, ...props }) => (
                                    <div className="my-4">
                                      <img
                                        src={src}
                                        alt={alt}
                                        className="max-w-full h-auto rounded-lg cursor-pointer hover:opacity-90 transition-opacity border border-white/20"
                                        onClick={() => window.open(src, '_blank')}
                                        {...props}
                                      />
                                    </div>
                                  ),
                                  // 自定义段落组件，处理图像链接
                                  p: ({ children, ...props }) => {
                                  // 检查是否包含图像链接
                                    const text = typeof children === 'string' ? children : ''
                                    const imageMatch = text.match(/!?\[([^\]]*)\]\((https:\/\/[^)]+\.(jpg|jpeg|png|gif|webp)[^)]*)\)/i)

                                    if (imageMatch) {
                                      const [, altText, imageUrl] = imageMatch
                                      return (
                                        <div className="my-4">
                                          <div className="aspect-auto overflow-hidden rounded-lg border border-white/20 bg-black/5 flex items-center justify-center">
                                            <img
                                              src={imageUrl}
                                              alt={altText || 'Generated Image'}
                                              className="max-w-full h-auto cursor-pointer hover:opacity-90 transition-opacity"
                                              onClick={() => window.open(imageUrl, '_blank')}
                                            />
                                          </div>
                                          {altText && (
                                            <p className="text-sm text-center mt-2 text-gray-400">{altText}</p>
                                          )}
                                        </div>
                                      )
                                    }

                                    return <p {...props}>{children}</p>
                                  },
                                }}
                              >
                                {msg.event_data.image_content}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : msg.event_type === 'generation_failed' ? (
                    // 生成失败卡片：展示官方原因（已脱敏）+ 失败项明细，不暴露内部信息
                      (() => {
                        const fd = msg.event_data || {}
                        const items = Array.isArray(fd.failed_items) ? fd.failed_items : []
                        const headline = fd.message || msg.content || t('generationFailed.title')
                        // 失败明细仅对逐镜头阶段（keyframe/video）有意义；音乐/角色等单依赖阶段标题已含原因，明细纯属重复，隐藏。
                        const showItemDetails =
                          (fd.stage === 'keyframe' || fd.stage === 'video') && items.length > 0
                        return (
                          <>
                            <div className="mt-1 p-4 bg-gradient-to-r from-rose-50 to-orange-50 dark:from-rose-900/20 dark:to-orange-900/20 rounded-xl border border-rose-200 dark:border-rose-800 w-full min-w-0 max-w-full overflow-hidden">
                              <div className="flex items-center gap-2 mb-2">
                                <AlertTriangle className="w-4 h-4 text-rose-600 dark:text-rose-300 flex-shrink-0" />
                                <span className="text-sm font-semibold text-rose-900 dark:text-rose-100">
                                  {t('generationFailed.title')}
                                </span>
                              </div>
                              <p className="text-sm text-rose-900/90 dark:text-rose-100/90 break-words leading-relaxed">
                                {headline}
                              </p>
                              {showItemDetails && (
                                <div className="mt-3">
                                  <p className="text-xs font-medium text-rose-800/80 dark:text-rose-200/80 mb-1">
                                    {t('generationFailed.itemsHeader')}
                                  </p>
                                  <ul className="space-y-1">
                                    {items.map((it, idx: number) => {
                                      const hasIndex = it.index != null && it.index !== ''
                                      const idxLabel = hasIndex
                                        ? displayValue(it.index)
                                        : t('generationFailed.itemFallbackIndex').replace('{index}', displayValue(idx + 1))
                                      return (
                                        <li
                                          key={idx}
                                          className="text-xs text-rose-900/85 dark:text-rose-100/85 break-words"
                                        >
                                          <span className="font-medium">{idxLabel}</span>
                                          {it.reason ? <>：{it.reason}</> : null}
                                        </li>
                                      )
                                    })}
                                  </ul>
                                </div>
                              )}
                            </div>
                            {msg.timestamp && (
                              <p className="text-[10px] opacity-70 mt-2 font-inter">
                                {new Date(msg.timestamp).toLocaleTimeString([], {
                                  hour: '2-digit',
                                  minute: '2-digit',
                                  hour12: false,
                                })}
                              </p>
                            )}
                          </>
                        )
                      })()
                    ) : msg.event_type === 'interrupt' ? (
                    // Display interrupt event (agent_selection or video step gate)；支持 detail 返回的 event_data.interrupt_data
                    // run_id 优先从消息体取（msg.run_id / event_data.run_id），避免用户 regenerate 后「最新任务」不是当前 interrupt 的 run
                      (() => {
                        const interruptData = msg.interrupt_data ?? msg.event_data?.interrupt_data
                        const interruptType = msg.interrupt_type ?? msg.event_data?.interrupt_type
                        const continued = !!msg.event_data?.continued
                        const msgId = msg.message_id ?? msg.event_data?.message_id
                        const runIdForResume = msg.run_id ?? msg.event_data?.run_id ?? currentRunId ?? null
                        const canContinue = interruptData?.step && runIdForResume && msgId != null && !continued
                        const buildVideoContinuePayload = () => {
                          const base = {
                            type: 'video_continue' as const,
                            run_id: runIdForResume,
                            interrupt_msgid: msgId,
                          }
                          if (interruptData?.smart_clip && isSmartClipReadyForInterrupt(interruptData)) {
                            return {
                              ...base,
                              smart_clip: buildRecommendedSmartClipDecision(
                                interruptData.smart_clip,
                              ),
                            }
                          }
                          return base
                        }
                        const autoResumeDismissedForMsg =
                          !!(msg.event_data)?.auto_resume_dismissed ||
                        (msgId != null && dismissedAutoResumeByMsgId[Number(msgId)])
                        const autoResumeAt = interruptData?.auto_resume_at
                        // 失败暂停：禁止 15s 自动继续，按钮改为「重试该步骤」
                        const suppressAutoResume =
                          interruptData?.disable_auto_resume === true ||
                        displayValue(interruptData?.step ?? '').startsWith('failed_')
                        // 失败暂停同样允许用户继续/重试：用户可在对话里调整后继续，这里仅关闭 15s 自动继续。
                        return (
                          <>
                            {/* 不展示「事件: interrupt」文案，只展示提示 + 继续按钮 */}
                            {/* 视频流程关键步骤暂停：展示提示文案 + 继续 / 已继续 */}
                            {interruptData?.step && (
                              <div className="mt-1 p-4 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 rounded-xl border border-amber-200 dark:border-amber-800 w-full min-w-0 max-w-full overflow-hidden text-center">
                                {continued ? (
                                  <p className="text-sm font-medium text-amber-900 dark:text-amber-100 mb-3 break-words">
                                    {resolveVideoInterruptDisplayText(interruptData, t, 'pause')}
                                  </p>
                                ) : null}
                                {continued ? (
                                  <div className="flex flex-col items-center gap-2">
                                    <span className="inline-block text-sm text-amber-700 dark:text-amber-300">{t('continued') || '已继续'}</span>
                                  </div>
                                ) : canContinue ? (
                                  <div className="flex flex-col items-center gap-3 w-full">
                                    {(() => {
                                      const sc: SmartClipPayload | undefined = interruptData.smart_clip
                                      if (!sc || sc.status !== 'ready') return null
                                      const handleSmartClipConfirm = (decision: SmartClipDecision) => {
                                        onInterruptOptionClick?.(
                                          {
                                            type: 'video_continue',
                                            run_id: runIdForResume,
                                            interrupt_msgid: msgId,
                                            smart_clip: decision,
                                          },
                                          msg.event_data?.thread_id || threadId || '',
                                        )
                                      }
                                      return (
                                        <div className="w-full pb-3 border-b border-dashed border-amber-300/40 dark:border-amber-700/40">
                                          <SmartClipPanel
                                            smartClip={sc}
                                            onConfirm={handleSmartClipConfirm}
                                            t={t}
                                          />
                                        </div>
                                      )
                                    })()}
                                    {autoResumeDismissedForMsg ? (
                                      <div className="flex flex-col items-center gap-2 w-full">
                                        <span className="inline-flex items-center justify-center px-3 py-1.5 rounded-full bg-amber-200/90 dark:bg-amber-800/65 text-amber-950 dark:text-amber-50 text-sm font-semibold tracking-tight shadow-sm border border-amber-300/80 dark:border-amber-600/50">
                                          {t('interrupt.statusPaused')}
                                        </span>
                                        <p className="text-sm text-amber-900/95 dark:text-amber-100 break-words max-w-full leading-relaxed">
                                          {resolveVideoInterruptDisplayText(
                                            interruptData,
                                            t,
                                            'pausedIntent',
                                          )}
                                        </p>
                                      </div>
                                    ) : suppressAutoResume ? (
                                      <div className="flex flex-col items-center gap-2 w-full">
                                        <span className="inline-flex items-center justify-center px-3 py-1.5 rounded-full bg-rose-200/90 dark:bg-rose-900/55 text-rose-950 dark:text-rose-50 text-sm font-semibold tracking-tight shadow-sm border border-rose-300/80 dark:border-rose-700/50">
                                          {t('interrupt.statusFailed')}
                                        </span>
                                        <p className="text-sm font-medium text-amber-900 dark:text-amber-100 mb-1 break-words leading-relaxed">
                                          {resolveVideoInterruptDisplayText(
                                            interruptData,
                                            t,
                                            'pause',
                                          )}
                                        </p>
                                      </div>
                                    ) : (
                                      <p className="text-sm font-medium text-amber-900 dark:text-amber-100 mb-1 break-words">
                                        {resolveVideoInterruptDisplayText(
                                          interruptData,
                                          t,
                                          'pause',
                                        )}
                                      </p>
                                    )}
                                    <div className="flex flex-wrap items-center justify-center gap-2">
                                      <Button
                                        size="sm"
                                        className={
                                          autoResumeDismissedForMsg
                                            ? 'bg-amber-600 hover:bg-amber-700 text-white shadow-md ring-2 ring-amber-400/45 dark:ring-amber-500/35'
                                            : 'bg-amber-600 hover:bg-amber-700 text-white'
                                        }
                                        onClick={() => onInterruptOptionClick?.(
                                          buildVideoContinuePayload(),
                                          msg.event_data?.thread_id || threadId || '',
                                        )}
                                      >
                                        {t('continue')}
                                      </Button>
                                      {autoContinueOnInterrupt &&
                                runIdForResume &&
                                !autoResumeDismissedForMsg &&
                                !suppressAutoResume && (
                                        <>
                                          <TooltipProvider>
                                            <Tooltip>
                                              <TooltipTrigger asChild>
                                                <Button
                                                  type="button"
                                                  variant="outline"
                                                  size="sm"
                                                  className="border-amber-300 text-amber-900 dark:text-amber-100 dark:border-amber-700"
                                                  onClick={asyncEvent(async () => {
                                                    const tid = msg.event_data?.thread_id || threadId || ''
                                                    const mid = Number(msgId)
                                                    if (!tid || !runIdForResume || !Number.isFinite(mid)) {
                                                      toast.error(t('interrupt.dismissAutoResumeFail'))
                                                      return
                                                    }
                                                    try {
                                                      const res = await agentApi.dismissInterruptAutoResume({
                                                        thread_id: tid,
                                                        interrupted_run_id: runIdForResume,
                                                        interrupt_msgid: mid,
                                                      })
                                                      if (res.code === 0) {
                                                        setDismissedAutoResumeByMsgId(p => ({ ...p, [mid]: true }))
                                                        toast.success(t('interrupt.dismissAutoResumeOk'))
                                                      } else {
                                                        toast.error(res.message || t('interrupt.dismissAutoResumeFail'))
                                                      }
                                                    } catch (e: unknown) {
                                                      toast.error(e instanceof Error && e.message ? e.message : t('interrupt.dismissAutoResumeFail'))
                                                    }
                                                  })}
                                                >
                                                  {t('interrupt.dismissAutoResume')}
                                                </Button>
                                              </TooltipTrigger>
                                              <TooltipContent side="bottom" className="max-w-xs">
                                                <p>{t('interrupt.dismissAutoResumeHint')}</p>
                                              </TooltipContent>
                                            </Tooltip>
                                          </TooltipProvider>
                                          <InterruptCountdown
                                            deadlineAt={autoResumeAt}
                                            onZero={() => onInterruptOptionClick?.(
                                              buildVideoContinuePayload(),
                                              msg.event_data?.thread_id || threadId || '',
                                            )}
                                            labelAfter={t('interrupt.auto_continue_in')}
                                          />
                                        </>
                                      )}
                                    </div>
                                  </div>
                                ) : (
                                  <p className="text-sm font-medium text-amber-900 dark:text-amber-100 mb-3 break-words">
                                    {interruptData.message_key
                                      ? t(interruptData.message_key as TranslationKey)
                                      : (interruptData.message_default || t('continue'))}
                                  </p>
                                )}
                              </div>
                            )}
                            {interruptType === 'agent_selection' && interruptData?.available_agents && (
                              <div className="mt-4 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 rounded-xl border border-blue-200 dark:border-blue-800 w-full min-w-0 max-w-full overflow-hidden flex-shrink-0">
                                <p className="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-3">
                                  {t('selectContentType')}
                                </p>
                                <div className="grid gap-3 w-full min-w-0">
                                  {interruptData.available_agents.map((agent: string, index: number) => (
                                    <Button
                                      key={index}
                                      variant="outline"
                                      className="w-full justify-start h-auto p-4 text-left hover:bg-blue-100 dark:hover:bg-blue-800/50 border-blue-200 dark:border-blue-700 hover:border-blue-300 dark:hover:border-blue-600 transition-all min-w-0"
                                      onClick={() => onInterruptOptionClick?.(agent, msg.event_data?.thread_id || threadId || '')}
                                    >
                                      <div className="flex items-start gap-3 w-full min-w-0">
                                        <div className="w-2 h-2 bg-blue-500 rounded-full mt-2 flex-shrink-0"></div>
                                        <div className="flex-1 min-w-0">
                                          <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
                                            {t(`agentType.${agent}` as TranslationKey)}
                                          </p>
                                          <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
                                            {t(`agentType.${agent}.description` as TranslationKey)}
                                          </p>
                                        </div>
                                      </div>
                                    </Button>
                                  ))}
                                </div>
                              </div>
                            )}
                            {msg.timestamp && (
                              <p className="text-[10px] opacity-70 mt-2 font-inter">
                                {new Date(msg.timestamp).toLocaleTimeString([], {
                                  hour: '2-digit',
                                  minute: '2-digit',
                                  hour12: false,
                                })}
                              </p>
                            )}
                          </>
                        )
                      })()
                    ) : msg.event_type === 'user_input' ? (
                    // 已发送消息中的 display prompt 以文字显示（backend 可能存长文案，此处统一展示简短文案）
                      <>
                        <p className="text-sm leading-relaxed font-inter">
                          {getDisplayPromptForUserMessage(msg.content)}
                        </p>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : msg.event_type === 'video_generation_progress' ? (
                    // 🎯 显示视频生成进度条 - 使用与其他事件一致的样式
                      <>
                        <div className="text-sm leading-relaxed font-inter">
                          <div className="flex items-center gap-2 mb-3">
                            <div className="w-2 h-2 rounded-full bg-gradient-to-r from-blue-400 to-purple-400" />
                            <span className="font-medium">{t('videoGenerationProgress')}</span>
                          </div>

                          <div className="space-y-3">
                            {/* Progress Info */}
                            <div className="flex items-center justify-between text-sm">
                              <span>{msg.event_data?.completed}/{msg.event_data?.total} {t('clipsUnit')}</span>
                              <span>{msg.event_data?.progress_percent || 0}%</span>
                            </div>

                            {/* Progress Bar */}
                            <div className="w-full bg-white/10 rounded-full h-2 overflow-hidden">
                              <div
                                className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                style={{ width: `${msg.event_data?.progress_percent || 0}%` }}
                              />
                            </div>
                          </div>
                        </div>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : msg.event_type === 'generation_todo' ? (
                    // ✅ lovable-style todo list, driven by real SSE events (/api/cuti)
                      (() => {
                        const eventTypes = new Set(messages.map(m => m.event_type).filter(Boolean) as string[])

                        const shotsProgressPercent = (msg.event_data?.progress_percent ??
                          (() => {
                            // fallback: find last video_generation_progress message
                            for (let i = messages.length - 1; i >= 0; i--) {
                              const m = messages[i]
                              if (!m) continue
                              if (m.event_type === 'video_generation_progress') {
                                return m.event_data?.progress_percent ?? 0
                              }
                            }
                            return 0
                          })()) || 0
                        const shotsCompleted = msg.event_data?.completed
                        const shotsTotal = msg.event_data?.total
                        const kfApiTodo = keyframeTodoFallbackFromApi(keyframesData)
                        let keyframeCompleted = msg.event_data?.keyframe_completed
                        let keyframeTotal = msg.event_data?.keyframe_total
                        if (kfApiTodo && kfApiTodo.total > 0) {
                          keyframeCompleted = kfApiTodo.completed
                          keyframeTotal = kfApiTodo.total
                        }
                        const totalFromScenes = typeof scenesCount === 'number' && Number.isFinite(scenesCount) ? scenesCount : undefined
                        const effectiveShotsTotal = (shotsTotal != null && shotsTotal > 0)
                          ? shotsTotal
                          : totalFromScenes
                        const vidApiTodo = videoTodoFallbackFromApi(videosData, scenesCount)
                        let shotsProgressPercentForBar = shotsProgressPercent
                        let shotsCompletedForBar: number | undefined =
                          shotsCompleted
                        let shotsTotalForBar: number | undefined =
                          effectiveShotsTotal !== undefined && effectiveShotsTotal > 0
                            ? effectiveShotsTotal
                            : undefined
                        if (vidApiTodo && vidApiTodo.total > 0) {
                          shotsCompletedForBar = vidApiTodo.completed
                          shotsTotalForBar = vidApiTodo.total
                          shotsProgressPercentForBar =
                            Math.round((vidApiTodo.completed / vidApiTodo.total) * 100 * 10) / 10
                        }
                        const effectiveKeyframeTotal = (keyframeTotal != null && keyframeTotal > 0)
                          ? keyframeTotal
                          : totalFromScenes
                        const keyframeProgressPercent = (keyframeTotal != null && keyframeTotal > 0 && keyframeCompleted != null
                          ? Math.round((keyframeCompleted / keyframeTotal) * 100 * 10) / 10
                          : msg.event_data?.keyframe_progress_percent ??
                            (() => {
                              for (let i = messages.length - 1; i >= 0; i--) {
                                const m = messages[i]
                                if (!m) continue
                                if (m.event_type === 'keyframe_generation_progress' && m.event_data) {
                                  const c = m.event_data.completed
                                  const t = m.event_data.total
                                  return typeof t === 'number' && typeof c === 'number' && t > 0 ? Math.round((c / t) * 100) : 0
                                }
                              }
                              return 0
                            })()) || 0
                        const keyframeReflectionCompleted = msg.event_data?.keyframe_reflection_completed
                        const keyframeReflectionTotal = msg.event_data?.keyframe_reflection_total
                        const keyframeReflectionProgressPercent = (msg.event_data?.keyframe_reflection_progress_percent ??
                          (keyframeReflectionTotal != null && keyframeReflectionTotal > 0 && keyframeReflectionCompleted != null
                            ? Math.round((keyframeReflectionCompleted / keyframeReflectionTotal) * 100)
                            : (() => {
                              for (let i = messages.length - 1; i >= 0; i--) {
                                const m = messages[i]
                                if (!m) continue
                                if (m.event_type === 'keyframe_reflection_progress' && m.event_data) {
                                  const c = m.event_data.completed
                                  const t = m.event_data.total
                                  return typeof t === 'number' && typeof c === 'number' && t > 0 ? Math.round((c / t) * 100) : 0
                                }
                              }
                              return 0
                            })())) || 0
                        const todoStatus = msg.event_data?.status
                        const isCancelled = todoStatus === TaskStatus.CANCELLED
                        const isFailed = todoStatus === TaskStatus.FAILED
                        const isInterrupted = todoStatus === TaskStatus.INTERRUPTED || todoStatus === 'interrupted'

                        // ✅ 支持从后端恢复的 completed_steps
                        const completedSteps = new Set<string>(msg.event_data?.completed_steps || [])

                        const hasAnyOrCompleted = completionPredicate(eventTypes, completedSteps)

                        // ✅ 关键帧反思进行中时「分镜」不算 done，这样 active 和百分比都显示在分镜下而非镜头下
                        const reflTotalForDone = keyframeReflectionTotal
                        const reflDoneForDone = keyframeReflectionCompleted ?? 0
                        const storyboardsActuallyDone =
                          hasAnyOrCompleted(['keyframes_generated']) &&
                        !(Number(reflTotalForDone) > 0 && reflDoneForDone < Number(reflTotalForDone))

                        const wfMsgExpanded = pickWorkflowStateMessageForTodo(messages, currentRunId)
                        const wfSrcExpanded = wfMsgExpanded ? (wfMsgExpanded.event_data ?? wfMsgExpanded) : null
                        const pathEntriesExpanded =
                          wfSrcExpanded && Array.isArray(wfSrcExpanded.path) && wfSrcExpanded.path.length > 0
                            ? wfSrcExpanded.path
                            : null
                        const steps = buildVideoTodoStepsFromPath(
                          pathEntriesExpanded,
                          t,
                          hasAnyOrCompleted,
                          storyboardsActuallyDone,
                          musicData,
                        )

                        const firstNotDone = steps.findIndex(s => !s.done)
                        const activeIdx = effectiveIsGenerating && !isCancelled && !isFailed && !isInterrupted
                          ? (firstNotDone === -1 ? steps.length - 1 : firstNotDone)
                          : -1
                        const allDone = steps.every(s => s.done)




                        const kfTotal = keyframeTotal ?? effectiveKeyframeTotal

                        const reflTotal = keyframeReflectionTotal

                        const shotsTotalNum = shotsTotalForBar ?? 0
                        const shotsPct = Math.max(0, Math.min(100, shotsProgressPercentForBar))
                        let narrationCompleted = msg.event_data?.narration_completed
                        let narrationTotal = msg.event_data?.narration_total
                        if (narrationCompleted == null || narrationTotal == null) {
                          for (let i = messages.length - 1; i >= 0; i--) {
                            const m = messages[i]
                            if (!m) continue
                            if (m.event_type === 'narration_generation_progress' && m.event_data) {
                              narrationCompleted = m.event_data.completed
                              narrationTotal = m.event_data.total
                              break
                            }
                          }
                        }
                        const narrationPct = Number(narrationTotal) > 0 && narrationCompleted != null
                          ? Math.max(0, Math.min(100, Math.round((narrationCompleted / Number(narrationTotal)) * 100 * 10) / 10))
                          : 0
                        const progressTitle =
                          allDone
                            ? (t('videoGenerationComplete') || '✓ Video generation complete!')
                            : isInterrupted
                              ? (t('waitingForConfirmation') || '⏸ Waiting for your confirmation...')
                              : (t('generatingYourVideo') || 'Generating your video...')

                        return (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between mb-3">
                              <p className="text-sm font-medium text-foreground">
                                {progressTitle}
                              </p>
                              {!allDone && effectiveIsGenerating && !isInterrupted && onCancelGeneration && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={onCancelGeneration}
                                  className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                >
                                  <X className="w-3.5 h-3.5 mr-1" />
                                  {t('cancel') || 'Cancel'}
                                </Button>
                              )}
                            </div>

                            {steps.map((step, idx) => {
                              const isCompleted = step.done
                              const isActive = idx === activeIdx && !isCompleted && effectiveIsGenerating && !isCancelled && !isFailed
                              const isCancelledOrFailed = (isCancelled || isFailed) && idx === activeIdx && !isCompleted
                              const isPending = !isCompleted && !isActive && !isCancelledOrFailed
                              // ✅ 只在收到对应 progress event（todo 里有 total > 0）且该步骤为当前 active 步时才展示 bar
                              //   （shots 的 total 会在 per_shot routing 阶段被提前 seed，需用 idx===activeIdx 防止「分镜」还在跑时镜头就显示 0/N）
                              const showShotsProgress = step.id === 'shots' && idx === activeIdx && shotsTotalNum > 0 && !isCompleted && !isCancelled && !isFailed
                              const showStoryboardsProgress = step.id === 'storyboards' && idx === activeIdx && Number(kfTotal) > 0 && !isCompleted && !isCancelled && !isFailed
                              const showReflectionProgress = step.id === 'storyboards' && idx === activeIdx && Number(reflTotal) > 0 && !isCompleted && !isCancelled && !isFailed
                              const showNarrationProgress = step.id === 'narration' && idx === activeIdx && Number(narrationTotal) > 0 && !isCompleted && !isCancelled && !isFailed
                              const showMusicCountdown = step.id === 'music' && isActive && !isCompleted
                              const keyframePct = Math.max(0, Math.min(100, keyframeProgressPercent))
                              const reflectionPct = Math.max(0, Math.min(100, keyframeReflectionProgressPercent))

                              return (
                                <div key={step.id} className="flex items-center gap-3">
                                  <div
                                    className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center transition-all duration-300 ${
                                      isCompleted
                                        ? 'bg-primary text-primary-foreground'
                                        : isCancelledOrFailed
                                          ? 'bg-destructive/20 border-2 border-destructive'
                                          : isActive
                                            ? 'bg-primary/20 border-2 border-primary'
                                            : 'bg-muted border border-border'
                                    }`}
                                  >
                                    {isCompleted ? (
                                      <CheckCircle2 className="w-3.5 h-3.5" />
                                    ) : isCancelledOrFailed ? (
                                      <X className="w-3.5 h-3.5 text-destructive" />
                                    ) : isActive ? (
                                      <Loader2 className="w-3 h-3 text-primary animate-spin" />
                                    ) : (
                                      <span className="text-[10px] text-muted-foreground">{idx + 1}</span>
                                    )}
                                  </div>

                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between mb-0.5">
                                      <span
                                        className={`text-[10px] font-medium truncate transition-colors ${
                                          isCompleted
                                            ? 'text-primary'
                                            : isActive
                                              ? 'text-foreground'
                                              : 'text-muted-foreground'
                                        }`}
                                      >
                                        {step.name}
                                      </span>
                                      {showShotsProgress && (
                                        <span className="text-[10px] text-muted-foreground ml-2">
                                          {shotsCompletedForBar !== undefined && shotsTotalForBar !== undefined
                                            ? `${shotsCompletedForBar}/${shotsTotalForBar} · ${Math.round(shotsPct)}%`
                                            : `${Math.round(shotsPct)}%`}
                                        </span>
                                      )}
                                      {showReflectionProgress ? (
                                        <span className="text-[10px] text-muted-foreground ml-2">
                                          {`${keyframeReflectionCompleted ?? 0}/${keyframeReflectionTotal} · ${Math.round(reflectionPct)}%`}
                                        </span>
                                      ) : showStoryboardsProgress ? (
                                        <span className="text-[10px] text-muted-foreground ml-2">
                                          {`${keyframeCompleted ?? 0}/${effectiveKeyframeTotal ?? kfTotal} · ${Math.round(keyframePct)}%`}
                                        </span>
                                      ) : showNarrationProgress ? (
                                        <span className="text-[10px] text-muted-foreground ml-2">
                                          {`${narrationCompleted ?? 0}/${narrationTotal} · ${Math.round(narrationPct)}%`}
                                        </span>
                                      ) : null}
                                      {showMusicCountdown && (
                                        <div className="flex items-center gap-1 text-[10px] text-muted-foreground ml-2 flex-shrink-0">
                                          <Clock className="w-3 h-3" />
                                          <span>{formatTime(musicCountdown)}</span>
                                        </div>
                                      )}
                                      {isCompleted && <span className="text-[10px] text-primary ml-2">{t('stepDone')}</span>}
                                      {isPending && !effectiveIsGenerating && !allDone && <span className="text-[10px] text-muted-foreground ml-2">{t('stepPending')}</span>}
                                    </div>

                                    {showShotsProgress && (
                                      <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                        <div
                                          className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                          style={{ width: `${shotsPct}%` }}
                                        />
                                      </div>
                                    )}
                                    {showReflectionProgress ? (
                                      <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                        <div
                                          className="bg-gradient-to-r from-amber-400 via-orange-400 to-amber-500 h-full rounded-full transition-all duration-500 ease-out"
                                          style={{ width: `${reflectionPct}%` }}
                                        />
                                      </div>
                                    ) : showStoryboardsProgress ? (
                                      <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                        <div
                                          className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                          style={{ width: `${keyframePct}%` }}
                                        />
                                      </div>
                                    ) : showNarrationProgress ? (
                                      <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                        <div
                                          className="bg-gradient-to-r from-cyan-400 via-teal-400 to-cyan-500 h-full rounded-full transition-all duration-500 ease-out"
                                          style={{ width: `${narrationPct}%` }}
                                        />
                                      </div>
                                    ) : null}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )
                      })()
                    ) : msg.event_type === 'interaction_post_regenerate' ? (
                      <PostRegenerateMessageBlock
                        msg={msg}
                        conversationId={conversationId ?? null}
                        t={t}
                        onRefresh={onPostRegenerateRefresh}
                        onPostRegenerateKeyframeDiceKeys={onPostRegenerateKeyframeDiceKeys}
                        onPostRegenerateVideoDiceKeys={onPostRegenerateVideoDiceKeys}
                        onPostRegenerateTimelineMergeBusy={onPostRegenerateTimelineMergeBusy}
                        keyframesData={keyframesData}
                        videosData={videosData}
                        charactersData={charactersData}
                      />
                    ) : msg.event_type === 'welcome' ? (
                    // 新建任务时的 Cuti 欢迎语，仅展示文案，不显示 loading
                      <p className="text-sm leading-relaxed font-inter whitespace-pre-wrap">
                        {msg.content}
                      </p>
                    ) : (msg.role === 'user' || msg.role === 'human') ? (
                    // 已发送的用户消息（含无 event_type 的乐观/历史）：display prompt 以文字显示
                      <>
                        <p className="text-sm leading-relaxed font-inter">
                          {getDisplayPromptForUserMessage(msg.content || '')}
                        </p>
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    ) : (
                    // For other event types or placeholder messages
                      <>
                        {msg.event_type ? (
                        // 有 event_type 的消息 - 🌐 使用后端返回的content，不再前端拼接
                          <p className="text-sm leading-relaxed font-inter whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                            {getAssistantBubbleDisplayText(msg)}
                          </p>
                        ) : (
                        // 没有 event_type 的占位消息（如 "Generating..."）
                          <div className="flex items-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <p className="text-sm font-inter">
                              {msg.content || 'Processing...'}
                            </p>
                          </div>
                        )}
                        {msg.timestamp && (
                          <p className="text-[10px] opacity-70 mt-2 font-inter">
                            {new Date(msg.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            })}
                          </p>
                        )}
                      </>
                    )}

                    {/* Display images and audio for user_input messages */}
                    {msg.event_type === 'user_input' && msg.event_data && (
                      <div className="mt-3 space-y-2 overflow-x-hidden">
                        {/* Display images array - now expects objects with url and filename */}
                        {msg.event_data.images && msg.event_data.images.length > 0 && (
                          <div className="flex flex-wrap gap-2 pb-2">
                            {msg.event_data.images.map((image, idx: number) => {
                            // Support both old format (string) and new format (object with url)
                              const imageUrl = typeof image === 'string' ? image : image.url
                              const filename = typeof image === 'object' ? image.filename : undefined
                              return (
                                <div key={idx} className="rounded overflow-hidden border border-white/20 flex-shrink-0">
                                  <img
                                    src={imageUrl}
                                    alt={filename || `User upload ${idx + 1}`}
                                    title={filename}
                                    className="max-w-[200px] h-auto"
                                  />
                                </div>
                              )
                            })}
                          </div>
                        )}
                        {/* Display audio files array - now expects objects with url and filename */}
                        {msg.event_data.audio_files && msg.event_data.audio_files.length > 0 && (
                          <div className="space-y-2 min-w-0">
                            {msg.event_data.audio_files.map((audio, idx: number) => {
                            // Support both old format (string) and new format (object with url)
                              const audioUrl = typeof audio === 'string' ? audio : audio.url
                              const filename = typeof audio === 'object' ? audio.filename : undefined
                              return (
                                <div key={idx}>
                                  {filename && <div className="text-[10px] text-muted-foreground mb-1">{filename}</div>}
                                  <audio controls className="w-full">
                                    <source src={audioUrl} type="audio/mpeg" />
                                  </audio>
                                </div>
                              )
                            })}
                          </div>
                        )}
                        {/* Display video files array - expects objects with url and filename */}
                        {msg.event_data.video_files && msg.event_data.video_files.length > 0 && (
                          <div className="space-y-2 min-w-0">
                            {msg.event_data.video_files.map((video, idx: number) => {
                            // Support both old format (string) and new format (object with url)
                              const videoUrl = typeof video === 'string' ? video : video.url
                              const filename = typeof video === 'object' ? video.filename : undefined
                              return (
                                <div key={idx}>
                                  {filename && <div className="text-[10px] text-muted-foreground mb-1">{filename}</div>}
                                  <VideoWithCleanup controls preload="metadata" className="w-full max-w-[300px] rounded">
                                    <source src={videoUrl} type="video/mp4" />
                                    {t('videoNotSupported')}
                                  </VideoWithCleanup>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  {(msg.role === 'user' || msg.role === 'human') && (
                    <img
                      src={userPromptAvatar}
                      alt="User"
                      className="mt-1 h-10 w-10 rounded-full flex-shrink-0 object-cover"
                    />
                  )}
                </div>
              )
            })}

            {/* ✅ Sticky todo list (keeps visible even when new bubbles arrive)；keyframe/reflection 进度更新时自动滚动到此块以展示进度条 */}
            {todoMessage && (
              <div
                ref={todoStickyRef}
                className={`sticky bottom-0 z-10 pt-4 ${todoCollapsed ? 'cursor-pointer' : ''}`}
                onClick={todoCollapsed ? () =>{  setTodoCollapsed(false) } : undefined}
                role={todoCollapsed ? 'button' : undefined}
                title={todoCollapsed ? 'Expand' : undefined}
              >
                <div className="flex justify-start min-w-0">
                  <div className="max-w-[78%] min-w-0 rounded-3xl rounded-tl-md bg-[var(--chat-bubble-ai)] px-4 py-3 text-[15px] leading-[1.55] text-foreground [box-shadow:var(--chat-shadow-bubble)]">
                    {(() => {
                      // ✅ 图片、音乐、故事、视频直生(video_gen)：显示简化的单一项 todo list（video_gen 对齐 image，不走 workflow 多步条）
                      if (agentType === 'image' || agentType === 'music' || agentType === 'story' || agentType === 'video_gen') {
                        const todoStatus = (todoMessage).event_data?.status
                        const isCancelled = todoStatus === TaskStatus.CANCELLED
                        const isFailed = todoStatus === TaskStatus.FAILED
                        // ⭐ 当前任务仍在 running 时，即使之前轮次有 completion 事件也不算 done
                        const isTaskRunning = todoStatus === 'running' || todoStatus === TaskStatus.RUNNING || todoStatus === TaskStatus.QUEUED
                        const isDone = !isTaskRunning && (agentType === 'image'
                          ? messages.some(m => m.event_type === 'image_agent_generated')
                          : agentType === 'music'
                            ? messages.some(m => m.event_type === 'music_agent_generated')
                            : agentType === 'video_gen'
                              ? messages.some(m => m.event_type === 'video_agent_generated')
                              : messages.some(m => m.event_type === 'story_agent_generated'))

                        const stepName = agentType === 'image'
                          ? (t('imageGenerating') || '图片生成中')
                          : agentType === 'music'
                            ? (t('musicGenerating') || '音乐生成中')
                            : agentType === 'video_gen'
                              ? (t('generatingVideos') || '正在生成视频...')
                              : t('da.composer.storyGenerating')

                        return (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${
                                isDone
                                  ? 'bg-primary text-primary-foreground'
                                  : isCancelled || isFailed
                                    ? 'bg-destructive/20 border-2 border-destructive'
                                    : 'bg-primary/20 border-2 border-primary'
                              }`}>
                                {isDone ? (
                                  <CheckCircle2 className="w-3.5 h-3.5" />
                                ) : isCancelled || isFailed ? (
                                  <X className="w-3.5 h-3.5 text-destructive" />
                                ) : (
                                  <Loader2 className="w-3 h-3 text-primary animate-spin" />
                                )}
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-medium truncate">
                                    {isDone
                                      ? (agentType === 'image'
                                        ? (t('imageGenerated') || '图片生成完成')
                                        : agentType === 'music'
                                          ? (t('musicGenerated') || '音乐生成完成')
                                          : agentType === 'video_gen'
                                            ? (t('generatedVideos') || '已生成视频')
                                            : t('da.composer.storyGenerated'))
                                      : isCancelled
                                        ? (t('generationCancelled') || 'Cancelled')
                                        : isFailed
                                          ? (t('generationFailed') || 'Failed')
                                          : stepName}
                                  </span>
                                  {isSimpleAgentType && !isDone && !isCancelled && !isFailed && effectiveIsGenerating && (
                                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground ml-2 flex-shrink-0">
                                      <Clock className="w-3 h-3" />
                                      <span>{formatTime(imageCountdown)}</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                              {!isDone && effectiveIsGenerating && onCancelGeneration && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={(e) => { e.stopPropagation(); onCancelGeneration() }}
                                  className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                >
                                  <X className="w-3.5 h-3.5 mr-1" />
                                  {t('cancel')}
                                </Button>
                              )}
                            </div>
                          </div>
                        )
                      }

                      // ✅ 视频生成：显示完整的多步骤 todo list
                      const eventTypes = new Set(messages.map(m => m.event_type).filter(Boolean) as string[])

                      const shotsProgressPercent = ((todoMessage).event_data?.progress_percent ??
                          (() => {
                            for (let i = messages.length - 1; i >= 0; i--) {
                              const m = messages[i]
                              if (!m) continue
                              if (m.event_type === 'video_generation_progress') {
                                return m.event_data?.progress_percent ?? 0
                              }
                            }
                            return 0
                          })()) || 0
                      const shotsCompleted = (todoMessage).event_data?.completed
                      const shotsTotal = (todoMessage).event_data?.total
                      const kfApiSticky = keyframeTodoFallbackFromApi(keyframesData)
                      let keyframeCompleted = (todoMessage).event_data?.keyframe_completed
                      let keyframeTotal = (todoMessage).event_data?.keyframe_total
                      if (kfApiSticky && kfApiSticky.total > 0) {
                        keyframeCompleted = kfApiSticky.completed
                        keyframeTotal = kfApiSticky.total
                      }
                      const totalFromScenes = typeof scenesCount === 'number' && Number.isFinite(scenesCount) ? scenesCount : undefined
                      const effectiveShotsTotal = (shotsTotal != null && shotsTotal > 0)
                        ? shotsTotal
                        : totalFromScenes
                      const vidApiStickyTodo = videoTodoFallbackFromApi(videosData, scenesCount)
                      let shotsProgressPercentSticky = shotsProgressPercent
                      let shotsCompletedSticky: number | undefined =
                        shotsCompleted
                      let shotsTotalSticky: number | undefined =
                        effectiveShotsTotal !== undefined && effectiveShotsTotal > 0
                          ? effectiveShotsTotal
                          : undefined
                      if (vidApiStickyTodo && vidApiStickyTodo.total > 0) {
                        shotsCompletedSticky = vidApiStickyTodo.completed
                        shotsTotalSticky = vidApiStickyTodo.total
                        shotsProgressPercentSticky =
                          Math.round((vidApiStickyTodo.completed / vidApiStickyTodo.total) * 100 * 10) / 10
                      }

                      const keyframeProgressPercent = (keyframeTotal != null && keyframeTotal > 0 && keyframeCompleted != null
                        ? Math.round((keyframeCompleted / keyframeTotal) * 100 * 10) / 10
                        : (todoMessage).event_data?.keyframe_progress_percent ??
                            (() => {
                              for (let i = messages.length - 1; i >= 0; i--) {
                                const m = messages[i]
                                if (!m) continue
                                if (m.event_type === 'keyframe_generation_progress' && m.event_data) {
                                  const c = m.event_data.completed
                                  const t = m.event_data.total
                                  return typeof t === 'number' && typeof c === 'number' && t > 0 ? Math.round((c / t) * 100) : 0
                                }
                              }
                              return 0
                            })()) || 0
                      const todoStatus = (todoMessage).event_data?.status // "cancelled" | "failed" | "interrupted" | undefined
                      const isCancelled = todoStatus === 'cancelled'
                      const isFailed = todoStatus === 'failed'
                      const isInterrupted = todoStatus === 'interrupted'

                      // ✅ 支持从后端恢复的 completed_steps
                      const completedSteps = new Set<string>((todoMessage).event_data?.completed_steps || [])
                      const hasAnyOrCompleted = completionPredicate(eventTypes, completedSteps)

                      const reflCompleted = (todoMessage).event_data?.keyframe_reflection_completed ?? 0
                      const reflTotal = (todoMessage).event_data?.keyframe_reflection_total
                      // ✅ 关键帧反思进行中时「分镜」不算 done，这样 active 和百分比都显示在分镜下而非镜头下
                      const storyboardsActuallyDoneCollapsed =
                        hasAnyOrCompleted(['keyframes_generated']) &&
                        !(Number(reflTotal) > 0 && reflCompleted < Number(reflTotal))

                      const wfMsgCollapsed = pickWorkflowStateMessageForTodo(messages, currentRunId)
                      const wfSrcCollapsed = wfMsgCollapsed ? (wfMsgCollapsed.event_data ?? wfMsgCollapsed) : null
                      const pathEntriesCollapsed =
                        wfSrcCollapsed && Array.isArray(wfSrcCollapsed.path) && wfSrcCollapsed.path.length > 0
                          ? wfSrcCollapsed.path
                          : null
                      const steps = buildVideoTodoStepsFromPath(
                        pathEntriesCollapsed,
                        t,
                        hasAnyOrCompleted,
                        storyboardsActuallyDoneCollapsed,
                        musicData,
                      )

                      const firstNotDone = steps.findIndex(s => !s.done)
                      const activeIdx = effectiveIsGenerating && !isCancelled && !isFailed && !isInterrupted
                        ? (firstNotDone === -1 ? steps.length - 1 : firstNotDone)
                        : -1
                      const allDone = steps.every(s => s.done)
                      const activeStep = activeIdx >= 0 ? steps[activeIdx] : null
                      const collapsedPct = Math.max(0, Math.min(100, shotsProgressPercentSticky))
                      const collapsedKeyframePct = Math.max(0, Math.min(100, keyframeProgressPercent))
                      const collapsedReflectionPct = Math.max(0, Math.min(100,
                        (todoMessage).event_data?.keyframe_reflection_progress_percent ??
                        (Number(reflTotal) > 0 ? Math.round((reflCompleted / Number(reflTotal)) * 100) : 0),
                      ))
                      const shotsCompletedCollapsed = shotsCompletedSticky ?? 0
                      const shotsTotalCollapsed = shotsTotalSticky
                      // ✅ 只在收到对应 progress event（todo 里有 total > 0）时才展示 bar
                      const hasKeyframeProgress = Number(keyframeTotal) > 0
                      const hasReflectionProgress = Number(reflTotal) > 0
                      const hasShotsProgress = Number(shotsTotalCollapsed) > 0
                      // 折叠态进度须与 activeStep 对齐，避免 label 显示「分镜」却展示 shots 的数字
                      const showCollapsedShotsProgress = activeStep?.id === 'shots' && hasShotsProgress && !isCancelled && !isFailed && !isInterrupted
                      const showCollapsedStoryboardsProgress = activeStep?.id === 'storyboards' && (hasKeyframeProgress || hasReflectionProgress) && !isCancelled && !isFailed && !isInterrupted
                      const collapsedProgressTitle = allDone
                        ? (t('videoGenerationComplete') || '✓ Video generation complete!')
                        : isCancelled
                          ? (t('generationCancelled') || 'Cancelled')
                          : isFailed
                            ? (t('generationFailed') || 'Failed')
                            : isInterrupted
                              ? (t('waitingForConfirmation') || '⏸ Waiting for your confirmation...')
                              : (t('generatingYourVideo') || 'Generating your video...')

                      // ✅ 计算总剩余时间（参考 instant 页面的智能算法）
                      const videoDuration = duration[0] || 30
                      const initialEstimatedTime = calculateTotalEstimatedTime(videoDuration)

                      // 计算整体进度百分比（基于已完成的步骤）
                      const completedStepsCount = steps.filter(s => s.done).length
                      const totalStepsCount = steps.length
                      const overallProgress = allDone ? 100 : Math.round((completedStepsCount / totalStepsCount) * 100)

                      // ✅ 智能计算总剩余时间（确保每秒动态减少）
                      const calculateTotalRemainingTime = (): number => {
                        if (allDone || isCancelled || isFailed || isInterrupted) {
                          lastRemainingRef.current = 0
                          return 0
                        }

                        const baseEstimate = initialEstimatedTime

                        // 没有进度时，基于已用时间直接计算
                        if (overallProgress === 0) {
                          const remaining = Math.max(0, baseEstimate - elapsedTime)
                          lastRemainingRef.current = remaining
                          lastProgressRef.current = 0
                          lastElapsedTimeRef.current = elapsedTime
                          return remaining
                        }

                        // 检查进度是否更新了
                        const progressChanged = overallProgress !== lastProgressRef.current

                        let remaining: number

                        if (progressChanged) {
                          // ✅ 进度更新了，重新计算剩余时间
                          if (overallProgress < 30) {
                            // 前期（0-30%）：基于初始估算线性递减，但要考虑已用时间
                            const progressBasedRemaining = Math.max(0, Math.round(baseEstimate * (1 - overallProgress / 100)))
                            const elapsedBasedRemaining = Math.max(0, baseEstimate - elapsedTime)
                            // 取两者中较小的，确保不会超过初始估算
                            remaining = Math.min(progressBasedRemaining, elapsedBasedRemaining)
                          } else if (elapsedTime > 0) {
                            // 后期（30-100%）：基于实际进度推算
                            const projectedTotal = elapsedTime / (overallProgress / 100)
                            remaining = Math.max(0, Math.round(projectedTotal - elapsedTime))
                          } else {
                            remaining = Math.max(0, baseEstimate - elapsedTime)
                          }

                          // 确保新计算的剩余时间不大于上一次的（单调递减）
                          if (lastRemainingRef.current !== null) {
                            remaining = Math.min(remaining, lastRemainingRef.current)
                          }

                          lastProgressRef.current = overallProgress
                          lastRemainingRef.current = remaining
                          lastElapsedTimeRef.current = elapsedTime
                          return remaining
                        } else {
                          // ⏱️ 进度未更新：保证倒计时持续递减（即使进度事件不更新）
                          const elapsedDelta = Math.max(0, elapsedTime - lastElapsedTimeRef.current)
                          if (overallProgress < 30) {
                            // 前期：基于初始估算减去已用时间（实时计算）
                            remaining = Math.max(0, baseEstimate - elapsedTime)
                          } else if (elapsedTime > 0) {
                            // 后期：基于实际进度和已用时间实时推算
                            const projectedTotal = elapsedTime / (overallProgress / 100)
                            remaining = Math.max(0, Math.round(projectedTotal - elapsedTime))
                          } else {
                            remaining = Math.max(0, baseEstimate - elapsedTime)
                          }

                          // 允许“跳跃式下降”（新推算值更小时采用它）
                          // 否则按 elapsedDelta 每秒递减，避免卡住不动
                          if (lastRemainingRef.current !== null) {
                            const tickDown = Math.max(0, lastRemainingRef.current - elapsedDelta)
                            remaining = Math.max(0, Math.min(remaining, tickDown))
                          }

                          lastRemainingRef.current = remaining
                          lastElapsedTimeRef.current = elapsedTime
                          return remaining
                        }
                      }

                      // ✅ 计算总剩余时间（elapsedTime 的更新会触发重新渲染，从而更新倒计时）
                      const totalRemainingTime = calculateTotalRemainingTime()

                      return (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2 min-w-0">
                              <p className="text-sm font-medium text-foreground truncate">
                                {collapsedProgressTitle}
                              </p>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); setTodoCollapsed(v => !v) }}
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                                title={todoCollapsed ? 'Expand' : 'Collapse'}
                              >
                                <ChevronDown className={`w-4 h-4 transition-transform ${todoCollapsed ? '' : 'rotate-180'}`} />
                              </Button>
                            </div>
                            {!allDone && effectiveIsGenerating && !isInterrupted && onCancelGeneration && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); onCancelGeneration() }}
                                className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                              >
                                <X className="w-3.5 h-3.5 mr-1" />
                                {t('cancel') || 'Cancel'}
                              </Button>
                            )}
                          </div>

                          {todoCollapsed ? (
                            <div className="space-y-2">
                              <div className="flex items-center gap-2">
                                <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${
                                  allDone
                                    ? 'bg-primary text-primary-foreground'
                                    : isCancelled || isFailed
                                      ? 'bg-destructive/20 border-2 border-destructive'
                                      : 'bg-primary/20 border-2 border-primary'
                                }`}>
                                  {allDone ? (
                                    <CheckCircle2 className="w-3.5 h-3.5" />
                                  ) : isCancelled || isFailed ? (
                                    <X className="w-3.5 h-3.5 text-destructive" />
                                  ) : (
                                    <Loader2 className="w-3 h-3 text-primary animate-spin" />
                                  )}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center justify-between">
                                    <span className="text-xs font-medium truncate">
                                      {allDone
                                        ? (t('videoComplete') || 'Complete')
                                        : isCancelled
                                          ? (t('generationCancelled') || 'Cancelled')
                                          : isFailed
                                            ? (t('generationFailed') || 'Failed')
                                            : (activeStep?.name || 'In progress')}
                                    </span>
                                    <div className="flex items-center gap-2">
                                      {!allDone && !isCancelled && !isFailed && effectiveIsGenerating && activeStep?.id === 'music' && (
                                        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                                          <Clock className="w-3 h-3" />
                                          <span>{formatTime(musicCountdown)}</span>
                                        </div>
                                      )}
                                      {!allDone && !isCancelled && !isFailed && effectiveIsGenerating && activeStep?.id !== 'music' && (totalRemainingTime > 0 || Number(activeStep?.est_seconds) > 0) && (
                                        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                                          <Clock className="w-3 h-3" />
                                          {/* 总剩余时间>0 时显示总剩余；被估算耗尽(=0)时回退显示当前步骤预估 ~Xs，避免折叠态无时间 */}
                                          <span>{totalRemainingTime > 0 ? formatTime(totalRemainingTime) : `~${formatTime(Number(activeStep?.est_seconds))}`}</span>
                                        </div>
                                      )}
                                      {!allDone && !isCancelled && !isFailed && showCollapsedShotsProgress && (
                                        <span className="text-[10px] text-muted-foreground">
                                          {`${shotsCompletedCollapsed}/${shotsTotalCollapsed} · ${Math.round(collapsedPct)}%`}
                                        </span>
                                      )}
                                      {!allDone && !isCancelled && !isFailed && showCollapsedStoryboardsProgress && (
                                        <span className="text-[10px] text-muted-foreground">
                                          {hasReflectionProgress
                                            ? `${reflCompleted}/${reflTotal} · ${Math.round(collapsedReflectionPct)}%`
                                            : `${keyframeCompleted ?? 0}/${keyframeTotal} · ${Math.round(collapsedKeyframePct)}%`}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  {!allDone && !isCancelled && !isFailed && showCollapsedShotsProgress && (
                                    <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden mt-2">
                                      <div
                                        className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                        style={{ width: `${collapsedPct}%` }}
                                      />
                                    </div>
                                  )}
                                  {!allDone && !isCancelled && !isFailed && showCollapsedStoryboardsProgress && (
                                    <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden mt-2">
                                      <div
                                        className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                        style={{ width: `${hasReflectionProgress ? collapsedReflectionPct : collapsedKeyframePct}%` }}
                                      />
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>
                          ) : (
                            <>
                              {steps.map((step, idx) => {
                                const isCompleted = step.done
                                const isActive = idx === activeIdx && !isCompleted && effectiveIsGenerating && !isCancelled && !isFailed
                                const isCancelledOrFailed = (isCancelled || isFailed) && idx === activeIdx && !isCompleted
                                // ✅ 只在收到对应 progress event（todo 里有 total > 0）且该步骤为当前 active 步时才展示 bar
                                //   （shots 的 total 会在 per_shot routing 阶段被提前 seed，需用 idx===activeIdx 防止「分镜」还在跑时镜头就显示 0/N）
                                const stepShowShotsProgress = step.id === 'shots' && idx === activeIdx && hasShotsProgress && !isCompleted && !isCancelled && !isFailed
                                const stepShowStoryboardsProgress = step.id === 'storyboards' && idx === activeIdx && hasKeyframeProgress && !hasReflectionProgress && !isCompleted && !isCancelled && !isFailed
                                const stepShowReflectionProgress = step.id === 'storyboards' && idx === activeIdx && hasReflectionProgress && !isCompleted && !isCancelled && !isFailed
                                const stepShowMusicCountdown = step.id === 'music' && isActive && !isCompleted
                                const shotsPct = Math.max(0, Math.min(100, collapsedPct))
                                const kfPct = Math.max(0, Math.min(100, collapsedKeyframePct))
                                const reflPct = Math.max(0, Math.min(100, collapsedReflectionPct))

                                return (
                                  <div key={step.id} className="flex items-center gap-3">
                                    <div
                                      className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center transition-all duration-300 ${
                                        isCompleted
                                          ? 'bg-primary text-primary-foreground'
                                          : isCancelledOrFailed
                                            ? 'bg-destructive/20 border-2 border-destructive'
                                            : isActive
                                              ? 'bg-primary/20 border-2 border-primary'
                                              : 'bg-muted border border-border'
                                      }`}
                                    >
                                      {isCompleted ? (
                                        <CheckCircle2 className="w-3.5 h-3.5" />
                                      ) : isCancelledOrFailed ? (
                                        <X className="w-3.5 h-3.5 text-destructive" />
                                      ) : isActive ? (
                                        <Loader2 className="w-3 h-3 text-primary animate-spin" />
                                      ) : (
                                        <span className="text-[10px] text-muted-foreground">{idx + 1}</span>
                                      )}
                                    </div>

                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center justify-between mb-0.5">
                                        <span
                                          className={`text-[10px] font-medium truncate transition-colors ${
                                            isCompleted
                                              ? 'text-primary'
                                              : isActive
                                                ? 'text-foreground'
                                                : 'text-muted-foreground'
                                          }`}
                                        >
                                          {step.name}
                                        </span>
                                        <div className="flex items-center gap-2">
                                          {stepShowShotsProgress && (
                                            <span className="text-[10px] text-muted-foreground">
                                              {`${shotsCompletedCollapsed}/${shotsTotalCollapsed} · ${Math.round(shotsPct)}%`}
                                            </span>
                                          )}
                                          {stepShowStoryboardsProgress && (
                                            <span className="text-[10px] text-muted-foreground">
                                              {`${keyframeCompleted ?? 0}/${keyframeTotal} · ${Math.round(kfPct)}%`}
                                            </span>
                                          )}
                                          {stepShowReflectionProgress && (
                                            <span className="text-[10px] text-muted-foreground">
                                              {`${reflCompleted}/${reflTotal} · ${Math.round(reflPct)}%`}
                                            </span>
                                          )}
                                          {stepShowMusicCountdown && (
                                            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                                              <Clock className="w-3 h-3" />
                                              <span>{formatTime(musicCountdown)}</span>
                                            </div>
                                          )}
                                          {!isCompleted && !isCancelledOrFailed && typeof step.est_seconds === 'number' && step.est_seconds > 0 &&
                                            !stepShowShotsProgress && !stepShowStoryboardsProgress &&
                                            !stepShowReflectionProgress && !stepShowMusicCountdown && (
                                            <span className="text-[10px] text-muted-foreground/70">~{formatTime(step.est_seconds)}</span>
                                          )}
                                          {isCompleted && <span className="text-[10px] text-primary ml-2">{t('stepDone')}</span>}
                                        </div>
                                      </div>

                                      {stepShowShotsProgress && (
                                        <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                          <div
                                            className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                            style={{ width: `${shotsPct}%` }}
                                          />
                                        </div>
                                      )}
                                      {stepShowStoryboardsProgress && (
                                        <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                          <div
                                            className="bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500 h-full rounded-full transition-all duration-500 ease-out"
                                            style={{ width: `${kfPct}%` }}
                                          />
                                        </div>
                                      )}
                                      {stepShowReflectionProgress && (
                                        <div className="w-full bg-white/10 rounded-full h-1 overflow-hidden">
                                          <div
                                            className="bg-gradient-to-r from-amber-400 via-orange-400 to-amber-500 h-full rounded-full transition-all duration-500 ease-out"
                                            style={{ width: `${reflPct}%` }}
                                          />
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                )
                              })}

                              {/* ✅ 总剩余时间显示（在所有步骤下方） */}
                              {!allDone && !isCancelled && !isFailed && effectiveIsGenerating && totalRemainingTime > 0 && (
                                <div className="flex items-center justify-center gap-2 pt-2 mt-2 border-t border-white/10">
                                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <Clock className="w-3.5 h-3.5" />
                                    <span className="font-medium">
                                      {t('estimatedTimeRemaining') || 'Estimated time remaining'}: {formatTime(totalRemainingTime)}
                                    </span>
                                  </div>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )
                    })()}
                  </div>
                </div>
              </div>
            )}
            {shouldShowAssistantThinking && (
              <div className="flex justify-start min-w-0 items-start gap-2">
                <button
                  type="button"
                  onClick={() =>{  setShowCutiAvatarLightbox(true) }}
                  className="mt-1 flex-shrink-0 rounded-full focus:outline-none focus:ring-2 focus:ring-primary/50"
                  title={t('da.composer.viewAvatar')}
                >
                  <img
                    src={aiAvatar}
                    alt="AI"
                    className="h-10 w-10 rounded-full object-cover"
                  />
                </button>
                <div className="max-w-[78%] min-w-0 rounded-3xl rounded-tl-md bg-[var(--chat-bubble-ai)] px-4 py-3 text-[15px] leading-[1.55] overflow-hidden [overflow-wrap:anywhere] [box-shadow:var(--chat-shadow-bubble)]">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <p className="text-sm font-inter">
                      {assistantThinkingText}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <MessageSquare className="w-12 h-12 mx-auto mb-4 text-muted-foreground/50" />
              <p className="text-muted-foreground">
                {t('da.composer.emptyHint')}
              </p>
            </div>
          </div>
        )}
      </ScrollArea>

      {/* Message Input - 霓虹渐变边框 + 深灰内背景（参考图样式）；手机端收紧与消息区的间距 */}
      <div
        className={`${isInputDisabled && !effectiveIsGenerating ? 'p-0' : 'mx-auto w-full max-w-[760px] px-3 pb-4 pt-1'} sticky bottom-0 z-20 shrink-0 overflow-x-hidden relative transition-all duration-200 bg-gradient-to-t from-background via-background to-background/0 ${
          isDragOver ? 'border-primary/50 bg-primary/5' : ''
        }`}
        onDragOver={isInputDisabled && !effectiveIsGenerating ? undefined : dragDropHandler.handleDragOver}
        onDragLeave={isInputDisabled && !effectiveIsGenerating ? undefined : dragDropHandler.handleDragLeave}
        onDrop={isInputDisabled && !effectiveIsGenerating ? undefined : dragDropHandler.handleDrop}
      >
        {/* 仅当禁止输入（如未选任务/需新建）时显示占位输入框；生成中保持可输入，右侧显示取消 */}
        {isInputDisabled && !effectiveIsGenerating ? (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="w-full">
                  <Textarea
                    ref={textareaRef}
                    placeholder=""
                    value=""
                    disabled={true}
                    className="w-full glass border-primary/30 font-inter resize-none overflow-hidden !min-h-[40px] max-h-[200px] py-2.5 text-xs leading-tight opacity-50 cursor-not-allowed bg-muted/30"
                    style={{ height: '40px' }}
                    rows={1}
                  />
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="z-[120] max-w-[var(--radix-tooltip-content-available-width)] whitespace-normal break-words">
                <p className="text-[10px] leading-snug">{t('chattingComingSoon')}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <>
            {suggestionsEverReceived && effectiveActionSuggestions.length > 0 && !effectiveIsGenerating && (
              <div className="px-1 pb-2">
                {showClickDirectGenerateHint && (
                  <div
                    role="status"
                    className="mb-2 rounded-lg border border-primary/35 bg-primary/8 px-3 py-2 text-[13px] leading-snug text-foreground"
                  >
                    {t('clickDirectGenerateHint')}
                  </div>
                )}
                <div className="px-1 pb-1.5 text-[12px] font-semibold font-medium text-foreground/50">
                  {t('actionSuggestionsTitle')}
                </div>
                <div className="overflow-hidden rounded-xl border border-[var(--chat-chip-border)] bg-[var(--chat-chip)]/40">
                  {effectiveActionSuggestions.map((item, i) => {
                    const isGenerate = Boolean(item.is_direct_generate)
                    const Icon = isGenerate ? Sparkles : MessageCircle
                    return (
                      <button
                        key={`${item.label}-${i}`}
                        type="button"
                        onClick={() =>{  handleActionSuggestionButtonClick(item) }}
                        disabled={isInputDisabled}
                        className={`group flex w-full items-center gap-3 px-4 text-left transition disabled:opacity-50 py-3 text-[13px] hover:bg-white dark:hover:bg-white/10 ${
                          i > 0 ? 'border-t border-[var(--chat-chip-border)]' : ''
                        }`}
                      >
                        <Icon
                          className={`h-4 w-4 shrink-0 ${
                            isGenerate
                              ? 'text-[var(--chat-brand-from)]'
                              : 'text-foreground/40'
                          }`}
                        />
                        <span
                          className={`flex-1 truncate ${
                            isGenerate
                              ? 'font-medium text-foreground'
                              : 'text-foreground/80'
                          }`}
                        >
                          {isGenerate ? t('directGenerateAction') : item.label}
                        </span>
                        <ArrowRight className="h-4 w-4 shrink-0 transition group-hover:translate-x-0.5 text-foreground/30 group-hover:text-foreground/60" />
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            {/* 提示词引导按钮：Create 页用 PROMPT_MAPPINGS_FOR_CREATE_PAGE（不含首页 demo），只显示功能名称。有 hint 的项点击后只填入 display 并显示小字提示；无 hint 可点击即发送 */}
            {showActionSuggestions && !suppressActionSuggestionsUI && agentSuggestionsEverReceived &&
              latestActionSuggestions.length === 0 && !streamedSuggestions && PROMPT_MAPPINGS_FOR_CREATE_PAGE.length > 0 && (
              <div className="flex flex-wrap gap-2 px-1 pb-2">
                {PROMPT_MAPPINGS_FOR_CREATE_PAGE.map((m, i) => (
                  <Button
                    key={i}
                    variant="outline"
                    size="sm"
                    type="button"
                    onClick={() => {
                      if (m.hint || m.fillOnly) {
                        onMessageChange(m.display)
                      } else if (onSendWithPrompt) {
                        onSendWithPrompt(m.display)
                      } else {
                        onMessageChange(m.display)
                      }
                    }}
                    disabled={isInputDisabled}
                    className="h-auto rounded-full border border-[var(--chat-chip-border)] bg-[var(--chat-chip)] px-4 py-2 text-[13px] font-medium text-foreground/80 transition hover:bg-white dark:hover:bg-white/10"
                    title={m.display}
                  >
                    {m.name}
                  </Button>
                ))}
              </div>
            )}
            <div className="relative">
              {/* 拖拽上传提示覆盖层 */}
              {isDragOver && (
                <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[28px] border-2 border-dashed border-primary/50 bg-primary/10">
                  <div className="text-center">
                    <Upload className="w-8 h-8 text-primary mx-auto mb-2" />
                    <p className="text-xs font-medium text-primary">
                      {t('dropFilesHere')}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {t('supportedFormats')}
                    </p>
                  </div>
                </div>
              )}
              {/* ChatGPT 式输入框：固定 28px 圆角矩形（不要 stadium），正文在上、工具栏在下 */}
              <div
                ref={pillWrapperRef}
                className="relative flex rounded-[28px] bg-white p-3 dark:bg-neutral-900 [box-shadow:0_0_0_1.5px_var(--chat-brand-from),0_8px_24px_oklch(0_0_0_/0.06)]"
                onMouseMove={(e) => {
                  const wrapper = pillWrapperRef.current
                  const spot = spotlightRef.current
                  if (!wrapper || !spot) return
                  const rect = wrapper.getBoundingClientRect()
                  const x = e.clientX - rect.left
                  const y = e.clientY - rect.top
                  spot.style.background = SPOTLIGHT_GRADIENT(x, y)
                }}
                onMouseLeave={() => {
                  const spot = spotlightRef.current
                  if (spot) spot.style.background = 'none'
                }}
              >
                <div ref={spotlightRef} className="pointer-events-none absolute inset-0 overflow-hidden rounded-[28px]" aria-hidden />
                <div className="relative z-[1] flex min-h-0 min-w-0 w-full flex-1 flex-col gap-1 bg-transparent">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".jpg,.jpeg,.png,.webp,.wav,.mp3,.aiff,.aac,.ogg,.flac,.mp4,.mpeg,.mov,.avi,.flv,.mpg,.webm,.wmv,.3gpp,audio/mpeg,audio/wav,audio/aiff,audio/aac,audio/ogg,audio/flac,image/png,image/jpeg,image/webp,video/mp4,video/mpeg,video/quicktime,video/avi,video/x-msvideo,video/x-flv,video/mpg,video/webm,video/wmv,video/3gpp"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  {/* 正文区：可增高、框内滚动，避免圆角把首尾行切掉 */}
                  <div className={`relative flex min-h-0 w-full min-w-0 flex-1 items-start ${isInputDisabled ? 'cursor-not-allowed' : ''}`}>
                    {(() => {
                      const trimmedMessage = (message || '').trim()
                      const isMappedDisplayPrompt = PROMPT_MAPPINGS.some(m => m.display.trim() === trimmedMessage)
                      if (isMappedDisplayPrompt && !isInputDisabled) {
                        return (
                          <div className="flex items-center gap-2 w-full min-h-[40px] max-sm:min-h-[21px] py-2 max-sm:py-0.5">
                            <Badge
                              variant="outline"
                              className="text-xs max-sm:text-[11px] leading-tight font-inter font-normal px-3 py-1.5 max-sm:py-0.5 cursor-default select-none shrink-0"
                            >
                              {getDisplayPromptForUserMessage(trimmedMessage)}
                            </Badge>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0 rounded-full shrink-0 text-muted-foreground hover:text-foreground"
                              onClick={() =>{  onMessageChange('') }}
                              title={t('clear') || '清除'}
                            >
                              <X className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        )
                      }
                      return (
                        <>
                          <Textarea
                            ref={textareaRef}
                            placeholder={isInputDisabled ? t('pleaseCreateNewTaskToSend') : t('typeMessage')}
                            value={message}
                            onChange={(e) => {
                              if (!isInputDisabled) {
                                onMessageChange(e.target.value)
                              }
                            }}
                            onKeyDown={(e) => {
                              if (isInputDisabled) {
                                e.preventDefault()
                                if (!effectiveIsGenerating) {
                                  toast.info(t('pleaseCreateNewTaskToSend'), { duration: 5000 })
                                }
                                return
                              }
                              const isComposing = e.nativeEvent.isComposing || composingRef.current
                              if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
                                e.preventDefault()
                                onSendMessage()
                              }
                            }}
                            onCompositionStart={() => {
                              composingRef.current = true
                            }}
                            onCompositionEnd={() => {
                              composingRef.current = false
                            }}
                            onPaste={(e) => {
                              if (isInputDisabled || !onFileUpload) return
                              const clipboardData = e.clipboardData

                              const rawFiles: File[] = []
                              for (let i = 0; i < clipboardData.items.length; i++) {
                                const item = clipboardData.items[i]
                                if (!item) continue
                                if (item.kind !== 'file') continue
                                const file = item.getAsFile()
                                if (file) rawFiles.push(normalizeClipboardFile(file))
                              }
                              if (rawFiles.length === 0) return
                              e.preventDefault()

                              const { validFiles } = validateFiles(rawFiles, uploadedFiles, t)
                              if (validFiles.length > 0) {
                                onFileUpload(validFiles)
                                toast.success(
                                  validFiles.length === 1
                                    ? t('pastedImage')
                                    : t('pastedImages').replace('{count}', displayValue(validFiles.length)),
                                )
                              }
                            }}
                            className={`block w-full resize-none overflow-y-auto border-0 bg-transparent px-1 py-0.5 font-inter text-[15px] leading-6 text-foreground shadow-none placeholder:text-foreground/40 focus-visible:ring-0 focus-visible:ring-offset-0 min-h-[24px] !min-h-[24px] max-h-[240px] ${
                              isInputDisabled ? 'opacity-50 cursor-not-allowed' : ''
                            }`}
                            disabled={isInputDisabled}
                            rows={1}
                          />
                          {isInputDisabled && !effectiveIsGenerating && (
                            <div
                              className="absolute inset-0 z-10 cursor-not-allowed"
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                toast.info(t('pleaseCreateNewTaskToSend'), { duration: 5000 })
                              }}
                              onMouseDown={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                              }}
                            />
                          )}
                        </>
                      )
                    })()}
                  </div>
                  {/* 底栏：左侧附件/选项，右侧发送，与 ChatGPT composer 一致 */}
                  <div className="flex w-full shrink-0 items-center gap-1 pt-1">
                    <TooltipProvider delayDuration={150}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={effectiveIsGenerating}
                            className="h-9 w-9 max-sm:h-[28px] max-sm:w-[28px] p-0 rounded-full text-foreground/60 hover:bg-black/5 dark:hover:bg-white/10 flex-shrink-0"
                          >
                            <Plus className="w-4 h-4 max-sm:w-3 max-sm:h-3" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top" sideOffset={6}>
                          {t('uploadFiles')}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <Popover>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <PopoverTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-9 w-9 max-sm:h-[28px] max-sm:w-[28px] p-0 rounded-full text-foreground/60 hover:bg-black/5 dark:hover:bg-white/10 flex-shrink-0"
                              disabled={effectiveIsGenerating}
                            >
                              <svg className="w-4 h-4 max-sm:w-3 max-sm:h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><circle cx="5" cy="7" r="2" fill="currentColor" stroke="none" /><line x1="10" y1="7" x2="20" y2="7" /><circle cx="19" cy="17" r="2" fill="currentColor" stroke="none" /><line x1="4" y1="17" x2="14" y2="17" /></svg>
                            </Button>
                          </PopoverTrigger>
                        </TooltipTrigger>
                        <TooltipContent side="top" sideOffset={6}>
                          {t('options')}
                        </TooltipContent>
                      </Tooltip>
                      <PopoverContent className="w-[min(20rem,92vw)] bg-popover/95 backdrop-blur-xl border border-border shadow-lg dark:bg-[#121212]/95 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.06)] p-4 z-[100] rounded-xl text-foreground dark:text-gray-300" align="start" side="top" sideOffset={8} collisionPadding={16}>
                        <VideoOptionsPanel
                          duration={duration}
                          onDurationChange={v => onDurationChange?.(v)}
                          resolution={resolution}
                          onResolutionChange={r => onResolutionChange?.(r)}
                          aspectRatio={aspectRatio}
                          onAspectRatioChange={a => onAspectRatioChange?.(a)}
                          lipsyncCoverage={lipsyncCoverage}
                          onLipsyncCoverageChange={v => onLipsyncCoverageChange?.(v)}
                          isAutoModel={selectedModel === 'Auto'}
                          onAutoModelChange={v => onModelChange?.(v ? 'Auto' : 'Seedance 1.0 Pro Fast')}
                          imageGenerationTool={imageGenerationTool}
                          onImageGenerationToolChange={v => onImageGenerationToolChange?.(v)}
                          videoModel={selectedModel === 'Auto' ? 'seedance_1_0_pro_fast' : (VIDEO_MODEL_LABEL_TO_VALUE[selectedModel] ?? 'seedance_1_0_pro_fast')}
                          onVideoModelChange={value => onModelChange?.(VIDEO_MODEL_VALUE_TO_LABEL[value] ?? 'Seedance 1.0 Pro Fast')}
                          lipsyncVideoModel={lipsyncVideoModel}
                          onLipsyncVideoModelChange={v => onLipsyncVideoModelChange?.(v)}
                          enableContinuityMode={enableContinuityMode}
                          onEnableContinuityModeChange={v => onEnableContinuityModeChange?.(v)}
                          enableKeyframeReflection={enableKeyframeReflection}
                          onEnableKeyframeReflectionChange={v => onEnableKeyframeReflectionChange?.(v)}
                          isGenerating={effectiveIsGenerating}
                          showRunMode={onAutoContinueOnInterruptChange != null}
                          autoContinueOnInterrupt={autoContinueOnInterrupt}
                          onAutoContinueOnInterruptChange={onAutoContinueOnInterruptChange}
                          onSoraSelect={(model) => {
                            setPendingSoraModel(model)
                            setShowSoraDialog(true)
                          }}
                        />
                      </PopoverContent>
                    </Popover>
                    <div className="ml-auto flex items-center">
                      {shouldShowCancelButton ? (
                        <Button
                          variant="destructive"
                          onClick={onCancelGeneration}
                          aria-label={t('cancel')}
                          className="h-11 w-11 max-sm:h-9 max-sm:w-9 rounded-full p-0 flex-shrink-0 bg-red-500/20 hover:bg-red-500/30 border border-red-500/50"
                          title={t('cancel')}
                        >
                          <Square className="w-4 h-4 max-sm:w-3 max-sm:h-3" fill="currentColor" />
                        </Button>
                      ) : (
                        <div className="group relative z-10 inline-flex">
                          <Button
                            onClick={() =>{  onSendMessage() }}
                            disabled={(!message.trim() && uploadedFiles.length === 0) || isInputDisabled || effectiveIsGenerating}
                            className="h-11 w-11 max-sm:h-9 max-sm:w-9 rounded-full p-0 flex-shrink-0 text-white disabled:opacity-50 disabled:cursor-not-allowed bg-[image:var(--chat-gradient-brand)] transition active:scale-95"
                          >
                            {effectiveIsGenerating ? (
                              <Loader2 className="w-4 h-4 max-sm:w-3 max-sm:h-3 text-white animate-spin" />
                            ) : (
                              <Send className="w-4 h-4 max-sm:w-3 max-sm:h-3 text-white transition-transform duration-150 group-hover:rotate-[-10deg]" />
                            )}
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            {/* 当输入框内容命中带 hint 的映射时，显示小字提示（如：请上传头像） */}
            {(() => {
              const trimmed = (message || '').trim()
              const withHint = PROMPT_MAPPINGS.find(m => m.hint && m.display.trim() === trimmed)
              return withHint?.hint ? (
                <p className="text-[11px] text-muted-foreground mt-2 px-1">
                  {withHint.hint}
                </p>
              ) : null
            })()}
          </>
        )}
        {/* Uploaded Files Display - 放在 pill 下方，与 0211 一致 */}
        {uploadedFiles.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 overflow-x-hidden pb-2">
            {uploadedFiles.map((file, index) => (
              <FilePreview
                key={index}
                file={file}
                index={index}
                onRemove={onFileRemove}
                onCropAudio={handleOpenAudioCrop}
                uploadPercent={fileUploadStates[index]?.percent}
                uploadPhase={fileUploadStates[index]?.phase}
              />
            ))}
          </div>
        )}
        <AudioCropDialog
          open={audioCropOpen}
          file={audioCropTarget?.file || null}
          suggestedDurationSec={suggestedCropDurationSec}
          onOpenChange={setAudioCropOpen}
          onApply={handleApplyAudioCrop}
        />

        {/* Storyboard Chat Area */}
        {selectedStoryboard && (
          <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-950/30 rounded-lg border border-blue-200 dark:border-blue-800">
            <div className="flex items-center gap-2 mb-2">
              <MessageSquare className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                {interpolate(t('da.composer.storyboardChat'), {
                  shot: selectedStoryboard.shot_number ?? '',
                  version: selectedStoryboard.version_number ?? '',
                })}
              </span>
            </div>
            <div className="flex gap-2">
              <Input
                value={storyboardChatMessage}
                onChange={e => onStoryboardChatMessageChange?.(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    onStoryboardChatSend?.()
                  }
                }}
                placeholder={t('storyboardDescribeChanges')}
                className="flex-1 text-xs"
              />
              <Button
                onClick={() => { onStoryboardChatSend?.() }}
                disabled={!storyboardChatMessage.trim()}
                size="sm"
                className="bg-blue-600 hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-600"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* 对话中结果图详情：放大、下载、分享、分格 */}
      <Dialog open={!!chatImageDetail} onOpenChange={(open) => { if (!open) resetChatImageDetail() }}>
        <DialogContent className={showImageResultsInChat ? 'max-w-none w-full h-full sm:max-w-4xl sm:h-auto sm:max-h-[90vh] p-0 overflow-hidden rounded-none sm:rounded-lg flex flex-col bg-black' : 'max-w-4xl w-full p-0 max-h-[90vh] overflow-y-auto'}>
          {showImageResultsInChat && chatImageDetail && <DialogTitle className="sr-only">{chatImageDetail.title}</DialogTitle>}
          {showImageResultsInChat && chatImageDetail ? (
            /* 移动端：全屏风格 - 顶部返回按钮、大图、右侧操作列、底部双按钮 */
            <>
              {/* 顶部返回按钮（图片上方） */}
              <div className="shrink-0 flex items-center px-4 py-3 border-b border-white/10">
                <button type="button" onClick={() => { if (chatSplitMode) { setChatSplitMode(false); setChatSplitTiles(null); setChatPreviewTile(null); setChatSplitError(null) } else resetChatImageDetail() }} className="p-2 rounded-full hover:bg-white/10 text-white flex items-center justify-center" aria-label={t('back') || 'Back'}>
                  <ArrowLeft className="w-5 h-5" />
                </button>
              </div>
              {/* 主内容区：大图 + 右侧操作列 */}
              <div className="flex-1 min-h-0 flex relative">
                {!chatSplitMode ? (
                  <>
                    <div className="absolute inset-0 flex items-center justify-center bg-black">
                      <img src={chatImageDetail.url} alt={chatImageDetail.title} className="max-w-full max-h-full w-auto h-auto object-contain" />
                    </div>
                    {/* 右侧竖排操作：图标+文字，与关闭按钮横向居中对齐 */}
                    <div className="absolute right-3 top-[34px] flex flex-col gap-5 z-10">
                      <button type="button" onClick={() =>{  setChatSplitMode(true) }} className="flex flex-col items-center gap-1 text-white hover:opacity-80">
                        <Scissors className="w-5 h-5" />
                        <span className="text-xs">{t('splitCollage')}</span>
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
                    <div className="flex justify-center rounded-lg bg-black/20 overflow-hidden relative">
                      <div className="relative inline-block">
                        <img src={chatImageDetail.url} alt={chatImageDetail.title} className="max-w-full max-h-[40vh] block" />
                        {/* 分割线预览覆盖层 */}
                        <div className="absolute inset-0 pointer-events-none">
                          {Array.from({ length: chatSplitCols - 1 }).map((_, i) => (
                            <div key={`v-${i}`} className="absolute top-0 bottom-0 flex items-center flex-shrink-0" style={{ left: `${((i + 1) / chatSplitCols) * 100}%` }}>
                              <div className="absolute left-0 w-[3px] sm:w-[2px] min-w-[3px] sm:min-w-[2px] h-full bg-red-500 shadow-[0_0_4px_rgba(239,68,68,0.6)] shrink-0" style={{ marginLeft: '-1.5px', transform: 'translateZ(0)' }} />
                            </div>
                          ))}
                          {Array.from({ length: chatSplitRows - 1 }).map((_, i) => (
                            <div key={`h-${i}`} className="absolute left-0 right-0 flex justify-center flex-shrink-0" style={{ top: `${((i + 1) / chatSplitRows) * 100}%` }}>
                              <div className="absolute top-0 w-full h-[3px] sm:h-[2px] min-h-[3px] sm:min-h-[2px] bg-red-500 shadow-[0_0_4px_rgba(239,68,68,0.6)] shrink-0" style={{ marginTop: '-1.5px', transform: 'translateZ(0)' }} />
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                    <MobileSplitCard
                      gridPresets={CHAT_GRID_PRESETS}
                      splitRows={chatSplitRows}
                      splitCols={chatSplitCols}
                      onRowsChange={(rows) =>{  setChatSplitRows(rows) }}
                      onColsChange={(cols) =>{  setChatSplitCols(cols) }}
                      onPresetSelect={(rows, cols) => { setChatSplitRows(rows); setChatSplitCols(cols) }}
                      onSplit={asyncEvent(handleChatSplitCollage)}
                      isSplitting={chatSplitSplitting}
                      splitError={chatSplitError}
                      splitTiles={chatSplitTiles}
                      onTileClick={setChatPreviewTile}
                      imageTitle={chatImageDetail.title}
                      onBack={() => {
                        setChatSplitMode(false)
                        setChatSplitTiles(null)
                        setChatPreviewTile(null)
                        setChatSplitError(null)
                      }}
                      hideBackButton
                    />
                  </div>
                )}
              </div>
              {/* 底部双按钮：下载(白色)、分享(粉紫色) */}
              {!chatSplitMode && (
                <div className="shrink-0 flex gap-3 px-4 py-4 pb-6 border-t border-white/10">
                  <Button type="button" className="flex-1 h-12 bg-white text-gray-900 hover:bg-gray-50 rounded-lg flex items-center justify-center gap-2" onClick={asyncEvent(() => handleChatImageDownload(chatImageDetail))}>
                    <Download className="w-4 h-4" />
                    <span>{t('save')}</span>
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button type="button" className="flex-1 h-12 bg-gradient-to-r from-pink-500 to-purple-500 text-white hover:from-pink-600 hover:to-purple-600 rounded-lg flex items-center justify-center gap-2">
                        <Share2 className="w-4 h-4" />
                        <span>{t('shareToFriends')}</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      side="top"
                      className="w-56 bg-white/95 dark:bg-gray-900/95 backdrop-blur-md border-0 shadow-2xl rounded-xl p-2 min-w-[200px]"
                      sideOffset={8}
                    >
                      <DropdownMenuItem
                        onClick={asyncEvent(handleCopyLink)}
                        className="cursor-pointer rounded-lg px-4 py-3 text-base hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                      >
                        <Copy className="w-5 h-5 mr-3 text-gray-600 dark:text-gray-400" />
                        <span className="font-medium">{t('copyLink')}</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={asyncEvent(handleShareDirectly)}
                        className="cursor-pointer rounded-lg px-4 py-3 text-base hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                      >
                        <Share2 className="w-5 h-5 mr-3 text-gray-600 dark:text-gray-400" />
                        <span className="font-medium">{t('shareDirectly')}</span>
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )}
            </>
          ) : (
            <>
              {!showImageResultsInChat && (
                <DialogHeader className="p-6 pb-4">
                  <DialogTitle className="text-lg font-semibold flex items-center gap-2">
                    {chatSplitMode ? (
                      <><Scissors className="w-5 h-5" />{t('splitCollage')}</>
                    ) : (
                      <><ZoomIn className="w-5 h-5" />{chatImageDetail?.title}</>
                    )}
                  </DialogTitle>
                </DialogHeader>
              )}
              {chatImageDetail && !showImageResultsInChat && (
                <div className="px-6 pb-6 space-y-4">
                  {!chatSplitTiles && (
                    <div className="flex justify-center rounded-lg bg-black/5 dark:bg-black/20 overflow-hidden">
                      <img src={chatImageDetail.url} alt={chatImageDetail.title} className="max-w-full max-h-[55vh] block" />
                    </div>
                  )}
                  {chatSplitMode && !chatSplitTiles && (
                    <div className="space-y-4 p-4 rounded-lg border border-white/20 dark:border-gray-700/50 bg-white/30 dark:bg-gray-800/30">
                      {/* Presets */}
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-foreground">
                          {t('gridPresets')}
                        </label>
                        <div className="flex flex-wrap gap-2">
                          {CHAT_GRID_PRESETS.map(p => (
                            <button
                              key={p.label}
                              onClick={() => { setChatSplitRows(p.rows); setChatSplitCols(p.cols) }}
                              className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                                chatSplitRows === p.rows && chatSplitCols === p.cols
                                  ? 'bg-primary text-primary-foreground border-primary'
                                  : 'bg-white/50 dark:bg-gray-700/50 border-white/20 dark:border-gray-600 hover:bg-white/80 dark:hover:bg-gray-700/80 text-gray-900 dark:text-gray-100'
                              }`}
                            >
                              {p.label}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Custom Rows / Cols */}
                      <div className="flex flex-wrap gap-6">
                        {/* Rows */}
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground w-12">
                            {t('rows')}
                          </span>
                          <Button
                            variant="outline" size="icon" className="w-7 h-7 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600"
                            onClick={() =>{  setChatSplitRows(Math.max(1, chatSplitRows - 1)) }}
                            disabled={chatSplitRows <= 1}
                          >
                            <Minus className="w-3 h-3 text-gray-900 dark:text-gray-100" />
                          </Button>
                          <span className="text-sm font-medium w-6 text-center text-gray-900 dark:text-gray-100 bg-white dark:bg-gray-700 px-2 py-1 rounded">{chatSplitRows}</span>
                          <Button
                            variant="outline" size="icon" className="w-7 h-7 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600"
                            onClick={() =>{  setChatSplitRows(Math.min(10, chatSplitRows + 1)) }}
                            disabled={chatSplitRows >= 10}
                          >
                            <Plus className="w-3 h-3 text-gray-900 dark:text-gray-100" />
                          </Button>
                        </div>
                        {/* Cols */}
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground w-12">
                            {t('cols')}
                          </span>
                          <Button
                            variant="outline" size="icon" className="w-7 h-7 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600"
                            onClick={() =>{  setChatSplitCols(Math.max(1, chatSplitCols - 1)) }}
                            disabled={chatSplitCols <= 1}
                          >
                            <Minus className="w-3 h-3 text-gray-900 dark:text-gray-100" />
                          </Button>
                          <span className="text-sm font-medium w-6 text-center text-gray-900 dark:text-gray-100 bg-white dark:bg-gray-700 px-2 py-1 rounded">{chatSplitCols}</span>
                          <Button
                            variant="outline" size="icon" className="w-7 h-7 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600"
                            onClick={() =>{  setChatSplitCols(Math.min(10, chatSplitCols + 1)) }}
                            disabled={chatSplitCols >= 10}
                          >
                            <Plus className="w-3 h-3 text-gray-900 dark:text-gray-100" />
                          </Button>
                        </div>
                      </div>

                      {/* Split button */}
                      <Button
                        className="w-full"
                        onClick={asyncEvent(handleChatSplitCollage)}
                        disabled={chatSplitSplitting}
                      >
                        {chatSplitSplitting ? (
                          <>
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            {t('splitting')}
                          </>
                        ) : (
                          <>
                            <Scissors className="w-4 h-4 mr-2" />
                            {t('splitNow')}
                          </>
                        )}
                      </Button>
                    </div>
                  )}
                  {chatSplitError && (
                    <div className="text-sm text-destructive bg-destructive/10 rounded-lg p-3">{chatSplitError}</div>
                  )}
                  {chatSplitTiles && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">{chatSplitTiles.length} {t('imagesSplit')}</span>
                        <Button size="sm" onClick={asyncEvent(async () => { const base = chatImageDetail.title.replace(/\s+/g, '_'); await downloadAllTiles(chatSplitTiles, base) })}>
                          <Download className="w-4 h-4 mr-2" />{t('downloadAll')}
                        </Button>
                      </div>
                      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${chatSplitCols}, 1fr)` }}>
                        {chatSplitTiles.map(tile => (
                          <div key={tile.index} className="relative rounded-lg overflow-hidden border border-border cursor-pointer hover:ring-2 hover:ring-primary/50" onClick={() =>{  setChatPreviewTile(tile) }}>
                            <img src={tile.dataUrl} alt={`${tile.index + 1}`} className="w-full h-auto object-contain" />
                            <span className="absolute top-1 left-1 bg-black/60 text-white text-[10px] font-bold rounded-full w-5 h-5 flex items-center justify-center">{tile.index + 1}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex justify-between items-center gap-2 flex-wrap">
                    {chatSplitMode ? (
                      <>
                        <Button variant="outline" size="sm" onClick={() => { setChatSplitMode(false); setChatSplitTiles(null); setChatSplitError(null) }}>
                          <X className="w-4 h-4 mr-2" />{t('back')}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => { setChatShareDialog(true) }}>
                          <Share2 className="w-4 h-4 mr-2" />{t('shareToFriends')}
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button variant="outline" size="sm" onClick={() =>{  setChatSplitMode(true) }}>
                          <Scissors className="w-4 h-4 mr-2" />{t('splitCollage')}
                        </Button>
                        <div className="flex gap-2">
                          <Button variant="outline" size="sm" onClick={() => { setChatShareDialog(true) }}>
                            <Share2 className="w-4 h-4 mr-2" />{t('shareToFriends')}
                          </Button>
                          <Button size="sm" onClick={asyncEvent(() => handleChatImageDownload(chatImageDetail))}>
                            <Download className="w-4 h-4 mr-2" />{t('download')}
                          </Button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* 分格后单张 tile 大图预览 */}
      <Dialog open={!!chatPreviewTile} onOpenChange={(o) => { if (!o) setChatPreviewTile(null) }}>
        <DialogContent className="max-w-[95vw] max-h-[95vh] w-auto p-0 overflow-hidden flex flex-col items-center">
          <DialogHeader className="p-4 pb-0 shrink-0">
            <DialogTitle className="text-base">{chatPreviewTile ? `#${chatPreviewTile.index + 1}` : ''}</DialogTitle>
          </DialogHeader>
          {chatPreviewTile && (
            <>
              <div className="flex-1 overflow-auto p-4 flex items-center justify-center bg-muted/20 min-h-0">
                <img src={chatPreviewTile.dataUrl} alt={`#${chatPreviewTile.index + 1}`} className="max-w-full max-h-[70vh] w-auto h-auto object-contain" />
              </div>
              <div className="p-4 flex justify-end gap-2 border-t">
                <Button size="sm" variant="outline" onClick={() => { setChatShareDialog(true) }}>
                  <Share2 className="w-4 h-4 mr-2" />{t('shareToFriends')}
                </Button>
                <Button size="sm" onClick={() => { const base = chatImageDetail?.title.replace(/\s+/g, '_') || 'image'; downloadBlob(chatPreviewTile.blob, `${base}_${chatPreviewTile.index + 1}.png`) }}>
                  <Download className="w-4 h-4 mr-2" />{t('download')}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* 分享弹窗 */}
      <Dialog open={chatShareDialog && !!chatImageDetail} onOpenChange={(o) => { setChatShareDialog(o); if (!o) { setChatShareMode('normal'); setChatShareWatermarkedUrl(null); setChatShareWatermarkedBlob(null) } }}>
        <DialogContent className="max-w-md p-0 overflow-hidden">
          <DialogHeader className="p-4 pb-2">
            <DialogTitle className="text-base">{t('shareToFriends')}</DialogTitle>
          </DialogHeader>
          {chatImageDetail && (
            <>
              <Tabs value={chatShareMode} onValueChange={(v) =>{  setChatShareMode(v as 'normal' | 'gift') }} className="px-4">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="normal">{t('shareModeNormal')}</TabsTrigger>
                  <TabsTrigger value="gift">{t('shareModeGift')}</TabsTrigger>
                </TabsList>
                <TabsContent value="normal" className="mt-3">
                  <div className="rounded-lg border bg-muted/30 p-4 flex flex-col items-center">
                    {chatShareWatermarkedUrl ? (
                      <>
                        <img src={chatShareWatermarkedUrl} alt={chatImageDetail.title} className="max-h-48 w-auto object-contain rounded" />
                        <span className="text-xs text-muted-foreground mt-2">{chatImageDetail.title}</span>
                      </>
                    ) : (
                      <div className="flex items-center justify-center py-6">
                        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                      </div>
                    )}
                  </div>
                </TabsContent>
                <TabsContent value="gift" className="mt-3">
                  <div className="rounded-lg border-2 border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30 p-4 flex flex-col items-center relative">
                    <div className="absolute top-2 right-4 text-amber-600 dark:text-amber-400 text-xs font-medium">{t('giftForYou')}</div>
                    {chatShareWatermarkedUrl ? (
                      <>
                        <img src={chatShareWatermarkedUrl} alt={chatImageDetail.title} className="max-h-48 w-auto object-contain rounded shadow-md" />
                        <span className="text-xs text-muted-foreground mt-2">{chatImageDetail.title}</span>
                      </>
                    ) : (
                      <div className="flex items-center justify-center py-6">
                        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                      </div>
                    )}
                  </div>
                </TabsContent>
              </Tabs>
              <div className="p-4 pt-2 flex justify-end gap-2 border-t">
                <Button size="sm" variant="outline" onClick={asyncEvent(async () => {
                  try {
                    const basePath = (import.meta.env.BASE_URL || '').replace(/\/$/, '')
                    const shareUrl = `${window.location.origin}${basePath}/${language}/share/image?mode=${chatShareMode}&image=${encodeURIComponent(chatImageDetail.url)}&title=${encodeURIComponent(chatImageDetail.title)}`
                    await navigator.clipboard.writeText(shareUrl)
                    toast.success(t('copyLinkSuccess'))
                  } catch (e) {
                    toast.error(displayValue(e))
                  }
                })}>
                  {t('copyLink')}
                </Button>
                <Button size="sm" onClick={asyncEvent(async () => {
                  const shareTitle = chatImageDetail.title
                  const shareText = chatShareMode === 'gift' ? (t('giftForYou') || 'A gift for you') : (t('shareImageDescription') || 'Check out this image')

                  // 优先用带水印的图片文件直接分享
                  if (chatShareWatermarkedBlob && typeof navigator.share === 'function') {
                    const file = new File([chatShareWatermarkedBlob], `${shareTitle.replace(/\s+/g, '_')}.png`, { type: 'image/png' })
                    if (navigator.canShare({ files: [file] })) {
                      try {
                        await navigator.share({ title: shareTitle, text: shareText, files: [file] })
                        setChatShareDialog(false)
                        return
                      } catch (e) {
                        if ((e as Error).name === 'AbortError') return
                        // 文件分享失败，降级到 URL 分享
                      }
                    }
                  }

                  // 降级：URL 分享
                  const basePath = (import.meta.env.BASE_URL || '').replace(/\/$/, '')
                  const shareUrl = `${window.location.origin}${basePath}/${language}/share/image?mode=${chatShareMode}&image=${encodeURIComponent(chatImageDetail.url)}&title=${encodeURIComponent(shareTitle)}`
                  if (typeof navigator.share === 'function') {
                    try {
                      await navigator.share({ title: shareTitle, text: shareText, url: shareUrl })
                      setChatShareDialog(false)
                    } catch (e) {
                      if ((e as Error).name !== 'AbortError') {
                        try { await navigator.clipboard.writeText(shareUrl); toast.success(t('copyLinkSuccess')) } catch { toast.error(displayValue(e)) }
                      }
                    }
                  } else {
                    try { await navigator.clipboard.writeText(shareUrl); toast.success(t('copyLinkSuccess')) } catch (e) { toast.error(displayValue(e)) }
                  }
                })}>
                  <Share2 className="w-4 h-4 mr-2" />{t('shareDirectly')}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Sora 模型选择确认对话框 */}
      <AlertDialog open={showSoraDialog} onOpenChange={setShowSoraDialog}>
        <AlertDialogContent className="max-w-md">
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
                onModelChange?.(pendingSoraModel)
                setShowSoraDialog(false)
                setPendingSoraModel('')
              }}
            >
              {t('continue') || 'Continue'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cuti 头像大图预览 */}
      <Dialog open={showCutiAvatarLightbox} onOpenChange={setShowCutiAvatarLightbox}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] w-auto p-2 border-0 bg-transparent shadow-none">
          <DialogTitle className="sr-only">Cuti avatar</DialogTitle>
          <img
            src={aiAvatar}
            alt="Cuti"
            className="max-w-full max-h-[85vh] w-auto h-auto object-contain rounded-lg"
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}
