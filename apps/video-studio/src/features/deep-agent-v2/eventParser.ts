import type { DeepAgentEvent } from './types'

export interface ParsedSseFrame {
  id?: string
  event?: string
  data: string
}

export class DeepAgentSseParser {
  private buffer = ''

  feed(chunk: string): ParsedSseFrame[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const frames: ParsedSseFrame[] = []
    let boundary = this.buffer.indexOf('\n\n')

    while (boundary >= 0) {
      const raw = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      const frame = parseFrame(raw)
      if (frame) frames.push(frame)
      boundary = this.buffer.indexOf('\n\n')
    }
    return frames
  }
}

function parseFrame(raw: string): ParsedSseFrame | null {
  if (!raw || raw.startsWith(':')) return null
  const result: ParsedSseFrame = { data: '' }
  const data: string[] = []
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'id') result.id = value
    if (field === 'event') result.event = value
    if (field === 'data') data.push(value)
  }
  result.data = data.join('\n')
  return result.data ? result : null
}

export function parseDeepAgentEvent(frame: ParsedSseFrame): DeepAgentEvent | null {
  try {
    const event = JSON.parse(frame.data) as DeepAgentEvent
    if (!event.id || !event.run_id || !Number.isFinite(event.sequence) || !event.type) return null
    return event
  } catch {
    return null
  }
}

export async function replayDeepAgentEvents(
  response: Response,
  onEvent: (event: DeepAgentEvent) => void,
): Promise<void> {
  if (!response.ok || !response.body) {
    throw new Error(`Deep Agent event stream failed (${response.status})`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new DeepAgentSseParser()
  while (true) {
    const { done, value } = await reader.read()
    const frames = parser.feed(decoder.decode(value, { stream: !done }))
    for (const frame of frames) {
      const event = parseDeepAgentEvent(frame)
      if (event) onEvent(event)
    }
    if (done) break
  }
}
