import { toast } from 'sonner'

// 支持的文件格式（与后端保持一致）
export const SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']
export const SUPPORTED_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.aiff', '.aac', '.ogg', '.flac']
export const SUPPORTED_VIDEO_EXTENSIONS = ['.mp4', '.mpeg', '.mov', '.avi', '.flv', '.mpg', '.webm', '.wmv', '.3gpp']

export const SUPPORTED_IMAGE_MIMETYPES = ['image/png', 'image/jpeg', 'image/webp']
export const SUPPORTED_AUDIO_MIMETYPES = ['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/aiff', 'audio/aac', 'audio/ogg', 'audio/flac']
export const SUPPORTED_VIDEO_MIMETYPES = ['video/mp4', 'video/mpeg', 'video/quicktime', 'video/avi', 'video/x-msvideo', 'video/x-flv', 'video/mpg', 'video/webm', 'video/wmv', 'video/3gpp']

export const MAX_IMAGE_FILE_SIZE = 20 * 1024 * 1024 // 20MB per image
export const MAX_AUDIO_FILE_SIZE = 70 * 1024 * 1024 // 70MB per audio
export const MAX_VIDEO_FILE_SIZE = 2 * 1024 * 1024 * 1024 // 2GB per video

/**
 * 检查文件是否支持
 */
/**
 * 剪贴板里的 File 常无扩展名或仅有通用名；按 MIME 补全扩展名，便于 isFileSupported / validateFiles 识别。
 */
export const normalizeClipboardFile = (file: File): File => {
  if (file.name && isFileSupported(file.name, file.type)) {
    return file
  }
  const mime = (file.type || '').toLowerCase()
  const mimeToExt: Record<string, string> = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/webp': '.webp',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/aiff': '.aiff',
    'audio/aac': '.aac',
    'audio/ogg': '.ogg',
    'audio/flac': '.flac',
    'video/mp4': '.mp4',
    'video/mpeg': '.mpeg',
    'video/quicktime': '.mov',
    'video/avi': '.avi',
    'video/x-msvideo': '.avi',
    'video/x-flv': '.flv',
    'video/mpg': '.mpg',
    'video/webm': '.webm',
    'video/wmv': '.wmv',
    'video/3gpp': '.3gpp',
  }
  const ext = mimeToExt[mime]
  if (!ext) {
    return file
  }
  const raw = file.name || ''
  const dot = raw.lastIndexOf('.')
  const base = dot > 0 ? raw.slice(0, dot) : (raw.trim() || 'pasted')
  return new File([file], `${base}${ext}`, { type: file.type || mime })
}

export const isFileSupported = (filename: string, contentType?: string): boolean => {
  const extension = filename.toLowerCase().substring(filename.lastIndexOf('.'))

  // 检查图片文件
  if (SUPPORTED_IMAGE_EXTENSIONS.includes(extension)) {
    if (!contentType) return true
    return SUPPORTED_IMAGE_MIMETYPES.some(mime => contentType.includes(mime))
  }

  // 检查音频文件
  if (SUPPORTED_AUDIO_EXTENSIONS.includes(extension)) {
    if (!contentType) return true
    return SUPPORTED_AUDIO_MIMETYPES.some(mime => contentType.includes(mime))
  }

  // 检查视频文件
  if (SUPPORTED_VIDEO_EXTENSIONS.includes(extension)) {
    if (!contentType) return true
    return SUPPORTED_VIDEO_MIMETYPES.some(mime => contentType.includes(mime))
  }

  return false
}

/**
 * 获取文件类型
 */
export const getFileType = (filename: string, _contentType?: string): 'image' | 'audio' | 'video' | 'unknown' => {
  const extension = filename.toLowerCase().substring(filename.lastIndexOf('.'))

  if (SUPPORTED_IMAGE_EXTENSIONS.includes(extension)) {
    return 'image'
  }

  if (SUPPORTED_AUDIO_EXTENSIONS.includes(extension)) {
    return 'audio'
  }

  if (SUPPORTED_VIDEO_EXTENSIONS.includes(extension)) {
    return 'video'
  }

  return 'unknown'
}

