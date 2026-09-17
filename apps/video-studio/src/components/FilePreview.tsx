import React, { useState, useEffect, useRef } from 'react'
import { X, FileText, Music, Video, Image, Play, Pause, Scissors } from 'lucide-react'
import { hardCleanupVideo } from '@/utils/videoCleanup'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useLanguage } from '@/i18n/LanguageContext'
import type { TranslationKey } from '@/i18n/translations'

const uploadOverlayLabel = (
  t: (key: TranslationKey) => string,
  percent: number,
  phase: 'uploading' | 'saving' | 'ready' | 'error',
): string => {
  if (phase === 'error') return t('da.composer.uploadFailed')
  if (phase === 'saving') return t('da.composer.savingUpload')
  if (phase === 'uploading') return t('da.composer.uploadPercent').replace('{percent}', String(percent))
  return ''
}

function UploadOverlay({
  percent,
  phase,
  label,
}: {
  percent: number
  phase: 'uploading' | 'saving' | 'ready' | 'error'
  label: string
}) {
  if (phase === 'ready') return null
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center overflow-hidden rounded-md bg-black/55">
      <span className="px-0.5 text-center text-[9px] font-medium leading-tight text-white">
        {label}
      </span>
      {phase !== 'error' && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20">
          <div
            className="h-full bg-white transition-[width] duration-150"
            style={{ width: `${Math.max(4, Math.min(100, percent))}%` }}
          />
        </div>
      )}
    </div>
  )
}

interface FilePreviewProps {
  file: File
  index: number
  onRemove?: (index: number) => void
  onCropAudio?: (index: number, file: File) => void
  uploadPercent?: number
  uploadPhase?: 'uploading' | 'saving' | 'ready' | 'error'
}

