import { displayValue } from './displayValue'
export type ActionSuggestionItem = {
  label: string
  message: string
  is_direct_generate?: boolean
}

export const ACTION_SUGGESTIONS_START = '<<<ACTION_SUGGESTIONS_START>>>'
export const ACTION_SUGGESTIONS_END = '<<<ACTION_SUGGESTIONS_END>>>'
export const ACTION_SUGGESTIONS_JSON_MARKER = '<<<ACTION_SUGGESTIONS_JSON>>>'

function markerHoldbackSuffixLen(text: string, marker: string): number {
  let maxHold = 0
  for (let i = 1; i < marker.length; i += 1) {
    if (text.endsWith(marker.slice(0, i))) {
      maxHold = i
    }
  }
  return maxHold
}

/** 从聊天正文中移除推荐动作块（含 START/END 与历史 JSON marker）。 */
export function stripActionSuggestionsFromChatContent(text: string): string {
  let out = (text)
  for (const marker of [ACTION_SUGGESTIONS_START, ACTION_SUGGESTIONS_JSON_MARKER]) {
    const idx = out.indexOf(marker)
    if (idx >= 0) {
      out = out.slice(0, idx)
    }
  }
  return out
}

/** 流式聊天可见区：见到 START 后不再向气泡追加内容。 */
export class ChatVisibleStreamAccumulator {
  private pending = ''
  private pastStart = false
  private visible = ''

  reset(): void {
    this.pending = ''
    this.pastStart = false
    this.visible = ''
  }

  hasPassedStart(): boolean {
    return this.pastStart
  }

  feed(chunk: string): string {
    if (!chunk || this.pastStart) {
      return ''
    }
    this.pending += chunk

    for (const marker of [ACTION_SUGGESTIONS_START, ACTION_SUGGESTIONS_JSON_MARKER]) {
      const startIdx = this.pending.indexOf(marker)
      if (startIdx >= 0) {
        const before = this.pending.slice(0, startIdx)
        this.pastStart = true
        this.pending = ''
        this.visible += before
        return before
      }
    }

    const hold = Math.max(
      markerHoldbackSuffixLen(this.pending, ACTION_SUGGESTIONS_START),
      markerHoldbackSuffixLen(this.pending, ACTION_SUGGESTIONS_JSON_MARKER),
    )
    const emitPart = hold > 0 ? this.pending.slice(0, -hold) : this.pending
    this.pending = hold > 0 ? this.pending.slice(-hold) : ''
    if (emitPart) {
      this.visible += emitPart
    }
    return emitPart
  }

  getVisibleText(): string {
    return stripActionSuggestionsFromChatContent(
      this.visible + (this.pastStart ? '' : this.pending),
    )
  }
}

const chatVisibleAccumulators = new Map<string, ChatVisibleStreamAccumulator>()

export function resetChatVisibleStreamAccumulator(chatKey: string): void {
  chatVisibleAccumulators.delete(chatKey)
}

export function getChatVisibleStreamAccumulator(chatKey: string): ChatVisibleStreamAccumulator {
  let acc = chatVisibleAccumulators.get(chatKey)
  if (!acc) {
    acc = new ChatVisibleStreamAccumulator()
    chatVisibleAccumulators.set(chatKey, acc)
  }
  return acc
}

const DIRECT_GENERATE_LABELS = new Set([
  '直接生成',
  '直接开始生成',
  '开始生成',
  'generate directly',
  'start generating',
  'generate now',
])

export const isDirectGenerateAction = (item: Pick<ActionSuggestionItem, 'label' | 'message' | 'is_direct_generate'>): boolean => {
  if (item.is_direct_generate) return true
  const label = (item.label).trim().toLowerCase()
  const message = (item.message).trim().toLowerCase()
  return DIRECT_GENERATE_LABELS.has(label) || DIRECT_GENERATE_LABELS.has(message)
}

export const isPaymentTopUpAction = (item: Pick<ActionSuggestionItem, 'label' | 'message'>): boolean => {
  const label = (item.label).trim().toLowerCase()
  const message = (item.message).trim().toLowerCase()
  return (
    label === '去升级'
    || message === '去升级'
    || label === '去充值'
    || message === '去充值'
    || label === 'upgrade'
    || message === 'upgrade'
    || label === 'top up'
    || message === 'top up'
  )
}

