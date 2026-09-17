import { useEffect, useRef, forwardRef, useCallback } from 'react'
import { hardCleanupVideo } from '@/utils/videoCleanup'

type VideoWithCleanupProps = React.ComponentPropsWithoutRef<'video'>

/**
 * 包装 <video>，在组件卸载时执行 hardCleanupVideo，避免 Detached 节点与显存泄漏。
 * 用于列表、弹窗等会频繁挂载/卸载的 video。
 */
export const VideoWithCleanup = forwardRef<HTMLVideoElement, VideoWithCleanupProps>(
  function VideoWithCleanup(props, ref) {
    const innerRef = useRef<HTMLVideoElement | null>(null)
    const setRef = useCallback(
      (el: HTMLVideoElement | null) => {
        innerRef.current = el
        if (typeof ref === 'function') {
          ref(el)
        } else if (ref) {
          (ref).current = el
        }
      },
      [ref],
    )
    useEffect(() => {
      return () =>{  hardCleanupVideo(innerRef.current) }
    }, [])
    return <video ref={setRef} {...props} />
  },
)