export const isAudioFile = (file: File): boolean => {
  if ((file.type || '').startsWith('audio/')) {
    return true
  }
  return getFileType(file.name, file.type) === 'audio'
}

/**
 * 验证文件并显示错误消息
 */
export const validateFiles = (
  files: File[],
  existingFiles: File[] = [],
  t: (key: string) => string | undefined,
): { validFiles: File[]; hasErrors: boolean } => {
  const validFiles: File[] = []
  let hasErrors = false

  // 检查文件格式
  for (const file of files) {
    if (!isFileSupported(file.name, file.type)) {
      toast.error(t('unsupportedFileType') || 'Unsupported file format')
      hasErrors = true
      continue
    }
    validFiles.push(file)
  }

  if (validFiles.length === 0) {
    return { validFiles: [], hasErrors: true }
  }

  for (const file of [...existingFiles, ...validFiles]) {
    const kind = getFileType(file.name, file.type)
    const limit =
      kind === 'image' ? MAX_IMAGE_FILE_SIZE
        : kind === 'audio' || file.type.startsWith('audio/') ? MAX_AUDIO_FILE_SIZE
          : kind === 'video' || file.type.startsWith('video/') ? MAX_VIDEO_FILE_SIZE
            : 0
    if (limit > 0 && file.size > limit) {
      const key =
        kind === 'image' ? 'imageFileSizeLimit'
          : kind === 'audio' || file.type.startsWith('audio/') ? 'audioFileSizeLimit'
            : 'videoFileSizeLimit'
      const label =
        kind === 'image' ? '20MB'
          : kind === 'audio' || file.type.startsWith('audio/') ? '70MB'
            : '2GB'
      const message = t(key)?.replace('{{size}}', label)
        || `${kind} file size cannot exceed ${label}`
      toast.error(message)
      return { validFiles: [], hasErrors: true }
    }
  }

  return { validFiles, hasErrors }
}

/**
 * 拖拽上传处理器类
 */
export class DragDropHandler {
  private isDragOver = false
  private onDragOverChange: (isDragOver: boolean) => void
  private onFilesDropped: (files: File[]) => void
  private isDisabled: () => boolean
  private t: (key: string) => string | undefined

  constructor(
    onDragOverChange: (isDragOver: boolean) => void,
    onFilesDropped: (files: File[]) => void,
    isDisabled: () => boolean,
    t: (key: string) => string | undefined,
  ) {
    this.onDragOverChange = onDragOverChange
    this.onFilesDropped = onFilesDropped
    this.isDisabled = isDisabled
    this.t = t
  }

  handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!this.isDragOver && !this.isDisabled()) {
      this.isDragOver = true
      this.onDragOverChange(true)
    }
  }

  handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // 只有当离开整个拖拽区域时才设置为false
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX
    const y = e.clientY
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
      this.isDragOver = false
      this.onDragOverChange(false)
    }
  }

  handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    this.isDragOver = false
    this.onDragOverChange(false)

    if (this.isDisabled()) return

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      // 过滤支持的文件类型
      const supportedFiles = files.filter(file =>
        isFileSupported(file.name, file.type),
      )

      if (supportedFiles.length !== files.length) {
        toast.error(this.t('unsupportedFileType') || 'Some files are not supported')
      }

      if (supportedFiles.length > 0) {
        this.onFilesDropped(supportedFiles)
      }
    }
  }
}

/**
 * 创建拖拽上传处理器
 */
export const createDragDropHandler = (
  onDragOverChange: (isDragOver: boolean) => void,
  onFilesDropped: (files: File[]) => void,
  isDisabled: () => boolean,
  t: (key: string) => string | undefined,
) => {
  return new DragDropHandler(onDragOverChange, onFilesDropped, isDisabled, t)
}
