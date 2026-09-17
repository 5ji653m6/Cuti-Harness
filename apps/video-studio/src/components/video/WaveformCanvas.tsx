import { useEffect, useRef } from 'react'

interface WaveformCanvasProps {
  /** 后端 audio_peaks 返回的归一化数组 [0,1]；为空时画一条占位中线 */
  peaks: number[] | null | undefined
  /** 总时长（秒）；用于计算 selection / cursor 像素 */
  durationSec: number
  /** 选区起点（秒） */
  selectionStartSec: number
  /** 选区终点（秒） */
  selectionEndSec: number
  /** 当前播放游标（秒）；不传则不画 */
  playCursorSec?: number | null
  /** 高度像素；默认 80 */
  height?: number
  /** 选区边缘 fade 区域宽度（秒） */
  fadeInSec?: number
  fadeOutSec?: number
  /** 鼠标点击波形时回调（秒），用于 SelectionWindow 拖动 */
  onPointerDownAt?: (timeSec: number) => void
}

/** 轻量 canvas 波形：512 sample 柱状峰值 + 选区高亮 + fade 渐变阴影。
 *  ⚠️ 不依赖 wavesurfer.js / peaks.js（~200KB+），只用 native canvas。
 */
export function WaveformCanvas({
  peaks,
  durationSec,
  selectionStartSec,
  selectionEndSec,
  playCursorSec,
  height = 80,
  fadeInSec = 0,
  fadeOutSec = 0,
  onPointerDownAt,
}: WaveformCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const dpr = window.devicePixelRatio || 1
    const cssWidth = container.clientWidth
    const cssHeight = height
    canvas.width = Math.floor(cssWidth * dpr)
    canvas.height = Math.floor(cssHeight * dpr)
    canvas.style.width = `${cssWidth}px`
    canvas.style.height = `${cssHeight}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, cssWidth, cssHeight)

    // 背景
    ctx.fillStyle = 'rgba(0,0,0,0.04)'
    ctx.fillRect(0, 0, cssWidth, cssHeight)

    const usableDuration = Math.max(durationSec, 0.01)
    const xOf = (sec: number) => (sec / usableDuration) * cssWidth

    // 波形柱子
    const mid = cssHeight / 2
    const arr = peaks && peaks.length > 0 ? peaks : null
    if (arr) {
      const barCount = arr.length
      const barWidth = cssWidth / barCount
      ctx.fillStyle = 'rgba(120,120,140,0.6)'
      for (let i = 0; i < barCount; i++) {
        const v = Math.max(0, Math.min(1, arr[i] || 0))
        const h = v * (cssHeight * 0.85)
        const x = i * barWidth
        ctx.fillRect(x, mid - h / 2, Math.max(1, barWidth - 0.5), h)
      }
    } else {
      // 占位：中线
      ctx.strokeStyle = 'rgba(120,120,140,0.6)'
      ctx.beginPath()
      ctx.moveTo(0, mid)
      ctx.lineTo(cssWidth, mid)
      ctx.stroke()
    }

    // 选区高亮
    const selStart = Math.max(0, Math.min(selectionStartSec, usableDuration))
    const selEnd = Math.max(selStart, Math.min(selectionEndSec, usableDuration))
    const xs = xOf(selStart)
    const xe = xOf(selEnd)
    // 选区背景
    ctx.fillStyle = 'rgba(245, 158, 11, 0.18)' // amber-500 18%
    ctx.fillRect(xs, 0, Math.max(1, xe - xs), cssHeight)

    // 选区边缘 fade 渐变（左右两侧）
    if (fadeInSec > 0) {
      const fxs = xOf(selStart)
      const fxe = xOf(Math.min(selStart + fadeInSec, selEnd))
      const grad = ctx.createLinearGradient(fxs, 0, fxe, 0)
      grad.addColorStop(0, 'rgba(245, 158, 11, 0.0)')
      grad.addColorStop(1, 'rgba(245, 158, 11, 0.35)')
      ctx.fillStyle = grad
      ctx.fillRect(fxs, 0, Math.max(1, fxe - fxs), cssHeight)
    }
    if (fadeOutSec > 0) {
      const fxe = xOf(selEnd)
      const fxs = xOf(Math.max(selEnd - fadeOutSec, selStart))
      const grad = ctx.createLinearGradient(fxs, 0, fxe, 0)
      grad.addColorStop(0, 'rgba(245, 158, 11, 0.35)')
      grad.addColorStop(1, 'rgba(245, 158, 11, 0.0)')
      ctx.fillStyle = grad
      ctx.fillRect(fxs, 0, Math.max(1, fxe - fxs), cssHeight)
    }

    // 选区两端竖线
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.95)'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(xs, 0)
    ctx.lineTo(xs, cssHeight)
    ctx.moveTo(xe, 0)
    ctx.lineTo(xe, cssHeight)
    ctx.stroke()

    // 播放游标
    if (typeof playCursorSec === 'number' && playCursorSec >= 0) {
      const cx = xOf(Math.min(playCursorSec, usableDuration))
      ctx.strokeStyle = 'rgba(17, 24, 39, 0.85)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(cx, 0)
      ctx.lineTo(cx, cssHeight)
      ctx.stroke()
    }
  }, [peaks, durationSec, selectionStartSec, selectionEndSec, playCursorSec, height, fadeInSec, fadeOutSec])

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!onPointerDownAt) return
    const rect = (e.currentTarget).getBoundingClientRect()
    const x = e.clientX - rect.left
    const t = (x / rect.width) * Math.max(durationSec, 0.01)
    onPointerDownAt(Math.max(0, Math.min(t, durationSec)))
  }

  return (
    <div ref={containerRef} className="w-full">
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        className="block w-full touch-none cursor-crosshair rounded-md border border-amber-200 dark:border-amber-800"
      />
    </div>
  )
}

export default WaveformCanvas
