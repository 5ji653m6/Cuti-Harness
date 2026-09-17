import { useEffect, useRef, useState } from 'react'
import { Play, Pause } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { WaveformCanvas } from './WaveformCanvas'

/** 后端 interrupt_data.smart_clip 数据契约（与 plan §3.4.1 对齐） */
export interface SmartClipPayload {
  status: string
  audio_url: string
  audio_duration_sec: number
  target_duration_sec: number
  recommended: {
    start_sec: number
    end_sec: number
    fade_in_sec: number
    fade_out_sec: number
    target_duration_sec: number
    actual_duration_sec: number
    duration_error_sec: number
    reasoning?: string
  }
  fallback_used?: boolean
  method?: string
  peaks?: { sample_count: number; duration: number; values: number[] } | null
  music_generation_uuid?: string
  user_confirmed?: unknown
}

export interface SmartClipDecision {
  accepted: boolean
  start_sec?: number
  end_sec?: number
  fade_in_sec?: number
  fade_out_sec?: number
  music_generation_uuid?: string
}

/** after_music 门闩：智能裁切已就绪（与后端 interrupt payload 一致） */
export function isSmartClipReadyForInterrupt(interruptData: unknown): boolean {
  if (!interruptData || typeof interruptData !== 'object') return false
  const sc = (interruptData as { smart_clip?: SmartClipPayload }).smart_clip
  return sc?.status === 'ready' && !!sc.recommended
}

/** 继续 / 15s 倒计时默认：采用 AI 推荐区间裁切（等同面板默认滑块 + 确认裁切） */
export function buildRecommendedSmartClipDecision(smartClip: SmartClipPayload): SmartClipDecision {
  const rec = smartClip.recommended
  return {
    accepted: true,
    start_sec: rec.start_sec,
    end_sec: rec.end_sec,
    fade_in_sec: rec.fade_in_sec,
    fade_out_sec: rec.fade_out_sec,
    music_generation_uuid: smartClip.music_generation_uuid,
  }
}

interface SmartClipPanelProps {
  smartClip: SmartClipPayload
  /** 用户作出选择后回调（点 "应用" / "保留原版"），父组件用此打包到 resume_data */
  onConfirm: (decision: SmartClipDecision) => void
  /** 是否禁用所有按钮（resume 进行中） */
  disabled?: boolean
  /** 国际化函数；可不传，用英文兜底 */
  t?: (k: string) => string
}

const FADE_MAX = 5
const MIN_SELECTION_SECONDS = 0.2

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}

