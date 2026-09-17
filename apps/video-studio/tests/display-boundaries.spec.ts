import { afterEach, describe, expect, it, vi } from 'vitest'
import { displayValue } from '../src/utils/displayValue'
import { requestHeaders } from '../src/utils/requestHeaders'
import { getPinnedConversations, getPinnedConversationsData } from '../src/utils/pinnedConversations'
import { splitCollage } from '../src/utils/collageSplitter'

afterEach(() => { vi.unstubAllGlobals() })

describe('frontend data boundaries', () => {
  it('renders structured results without losing scalar values', () => {
    expect(displayValue({ title: '故事', shots: [1, 2] })).toBe('{"title":"故事","shots":[1,2]}')
    expect(displayValue('text')).toBe('text')
    expect(displayValue(0)).toBe('0')
    expect(displayValue(false)).toBe('false')
    expect(displayValue(null)).toBe('null')
  })

  it('merges tuple, object and Headers inputs without dropping request overrides', () => {
    for (const overrides of [new Headers({ 'X-Test': 'override' }), [['X-Test', 'override']], { 'X-Test': 'override' }] as HeadersInit[]) {
      const headers = requestHeaders({ 'X-Test': 'default', 'X-App-Language': 'zh' }, overrides)
      expect(headers.get('x-test')).toBe('override')
      expect(headers.get('x-app-language')).toBe('zh')
      expect(headers.has('0')).toBe(false)
    }
  })

  it('reads legacy pinned IDs and filters malformed entries', () => {
    vi.stubGlobal('localStorage', { getItem: () => '["thread-1",null,12,"thread-2"]' })
    expect(getPinnedConversations()).toEqual(['thread-1', 'thread-2'])
    expect(getPinnedConversationsData()).toEqual([])
  })

  it('retains valid pinned metadata without trusting arbitrary stored objects', () => {
    const valid = { id: 'thread-1', title: '故事', thread_id: 'thread-1', conversation_id: 7, pinnedAt: 1 }
    vi.stubGlobal('localStorage', { getItem: () => JSON.stringify([null, valid, { id: 'invalid' }]) })
    expect(getPinnedConversations()).toEqual(['thread-1'])
    expect(getPinnedConversationsData()).toEqual([valid])
  })
})

describe('canvas export failures', () => {
  const prepareImage = () => {
    vi.stubGlobal('Image', class {
      width = 16
      height = 16
      onload?: () => void
      set src(_value: string) { this.onload?.() }
    })
  }

  it('rejects unavailable rendering contexts', async () => {
    prepareImage()
    vi.stubGlobal('document', { createElement: () => ({ getContext: () => null }) })
    await expect(splitCollage('image.png', { rows: 1, cols: 1 })).rejects.toThrow('Canvas 2D rendering is unavailable')
  })

  it('rejects encoding failure instead of returning a null blob', async () => {
    prepareImage()
    vi.stubGlobal('document', { createElement: () => ({
      getContext: () => ({ drawImage: () => {} }),
      toBlob: (callback: (blob: Blob | null) => void) => { callback(null) },
    }) })
    await expect(splitCollage('image.png', { rows: 1, cols: 1 })).rejects.toThrow('Failed to encode canvas as PNG')
  })
})