export const FilePreview: React.FC<FilePreviewProps> = ({
  file,
  index,
  onRemove,
  onCropAudio,
  uploadPercent = 100,
  uploadPhase = 'ready',
}) => {
  const { t } = useLanguage()
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [, setError] = useState<string | null>(null)
  const [audioPlaying, setAudioPlaying] = useState(false)
  const [, setAudioUrlReady] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioUrlRef = useRef<string | null>(null)
  const lastAudioFileRef = useRef<File | null>(null)

  useEffect(() => {
    let cleanup: (() => void) | undefined

    if (file.type.startsWith('image/')) {
      // 图片预览
      const url = URL.createObjectURL(file)
      setPreviewUrl(url)
      cleanup = () =>{  URL.revokeObjectURL(url) }
    } else if (file.type.startsWith('audio/')) {
      if (lastAudioFileRef.current === file && audioUrlRef.current) {
        cleanup = () => {}
      } else {
        if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
        const url = URL.createObjectURL(file)
        audioUrlRef.current = url
        lastAudioFileRef.current = file
        setAudioUrlReady(true)
        cleanup = () => {
          URL.revokeObjectURL(url)
          audioUrlRef.current = null
          lastAudioFileRef.current = null
        }
      }
    } else if (file.type.startsWith('video/')) {
      void extractVideoThumbnail(file)
    }

    return () => {
      if (cleanup) cleanup()
      if (previewUrl && !file.type.startsWith('audio/')) {
        URL.revokeObjectURL(previewUrl)
      }
    }
  }, [file])

  useEffect(() => () => {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = null
    }
    lastAudioFileRef.current = null
  }, [])

  const extractVideoThumbnail = async (videoFile: File) => {
    try {
      const video = document.createElement('video')
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d')

      if (!ctx) {
        setError('Canvas not supported')
        return
      }

      video.preload = 'metadata'
      video.muted = true
      video.crossOrigin = 'anonymous'

      const videoUrl = URL.createObjectURL(videoFile)
      video.src = videoUrl

      // 使用 Promise 包装事件处理
      const extractThumbnail = new Promise<void>((resolve, reject) => {
        let hasResolved = false

        const cleanup = () => {
          URL.revokeObjectURL(videoUrl)
          video.removeEventListener('loadedmetadata', onLoadedMetadata)
          video.removeEventListener('seeked', onSeeked)
          video.removeEventListener('error', onError)
          hardCleanupVideo(video)
        }

        const onLoadedMetadata = () => {
          if (hasResolved) return

          // 设置画布尺寸 - 限制最大尺寸以提高性能
          const maxSize = 200
          const aspectRatio = video.videoWidth / video.videoHeight

          if (video.videoWidth > video.videoHeight) {
            canvas.width = Math.min(maxSize, video.videoWidth)
            canvas.height = canvas.width / aspectRatio
          } else {
            canvas.height = Math.min(maxSize, video.videoHeight)
            canvas.width = canvas.height * aspectRatio
          }

          // 跳转到第一帧（稍微延后一点以确保有内容）
          video.currentTime = Math.min(0.1, video.duration / 10)
        }

        const onSeeked = () => {
          if (hasResolved) return
          hasResolved = true

          try {
            // 绘制当前帧到画布
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

            // 转换为blob URL
            canvas.toBlob((blob) => {
              if (blob) {
                const thumbnailUrl = URL.createObjectURL(blob)
                setPreviewUrl(thumbnailUrl)
              }
              cleanup()
              resolve()
            }, 'image/jpeg', 0.7)

          } catch (err) {
            console.error('Error extracting video thumbnail:', err)
            setError('Failed to extract thumbnail')
            cleanup()
            reject(err instanceof Error ? err : new Error('Failed to extract thumbnail', { cause: err }))
          }
        }

        const onError = (e: Event) => {
          if (hasResolved) return
          hasResolved = true

          console.error('Video loading error:', e)
          setError('Failed to load video')
          cleanup()
          reject(new Error('Video loading failed'))
        }

        video.addEventListener('loadedmetadata', onLoadedMetadata)
        video.addEventListener('seeked', onSeeked)
        video.addEventListener('error', onError)

        // 超时处理
        setTimeout(() => {
          if (!hasResolved) {
            hasResolved = true
            setError('Thumbnail extraction timeout')
            cleanup()
            reject(new Error('Timeout'))
          }
        }, 10000) // 10秒超时
      })

      await extractThumbnail

    } catch (err) {
      console.error('Error creating video thumbnail:', err)
      setError('Failed to create thumbnail')
    }
  }

  const handleAudioClick = () => {
    if (onCropAudio) {
      onCropAudio(index, file)
      return
    }
    const audio = audioRef.current
    if (!audio) return
    if (audioPlaying) {
      audio.pause()
      setAudioPlaying(false)
    } else {
      audio.play().catch(() =>{  setAudioPlaying(false) })
      setAudioPlaying(true)
    }
  }

  const handleAudioEnded = () =>{  setAudioPlaying(false) }

  const getFileIcon = () => {
    if (file.type.startsWith('image/')) {
      return <Image className="w-4 h-4" />
    } else if (file.type.startsWith('video/')) {
      return <Video className="w-4 h-4" />
    } else if (file.type.startsWith('audio/')) {
      return <Music className="w-4 h-4" />
    } else {
      return <FileText className="w-4 h-4" />
    }
  }

  const getDisplayName = (): string => {
    const name = file.name
    const charMatch = name.match(/^character-(.+)\.(png|jpg|jpeg|webp)$/i)
    if (charMatch?.[1]) {
      const id = charMatch[1].toLowerCase()
      const map: Record<string, string> = {
        cuti: 'Cuti', ducky: 'Ducky', hana: 'Hana', jay: 'Jay',
        leo: 'Leo', luna: 'Luna', ruby: 'Ruby', miumiu: 'Mimi',
      }
      return map[id] || id.charAt(0).toUpperCase() + id.slice(1)
    }
    if (name.startsWith('demo-character-')) return 'Character'
    if (name.startsWith('demo-storytelling')) return 'Storytelling'
    if (name.startsWith('demo-song-') || name.includes('Kill This Love')) {
      if (name.includes('lipsync')) return 'Lipsync'
      if (name.includes('kill-this-love') || name.includes('Kill This Love')) return 'Kill This Love'
      return name.replace(/\.(mp3|wav|m4a)$/i, '').replace(/-/g, ' ')
    }
    return name
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="relative flex items-start flex-shrink-0 cursor-default">
          {/* 预览区域 */}
          <div className="flex-shrink-0">
            {previewUrl && (file.type.startsWith('image/') || file.type.startsWith('video/')) ? (
              <div className={`w-12 h-12 rounded-md overflow-hidden bg-black/20 flex items-center justify-center relative ${uploadPhase === 'error' ? 'ring-1 ring-red-500' : ''}`}>
                <img
                  src={previewUrl}
                  alt={file.name}
                  className="w-full h-full object-cover"
                  onError={() =>{  setError('Failed to load preview') }}
                />
                {file.type.startsWith('video/') && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/30 rounded-md">
                    <Video className="w-4 h-4 text-white/90 drop-shadow-sm" />
                  </div>
                )}
                <UploadOverlay percent={uploadPercent} phase={uploadPhase} label={uploadOverlayLabel(t, uploadPercent, uploadPhase)} />
              </div>
            ) : file.type.startsWith('audio/') && audioUrlRef.current ? (
              <div className={`relative w-12 h-12 ${uploadPhase === 'error' ? 'ring-1 ring-red-500 rounded-md' : ''}`}>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); handleAudioClick() }}
                  className="w-12 h-12 rounded-md bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors cursor-pointer"
                  title={onCropAudio ? t('cropAudioTitle') : (audioPlaying ? t('pausePreview') : t('playPreview'))}
                >
                  {onCropAudio ? <Music className="w-5 h-5" /> : (audioPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />)}
                </button>
                <UploadOverlay percent={uploadPercent} phase={uploadPhase} label={uploadOverlayLabel(t, uploadPercent, uploadPhase)} />
              </div>
            ) : (
              <div className={`relative w-12 h-12 rounded-md bg-white/10 flex items-center justify-center ${uploadPhase === 'error' ? 'ring-1 ring-red-500' : ''}`}>
                {getFileIcon()}
                <UploadOverlay percent={uploadPercent} phase={uploadPhase} label={uploadOverlayLabel(t, uploadPercent, uploadPhase)} />
              </div>
            )}
          </div>

          {/* 音频裁剪按钮 */}
          {file.type.startsWith('audio/') && onCropAudio && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCropAudio(index, file)
              }}
              className="absolute -bottom-0.5 -right-0.5 hover:bg-white/20 rounded-full p-0.5 min-w-[20px] min-h-[20px] sm:min-w-0 sm:min-h-0 sm:p-0.5 transition-colors flex-shrink-0 bg-white/10 backdrop-blur-sm flex items-center justify-center"
              title={t('cropAudioTitle')}
            >
              <Scissors className="w-2.5 h-2.5" />
            </button>
          )}

          {/* 删除按钮 */}
          {file.type.startsWith('audio/') && audioUrlRef.current && (
            <audio
              ref={audioRef}
              src={audioUrlRef.current}
              onEnded={handleAudioEnded}
              className="hidden"
            />
          )}
          {onRemove && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onRemove(index)
              }}
              className="absolute -top-0.5 -right-0.5 hover:bg-white/20 rounded-full p-0.5 min-w-[20px] min-h-[20px] sm:min-w-0 sm:min-h-0 sm:p-0.5 transition-colors flex-shrink-0 bg-white/10 backdrop-blur-sm flex items-center justify-center"
              title={t('delete')}
            >
              <X className="w-2.5 h-2.5" />
            </button>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="z-[9999]">
        {uploadPhase === 'error' ? t('da.composer.uploadFailed') : getDisplayName()}
      </TooltipContent>
    </Tooltip>
  )
}