export function SmartClipPanel({ smartClip, onConfirm, disabled, t }: SmartClipPanelProps) {
  const audioDuration = Math.max(0.01, (smartClip.audio_duration_sec || 0))
  const target = Math.max(0.01, (smartClip.target_duration_sec || 0))
  const rec = smartClip.recommended

  const [start, setStart] = useState<number>(clamp(rec.start_sec, 0, audioDuration))
  const [end, setEnd] = useState<number>(clamp(rec.end_sec, 0, audioDuration))
  const [fadeIn, setFadeIn] = useState<number>(clamp(rec.fade_in_sec, 0, FADE_MAX))
  const [fadeOut, setFadeOut] = useState<number>(clamp(rec.fade_out_sec, 0, FADE_MAX))

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const progressTrackRef = useRef<HTMLDivElement | null>(null)
  const [isPlayingSelection, setIsPlayingSelection] = useState(false)
  const [cursor, setCursor] = useState<number | null>(null)
  const [draggingHandle, setDraggingHandle] = useState<'start' | 'end' | null>(null)
  /** 选区/候选预览的播放上限（秒），onTimeUpdate 到达时停。null 表示不限（全曲播放） */
  const stopAtRef = useRef<number | null>(null)
  const [audioError, setAudioError] = useState(false)
  /** 自动重试计数：CDN 边缘节点首请求 cold cache 偶发失败，静默 reload 一次能恢复，避免给用户误报 */
  const audioRetryCountRef = useRef<number>(0)
  const audioRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const peaksValues = smartClip.peaks?.values ?? null

  const tr = (k: string, def?: string) => {
    if (t) {
      const v = t(k)
      if (v && v !== k) return v
    }
    return def ?? k
  }

  const fmtSec = (n: number, digits = 1) => Number.isFinite(n) ? n.toFixed(digits) : '0.0'

  const pauseForRangeEdit = () => {
    const audio = audioRef.current
    if (audio && !audio.paused) {
      audio.pause()
    }
    stopAtRef.current = null
    setIsPlayingSelection(false)
  }

  const setStartSec = (value: number) => {
    pauseForRangeEdit()
    setStart(clamp(value, 0, Math.max(0, end - MIN_SELECTION_SECONDS)))
  }

  const setEndSec = (value: number) => {
    pauseForRangeEdit()
    setEnd(clamp(value, Math.min(audioDuration, start + MIN_SELECTION_SECONDS), audioDuration))
  }

  // 摘要：AI 推荐 25.3s – 38.6s · 共 13.3s，目标 15s（偏差 1.7s）
  const summaryText = (() => {
    const recDur = Math.max(0, (rec.end_sec) - (rec.start_sec))
    const recErr = Math.abs(recDur - target)
    return tr('smartClip.summary', 'Recommended {start}s – {end}s · {dur}s clip, target {target}s (Δ {delta}s)')
      .replace('{start}', fmtSec(rec.start_sec))
      .replace('{end}', fmtSec(rec.end_sec))
      .replace('{dur}', fmtSec(recDur))
      .replace('{target}', fmtSec(target, 0))
      .replace('{delta}', fmtSec(recErr))
  })()

  // 选区拖动：点击波形先决定是哪一端（靠近 start 用 start，靠近 end 用 end）
  const handlePointerDownAt = (timeSec: number) => {
    const dStart = Math.abs(timeSec - start)
    const dEnd = Math.abs(timeSec - end)
    if (dStart <= dEnd) setStartSec(timeSec)
    else setEndSec(timeSec)
  }

  const getTrackSecFromPointer = (clientX: number) => {
    const track = progressTrackRef.current
    if (!track) return 0
    const rect = track.getBoundingClientRect()
    const ratio = clamp((clientX - rect.left) / Math.max(1, rect.width), 0, 1)
    return ratio * audioDuration
  }

  useEffect(() => {
    if (!draggingHandle || disabled) return
    const onMove = (event: PointerEvent) => {
      const sec = getTrackSecFromPointer(event.clientX)
      if (draggingHandle === 'start') {
        setStartSec(sec)
      } else {
        setEndSec(sec)
      }
    }
    const onUp = () =>{  setDraggingHandle(null) }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [draggingHandle, disabled, start, end, audioDuration])

  // 播放选区 [start..end]
  const playSelection = async () => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = start
    stopAtRef.current = end
    setCursor(start)
    try {
      await audio.play()
      setIsPlayingSelection(true)
      setAudioError(false)
    } catch (e) {
      console.warn('smart_clip: playSelection failed', e)
      setAudioError(true)
    }
  }

  const pauseSelection = () => {
    audioRef.current?.pause()
    stopAtRef.current = null
    setIsPlayingSelection(false)
  }

  // audio element 事件挂载：原生 controls 与自定义按钮都只播放当前选区。
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const onTime = () => {
      const c = audio.currentTime
      setCursor(c)
      const stop = stopAtRef.current
      if (stop != null && c >= stop) {
        audio.pause()
        setIsPlayingSelection(false)
        setCursor(stop)
        stopAtRef.current = null
      }
    }
    const onEnded = () => {
      setIsPlayingSelection(false)
      stopAtRef.current = null
    }
    const onPlay = () => {
      audio.currentTime = start
      stopAtRef.current = end
      setCursor(start)
      setIsPlayingSelection(true)
      setAudioError(false)
      audioRetryCountRef.current = 0
    }
    const onPause = () =>{  setIsPlayingSelection(false) }
    const onCanPlay = () => {
      // 加载成功（含 retry 后成功）：复位计数 & 清除错误提示
      audioRetryCountRef.current = 0
      setAudioError(false)
    }
    const onError = () => {
      // CDN 边缘节点首次请求经常 cold cache miss → 浏览器抛 MEDIA_ERR_NETWORK / DECODE。
      // 静默 reload 重试 2 次再向用户报错，避免 "音频加载失败" 的间歇性误报。
      if (audioRetryCountRef.current < 2) {
        audioRetryCountRef.current += 1
        if (audioRetryTimerRef.current) clearTimeout(audioRetryTimerRef.current)
        audioRetryTimerRef.current = setTimeout(() => {
          audioRetryTimerRef.current = null
          try {
            audio.load()
          } catch {
            // load() 抛错忽略，下一轮 error 会被再次捕获
          }
        }, 600 * audioRetryCountRef.current)
        return
      }
      setAudioError(true)
    }
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('canplay', onCanPlay)
    audio.addEventListener('error', onError)
    return () => {
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('canplay', onCanPlay)
      audio.removeEventListener('error', onError)
      if (audioRetryTimerRef.current) {
        clearTimeout(audioRetryTimerRef.current)
        audioRetryTimerRef.current = null
      }
    }
  }, [start, end])

  const accept = (useRecommended: boolean) => {
    const decision: SmartClipDecision = useRecommended
      ? {
        accepted: true,
        start_sec: rec.start_sec,
        end_sec: rec.end_sec,
        fade_in_sec: rec.fade_in_sec,
        fade_out_sec: rec.fade_out_sec,
        music_generation_uuid: smartClip.music_generation_uuid,
      }
      : {
        accepted: true,
        start_sec: start,
        end_sec: end,
        fade_in_sec: fadeIn,
        fade_out_sec: fadeOut,
        music_generation_uuid: smartClip.music_generation_uuid,
      }
    onConfirm(decision)
  }

  const reject = () => {
    onConfirm({ accepted: false, music_generation_uuid: smartClip.music_generation_uuid })
  }

  if (smartClip.status === 'failed') {
    return (
      <div className="mt-3 rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-900/15 p-3">
        <p className="text-sm text-amber-900 dark:text-amber-100">
          {tr('smartClip.failedTitle', 'Smart trim is unavailable, original kept.')}
        </p>
      </div>
    )
  }

  if (smartClip.status !== 'ready') {
    return null
  }

  const dur = Math.max(0, end - start)
  const errSec = Math.abs(dur - target)
  const safeDuration = Math.max(audioDuration, 0.01)
  const startRatio = (start / safeDuration) * 100
  const endRatio = (end / safeDuration) * 100
  const cursorRatio = cursor == null ? null : (cursor / safeDuration) * 100

  return (
    <div className="text-left rounded-2xl border border-amber-300/70 dark:border-amber-700/80 bg-white/95 dark:bg-zinc-950/90 shadow-[0_18px_55px_rgba(245,158,11,0.14)] overflow-hidden">
      {/* Header: 标题 + AI 推荐徽章 + 摘要 */}
      <div className="border-b border-amber-200/70 dark:border-amber-800/60 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/25 dark:to-orange-900/25 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-amber-950 dark:text-amber-50">
            {tr('smartClip.title', 'Smart trim')}
          </span>
          <span className="inline-flex items-center rounded-full bg-amber-600 text-white text-[10px] font-medium px-1.5 py-0.5">
            {tr('smartClip.recommendedBadge', 'AI recommended')}
          </span>
        </div>
        <p className="mt-0.5 text-[12px] text-amber-900/80 dark:text-amber-100/80 break-words">
          {summaryText}
        </p>
      </div>

      {/* Body */}
      <div className="px-3 py-3 space-y-4">
        {/* 原生 audio：让用户随时全曲播放 / 拖进度，解决 "音乐没有播放" */}
        <audio
          ref={audioRef}
          src={smartClip.audio_url}
          preload="metadata"
          controls
          className="w-full h-9 rounded"
        />
        {audioError ? (
          <p className="text-[11px] text-red-600 dark:text-red-300">
            {tr('smartClip.audioLoadFailed', 'Audio failed to load. Try clicking play again.')}
          </p>
        ) : null}

        {/* 波形 + 选区可视化 */}
        <div className="rounded-xl border border-amber-200/70 dark:border-amber-800/70 bg-amber-50/35 dark:bg-amber-950/20 p-3">
          <WaveformCanvas
            peaks={peaksValues}
            durationSec={audioDuration}
            selectionStartSec={start}
            selectionEndSec={end}
            playCursorSec={cursor}
            fadeInSec={fadeIn}
            fadeOutSec={fadeOut}
            height={96}
            onPointerDownAt={handlePointerDownAt}
          />
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between text-[11px] text-amber-900/70 dark:text-amber-100/65">
              <span>0.00s</span>
              <span>{fmtSec(audioDuration, 2)}s</span>
            </div>
            <div className="relative px-2 pb-5 pt-7">
              <div
                ref={progressTrackRef}
                className="relative h-2 touch-none rounded-full bg-amber-950/10 dark:bg-white/10"
                onPointerDown={(event) => {
                  if (disabled) return
                  const sec = getTrackSecFromPointer(event.clientX)
                  handlePointerDownAt(sec)
                }}
              >
                <div
                  className="absolute top-0 h-2 rounded-full bg-gradient-to-r from-emerald-400 via-amber-400 to-sky-400 shadow-[0_0_20px_rgba(245,158,11,0.22)]"
                  style={{
                    left: `${clamp(startRatio, 0, 100)}%`,
                    width: `${clamp(endRatio - startRatio, 0, 100)}%`,
                  }}
                />
                {cursorRatio != null ? (
                  <div
                    className="absolute top-[-6px] bottom-[-6px] w-[2px] rounded-full bg-red-500 shadow"
                    style={{ left: `${clamp(cursorRatio, 0, 100)}%` }}
                  />
                ) : null}
                <button
                  type="button"
                  className="absolute top-1/2 z-10 h-6 w-6 touch-none -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-white bg-emerald-500 shadow-lg ring-4 ring-emerald-500/15 transition hover:scale-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ left: `${clamp(startRatio, 1, 99)}%` }}
                  onPointerDown={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    if (!disabled) setDraggingHandle('start')
                  }}
                  disabled={disabled}
                  aria-label={tr('dragStartHandle', 'Drag start handle')}
                  title={`${tr('smartClip.start', 'Start')} ${fmtSec(start, 2)}s`}
                />
                <button
                  type="button"
                  className="absolute top-1/2 z-10 h-6 w-6 touch-none -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-white bg-sky-500 shadow-lg ring-4 ring-sky-500/15 transition hover:scale-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ left: `${clamp(endRatio, 1, 99)}%` }}
                  onPointerDown={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    if (!disabled) setDraggingHandle('end')
                  }}
                  disabled={disabled}
                  aria-label={tr('dragEndHandle', 'Drag end handle')}
                  title={`${tr('smartClip.end', 'End')} ${fmtSec(end, 2)}s`}
                />
              </div>
              <div
                className="absolute top-0 -translate-x-1/2 rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-medium text-white shadow-sm"
                style={{ left: `${clamp(startRatio, 6, 94)}%` }}
              >
                {tr('smartClip.start', 'Start')}
              </div>
              <div
                className="absolute top-0 -translate-x-1/2 rounded-full bg-sky-600 px-2 py-0.5 text-[10px] font-medium text-white shadow-sm"
                style={{ left: `${clamp(endRatio, 6, 94)}%` }}
              >
                {tr('smartClip.end', 'End')}
              </div>
            </div>
          </div>
        </div>

        {/* 选区微调 */}
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {tr('startSeconds', 'Start (s)')}
              </label>
              <Input
                type="number"
                min={0}
                max={Math.max(0, end - MIN_SELECTION_SECONDS)}
                step={0.01}
                value={start.toFixed(2)}
                onChange={(event) =>{  setStartSec(Number(event.target.value || 0)) }}
                disabled={disabled}
                className="h-9 bg-white/70 dark:bg-zinc-900/70"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {tr('endSeconds', 'End (s)')}
              </label>
              <Input
                type="number"
                min={Math.min(audioDuration, start + MIN_SELECTION_SECONDS)}
                max={audioDuration}
                step={0.01}
                value={end.toFixed(2)}
                onChange={(event) =>{  setEndSec(Number(event.target.value || audioDuration)) }}
                disabled={disabled}
                className="h-9 bg-white/70 dark:bg-zinc-900/70"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {tr('smartClip.fadeIn', 'Fade in')} ({fmtSec(fadeIn, 2)}s)
              </label>
              <Slider
                value={[fadeIn]}
                min={0}
                max={FADE_MAX}
                step={0.1}
                onValueChange={(v) =>{  setFadeIn(clamp(v[0] ?? fadeIn, 0, FADE_MAX)) }}
                disabled={disabled}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {tr('smartClip.fadeOut', 'Fade out')} ({fmtSec(fadeOut, 2)}s)
              </label>
              <Slider
                value={[fadeOut]}
                min={0}
                max={FADE_MAX}
                step={0.1}
                onValueChange={(v) =>{  setFadeOut(clamp(v[0] ?? fadeOut, 0, FADE_MAX)) }}
                disabled={disabled}
              />
            </div>
          </div>
        </div>

        {/* 选区数值小结 + 内联试听按钮 + reasoning */}
        <div className="rounded-md bg-amber-50/60 dark:bg-amber-900/15 px-2.5 py-2 border border-amber-200/70 dark:border-amber-800/60">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={isPlayingSelection ? pauseSelection : playSelection}
              disabled={disabled}
              title={
                isPlayingSelection
                  ? tr('smartClip.pause', 'Pause')
                  : tr('smartClip.previewSelection', 'Preview selection')
              }
              aria-label={
                isPlayingSelection
                  ? tr('smartClip.pause', 'Pause')
                  : tr('smartClip.previewSelection', 'Preview selection')
              }
              className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 shadow-sm shrink-0"
            >
              {isPlayingSelection ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 translate-x-[1px]" />}
            </button>
            <p className="text-[11px] text-amber-900 dark:text-amber-100">
              <span className="font-medium">{tr('smartClip.lengthInfo', 'Selection')}:</span> {fmtSec(dur)}s
              <span className="mx-1.5 text-amber-700/60">·</span>
              <span className="font-medium">{tr('smartClip.target', 'Target')}:</span> {fmtSec(target, 0)}s
              <span className="mx-1.5 text-amber-700/60">·</span>
              <span className="font-medium">{tr('smartClip.delta', 'Δ')}:</span> {fmtSec(errSec)}s
            </p>
          </div>
        </div>

      </div>

      {/* Footer 按钮组：仅"保留原版" + "应用我的选择"（默认值已是 AI 推荐） */}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-amber-200/70 dark:border-amber-800/60 bg-amber-50/40 dark:bg-amber-900/15 px-3 py-2.5">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={reject}
          disabled={disabled}
        >
          {tr('smartClip.keepOriginal', 'Keep original (no trim)')}
        </Button>
        <Button
          type="button"
          size="sm"
          className="bg-amber-600 hover:bg-amber-700 text-white shadow-sm"
          onClick={() =>{  accept(false) }}
          disabled={disabled}
        >
          {tr('smartClip.applyMine', 'Apply my selection')}
        </Button>
      </div>
    </div>
  )
}

export default SmartClipPanel
