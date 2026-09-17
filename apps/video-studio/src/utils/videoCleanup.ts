/**
 * 显存级释放：停止播放、切断媒体源、强制释放解码器缓冲。
 * 仅从 DOM remove 不足以释放显存，必须在卸载时调用此函数。
 */
export function hardCleanupVideo(el: HTMLVideoElement | null | undefined): void {
  if (!el) return
  try {
    el.pause()
  } catch (_) {}
  try {
    // Break media pipeline immediately.
    el.srcObject = null
    el.src = ''
    el.removeAttribute('src')
    const sources = el.querySelectorAll('source')
    sources.forEach((source) => {
      source.removeAttribute('src')
    })
    // Drop inline handlers to avoid retaining closures.
    el.onloadeddata = null
    el.onloadedmetadata = null
    el.oncanplay = null
    el.oncanplaythrough = null
    el.onplay = null
    el.onpause = null
    el.onerror = null
    el.load()
  } catch (_) {}
}
