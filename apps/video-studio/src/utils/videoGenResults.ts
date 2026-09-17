export type NormalizedGeneratedVideoItem = {
  index: number
  video_url: string
  cover_image_url?: string | null
}

const VIDEO_URL_RE = /((?:https?:\/\/)[^\s)]+\.(?:mp4|webm|mov)(?:[^\s)]*)?)/gi
const MARKDOWN_VIDEO_RE = /!?\[[^\]]*\]\(([^\s)]+\.(?:mp4|webm|mov)(?:[^\s)]*)?)\)/gi

const firstString = (...values: unknown[]): string | undefined => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return undefined
}

const toRecord = (value: unknown): Record<string, unknown> | null => {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

const pickVideoUrl = (value: unknown): string | undefined => {
  const item = toRecord(value)
  if (!item) return undefined
  return firstString(
    item.video_url,
    item.url,
    item.final_video_url,
    item.latest_final_video_url,
    item.lipsync_video_url,
    item.video,
  )
}

const pickCoverUrl = (value: unknown): string | undefined => {
  const item = toRecord(value)
  if (!item) return undefined
  return firstString(
    item.cover_image_url,
    item.cover_url,
    item.thumbnail_url,
    item.poster,
    item.keyframe_url,
    item.start_image_url,
    item.image_url,
  )
}

function pushVideo(
  out: NormalizedGeneratedVideoItem[],
  seen: Set<string>,
  url: string | undefined,
  coverUrl?: string | null,
): void {
  const normalized = (url || '').trim()
  if (!normalized || seen.has(normalized)) return
  seen.add(normalized)
  out.push({
    index: out.length,
    video_url: normalized,
    cover_image_url: coverUrl || undefined,
  })
}

function extractFromText(
  out: NormalizedGeneratedVideoItem[],
  seen: Set<string>,
  text: unknown,
): void {
  if (typeof text !== 'string' || !text.trim()) return
  let match: RegExpExecArray | null
  MARKDOWN_VIDEO_RE.lastIndex = 0
  while ((match = MARKDOWN_VIDEO_RE.exec(text)) !== null) {
    pushVideo(out, seen, match[1])
  }
  VIDEO_URL_RE.lastIndex = 0
  while ((match = VIDEO_URL_RE.exec(text)) !== null) {
    pushVideo(out, seen, match[1])
  }
}

export function extractGeneratedVideoItems(payload: unknown): NormalizedGeneratedVideoItem[] {
  const out: NormalizedGeneratedVideoItem[] = []
  const seen = new Set<string>()
  const root = toRecord(payload)

  const rawVideos = Array.isArray(payload)
    ? payload
    : Array.isArray(root?.videos)
      ? root.videos
      : []
  for (const item of rawVideos) {
    pushVideo(out, seen, pickVideoUrl(item), pickCoverUrl(item))
  }

  if (root) {
    pushVideo(out, seen, pickVideoUrl(root), pickCoverUrl(root))
  }

  const generations = Array.isArray(root?.video_generations) ? root.video_generations : []
  for (const generation of generations) {
    const gen = toRecord(generation)
    if (!gen) continue
    const versions = Array.isArray(gen.versions) ? gen.versions : []
    const selectedVersion =
      toRecord(gen.selected_version) ||
      toRecord(gen.current_version) ||
      versions
        .map(toRecord)
        .find(version => Boolean(version?.is_selected || version?.selected || version?.is_current)) ||
      toRecord(versions[0])
    pushVideo(
      out,
      seen,
      pickVideoUrl(selectedVersion) || pickVideoUrl(gen),
      pickCoverUrl(selectedVersion) || pickCoverUrl(gen),
    )
  }

  if (root) {
    extractFromText(out, seen, root.video_content)
    extractFromText(out, seen, root.message)
    extractFromText(out, seen, root.content)
  } else {
    extractFromText(out, seen, payload)
  }

  return out
}

export function hasGeneratedVideoResult(payload: unknown): boolean {
  const root = toRecord(payload)
  if (extractGeneratedVideoItems(payload).length > 0) return true
  const count = Number(root?.count ?? root?.total)
  return Number.isFinite(count) && count > 0
}
