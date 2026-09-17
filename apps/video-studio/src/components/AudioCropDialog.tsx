import { asyncEvent } from '../utils/asyncEvent'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Pause, Play, Scissors } from 'lucide-react'
import { toast } from 'sonner'
import { createWaveformPeaks, cropAudioFile, decodeAudioFile } from '@/utils/audioCrop'
import { useLanguage } from '@/i18n/LanguageContext'

interface AudioCropDialogProps {
  open: boolean
  file: File | null
  /** 用户显式指定的目标视频时长；用于 AI 推荐区间 + 手动「建议区间」快捷按钮 */
  suggestedDurationSec?: number | null
  onOpenChange: (open: boolean) => void
  onApply: (nextFile: File) => void
}

const MIN_CROP_SECONDS = 1
const RECOMMEND_GAP_SEC = 1

const formatSec = (sec: number) => {
  if (!Number.isFinite(sec)) return '0.00s'
  return `${sec.toFixed(2)}s`
}

export const AudioCropDialog = ({
  open,
  file,
  suggestedDurationSec,
  onOpenChange,
  onApply,
}: AudioCropDialogProps) => {
  const { t } = useLanguage()
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const progressTrackRef = useRef<HTMLDivElement | null>(null)
  const [audioUrl, setAudioUrl] = useState<string>('')
  const [duration, setDuration] = useState(0)
  const [range, setRange] = useState<[number, number]>([0, 0])
  const [currentTime, setCurrentTime] = useState(0)
  const [wavePeaks, setWavePeaks] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [cropping, setCropping] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [draggingHandle, setDraggingHandle] = useState<'start' | 'end' | null>(null)

  useEffect(() => {
    if (!open || !file) return
    const operation = { cancelled: false }
    const isCancelled = () => operation.cancelled

    const run = async () => {
      setLoading(true)
      try {
        const decoded = await decodeAudioFile(file)
        if (isCancelled()) return
        const dur = Math.max(decoded.duration, MIN_CROP_SECONDS)
        setDuration(dur)
        setRange([0, dur])
        setCurrentTime(0)
        setWavePeaks(createWaveformPeaks(decoded))

        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
        const url = URL.createObjectURL(file)
        objectUrlRef.current = url
        setAudioUrl(url)

        const shouldRecommend =
          suggestedDurationSec != null
          && suggestedDurationSec > 0
          && dur > suggestedDurationSec + RECOMMEND_GAP_SEC

        if (!shouldRecommend) return
        if (isCancelled()) return
      } catch (error: unknown) {
        if (!operation.cancelled) {
          toast.error(error instanceof Error && error.message ? error.message : t('failedParseAudio'))
        }
      } finally {
        if (!operation.cancelled) {
          setLoading(false)
        }
      }
    }

    void run()
    return () => {
      operation.cancelled = true
    }
  }, [open, file, suggestedDurationSec, t])

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handleTimeUpdate = () => {
      const t = audio.currentTime
      setCurrentTime(t)
      if (t >= range[1]) {
        audio.pause()
        audio.currentTime = range[0]
      }
    }
    const handlePause = () =>{  setPlaying(false) }
    const handlePlay = () =>{  setPlaying(true) }

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('play', handlePlay)
    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('play', handlePlay)
    }
  }, [range])

  const selectedDuration = useMemo(() => Math.max(0, range[1] - range[0]), [range])

  const setStart = (value: number) => {
    const nextStart = Math.max(0, Math.min(value, range[1] - MIN_CROP_SECONDS))
    setRange([nextStart, range[1]])
  }

  const setEnd = (value: number) => {
    const nextEnd = Math.min(duration, Math.max(value, range[0] + MIN_CROP_SECONDS))
    setRange([range[0], nextEnd])
  }

  const togglePlay = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      return
    }
    if (audio.currentTime < range[0] || audio.currentTime > range[1]) {
      audio.currentTime = range[0]
    }
    try {
      await audio.play()
    } catch {
      setPlaying(false)
    }
  }

  const getSecFromPointer = (clientX: number) => {
    const el = progressTrackRef.current
    if (!el) return 0
    const rect = el.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)))
    return ratio * safeDuration
  }

  useEffect(() => {
    if (!draggingHandle) return
    const onMove = (event: PointerEvent) => {
      const sec = getSecFromPointer(event.clientX)
      if (draggingHandle === 'start') {
        setStart(sec)
      } else {
        setEnd(sec)
      }
    }
    const onUp = () =>{  setDraggingHandle(null) }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [draggingHandle, range, duration])

  const handleApplyCrop = async () => {
    if (!file) return
    setCropping(true)
    try {
      const cropped = await cropAudioFile(file, range[0], range[1])
      onApply(cropped)
      onOpenChange(false)
      toast.success(t('audioCropped'))
    } catch (error: unknown) {
      toast.error(error instanceof Error && error.message ? error.message : t('failedCropAudio'))
    } finally {
      setCropping(false)
    }
  }

  const safeDuration = duration || 1
  const startRatio = (range[0] / safeDuration) * 100
  const endRatio = (range[1] / safeDuration) * 100
  const playheadRatio = (currentTime / safeDuration) * 100

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(92vw,42rem)] max-w-2xl overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Scissors className="w-4 h-4" />
            {t('cropAudioTitle')}
          </DialogTitle>
        </DialogHeader>

        {!file || loading ? (
          <div className="text-sm text-muted-foreground py-8 text-center">{t('loadingAudio')}</div>
        ) : (
          <div className="space-y-4 min-w-0">
            <div className="flex items-center justify-between gap-2 min-w-0">
              <div className="text-sm truncate flex-1 min-w-0" title={file.name}>{file.name}</div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <Badge variant="secondary">{t('selectedDuration')}: {formatSec(selectedDuration)}</Badge>
                <span className="text-[11px] text-muted-foreground">{t('totalDuration')}: {formatSec(duration)}</span>
              </div>
            </div>

            {suggestedDurationSec != null &&
              suggestedDurationSec > 0 &&
              suggestedDurationSec < duration - 0.05 && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-muted/15 px-3 py-2">
                <span className="text-xs text-muted-foreground">
                  {t('suggestedCropHint').replace('{duration}', formatSec(suggestedDurationSec))}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>{  setRange([0, Math.min(duration, suggestedDurationSec)]) }}
                >
                  {t('applySuggestedCrop')}
                </Button>
              </div>
            )}

            <div className="rounded-md border border-border/60 p-3 bg-muted/20 max-w-full overflow-hidden">
              <div className="relative h-24 w-full overflow-hidden rounded select-none">
                <div
                  className="absolute inset-0 grid items-end gap-[2px]"
                  style={{ gridTemplateColumns: `repeat(${Math.max(1, wavePeaks.length)}, minmax(0, 1fr))` }}
                >
                  {wavePeaks.map((peak, idx) => {
                    const pct = (idx / Math.max(1, wavePeaks.length - 1)) * 100
                    const selected = pct >= startRatio && pct <= endRatio
                    return (
                      <div
                        key={idx}
                        className={selected ? 'bg-primary/90' : 'bg-muted-foreground/30'}
                        style={{ height: `${Math.max(6, peak * 100)}%` }}
                      />
                    )
                  })}
                </div>
                <div
                  className="absolute top-0 bottom-0 w-[2px] bg-red-500"
                  style={{ left: `${Math.min(100, Math.max(0, playheadRatio))}%` }}
                />
                <div
                  className="absolute top-0 bottom-0 w-[2px] bg-emerald-500"
                  style={{ left: `${Math.min(100, Math.max(0, startRatio))}%` }}
                />
                <div
                  className="absolute top-0 bottom-0 w-[2px] bg-blue-500"
                  style={{ left: `${Math.min(100, Math.max(0, endRatio))}%` }}
                />
              </div>
              <div className="text-xs text-muted-foreground mt-2">{t('waveformLabel')}</div>
            </div>

            <div className="space-y-2">
              <div className="relative pt-7 pb-3 px-1 max-w-full overflow-hidden">
                <div ref={progressTrackRef} className="relative h-2 w-full rounded-full bg-muted-foreground/20">
                  <div
                    className="absolute top-0 h-2 rounded-full bg-primary/70"
                    style={{
                      left: `${Math.min(100, Math.max(0, startRatio))}%`,
                      width: `${Math.min(100, Math.max(0, endRatio - startRatio))}%`,
                    }}
                  />
                  <div
                    className="absolute top-[-4px] bottom-[-4px] w-[2px] bg-red-500"
                    style={{ left: `${Math.min(100, Math.max(0, playheadRatio))}%` }}
                  />
                  <button
                    type="button"
                    className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full border-2 border-white bg-emerald-500 shadow cursor-ew-resize"
                    style={{ left: `${Math.min(99, Math.max(1, startRatio))}%` }}
                    onPointerDown={(e) => {
                      e.preventDefault()
                      setDraggingHandle('start')
                    }}
                    aria-label={t('dragStartHandle')}
                    title={`${t('cropStart')} ${formatSec(range[0])}`}
                  />
                  <button
                    type="button"
                    className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full border-2 border-white bg-blue-500 shadow cursor-ew-resize"
                    style={{ left: `${Math.min(99, Math.max(1, endRatio))}%` }}
                    onPointerDown={(e) => {
                      e.preventDefault()
                      setDraggingHandle('end')
                    }}
                    aria-label={t('dragEndHandle')}
                    title={`${t('cropEnd')} ${formatSec(range[1])}`}
                  />
                </div>
                <div
                  className="absolute top-0 -translate-x-1/2 text-[10px] px-1 py-0.5 rounded bg-emerald-600 text-white whitespace-nowrap"
                  style={{ left: `${Math.min(96, Math.max(4, startRatio))}%` }}
                >
                  {t('cropStart')}
                </div>
                <div
                  className="absolute top-0 -translate-x-1/2 text-[10px] px-1 py-0.5 rounded bg-blue-600 text-white whitespace-nowrap"
                  style={{ left: `${Math.min(96, Math.max(4, endRatio))}%` }}
                >
                  {t('cropEnd')}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-muted-foreground mb-1">{t('startSeconds')}</div>
                  <Input
                    type="number"
                    min={0}
                    max={Math.max(0, range[1] - MIN_CROP_SECONDS)}
                    step={0.01}
                    value={range[0].toFixed(2)}
                    onChange={(e) =>{  setStart(Number(e.target.value || 0)) }}
                  />
                </div>
                <div>
                  <div className="text-xs text-muted-foreground mb-1">{t('endSeconds')}</div>
                  <Input
                    type="number"
                    min={Math.min(duration, range[0] + MIN_CROP_SECONDS)}
                    max={duration}
                    step={0.01}
                    value={range[1].toFixed(2)}
                    onChange={(e) =>{  setEnd(Number(e.target.value || duration)) }}
                  />
                </div>
              </div>
            </div>

            <audio ref={audioRef} src={audioUrl} preload="metadata" className="hidden" />

            <div className="flex items-center justify-between">
              <Button variant="outline" type="button" onClick={asyncEvent(togglePlay)}>
                {playing ? <Pause className="w-4 h-4 mr-1" /> : <Play className="w-4 h-4 mr-1" />}
                {playing ? t('pausePreview') : t('playPreview')}
              </Button>
              <Button type="button" onClick={asyncEvent(handleApplyCrop)} disabled={cropping}>
                {cropping ? t('cropping') : t('applyCrop')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