/** 解析 START/END 之间的格式化推荐动作（choice|open + label|message 行）。 */
export const parseFormattedActionSuggestionsText = (raw: string): ActionSuggestionItem[] => {
  const body = (raw).trim()
  if (!body) return []

  const lines = body.split(/\r?\n/).map(ln => ln.trim()).filter(Boolean)
  if (!lines.length) return []

  let startIdx = 0
  const first = lines[0]?.toLowerCase()
  if (first === 'choice' || first === 'open') {
    startIdx = 1
  }

  const items: ActionSuggestionItem[] = []
  for (let i = startIdx; i < lines.length; i += 1) {
    const line = lines[i]
    if (!line) continue
    if (line.startsWith('#')) continue
    let label: string
    let message: string
    if (line.includes('|')) {
      const pipe = line.indexOf('|')
      label = line.slice(0, pipe).trim()
      message = line.slice(pipe + 1).trim()
    } else {
      label = line
      message = line
    }
    if (!label && !message) continue
    if (!label) label = message.slice(0, 15)
    if (!message) message = label
    const item: ActionSuggestionItem = {
      label,
      message,
      is_direct_generate: false,
    }
    if (isDirectGenerateAction(item)) {
      item.is_direct_generate = true
    }
    items.push(item)
  }
  return items
}

/** 流式累积：见到 START 开始记录，见到 END 后一次性解析。 */
export class ActionSuggestionsStreamAccumulator {
  private body = ''
  private recording = false
  private ended = false

  reset(): void {
    this.body = ''
    this.recording = false
    this.ended = false
  }

  onSuggestionsPhase(phase: 'start' | 'end'): void {
    if (phase === 'start') {
      this.body = ''
      this.recording = true
      this.ended = false
      return
    }
    this.ended = true
    this.recording = false
  }

  appendChunk(chunk: string): void {
    if (!chunk) return
    if (!this.recording && !this.ended) {
      const startIdx = chunk.indexOf(ACTION_SUGGESTIONS_START)
      if (startIdx < 0) return
      this.recording = true
      chunk = chunk.slice(startIdx + ACTION_SUGGESTIONS_START.length)
    }
    if (!this.recording || this.ended) return

    const endIdx = chunk.indexOf(ACTION_SUGGESTIONS_END)
    if (endIdx >= 0) {
      this.body += chunk.slice(0, endIdx)
      this.ended = true
      this.recording = false
      return
    }
    this.body += chunk
  }

  getParsedIfReady(): ActionSuggestionItem[] | null {
    if (!this.ended && !this.body) return null
    const parsed = parseFormattedActionSuggestionsText(this.body)
    return parsed.length > 0 ? parsed : null
  }

  isEnded(): boolean {
    return this.ended
  }
}

export const parseActionSuggestions = (raw: unknown): ActionSuggestionItem[] => {
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.includes('|') || /^(choice|open)\b/i.test(trimmed)) {
      return parseFormattedActionSuggestionsText(trimmed)
    }
  }
  if (!Array.isArray(raw)) return []
  const items: ActionSuggestionItem[] = []
  for (const entry of raw) {
    if (typeof entry === 'string') {
      const text = entry.trim()
      if (!text) continue
      const item: ActionSuggestionItem = { label: text, message: text }
      item.is_direct_generate = isDirectGenerateAction(item)
      items.push(item)
      continue
    }
    if (!entry || typeof entry !== 'object') continue
    const o = entry as Record<string, unknown>
    const label = displayValue(o.label ?? '').trim()
    const message = displayValue(o.message ?? label).trim()
    if (!label && !message) continue
    const item: ActionSuggestionItem = {
      label: label || message,
      message: message || label,
      is_direct_generate: Boolean(o.is_direct_generate),
    }
    if (isDirectGenerateAction(item)) {
      item.is_direct_generate = true
    }
    items.push(item)
  }
  return items
}

export const getStreamEventContentType = (event: Record<string, unknown>): string =>
  displayValue(event.content_type ?? (event.event_data as Record<string, unknown> | undefined)?.content_type ?? 'text')

export const getStreamEventSuggestionsPhase = (event: Record<string, unknown>): string | undefined => {
  const phase = event.suggestions_phase ?? (event.event_data as Record<string, unknown> | undefined)?.suggestions_phase
  return phase != null ? displayValue(phase) : undefined
}
