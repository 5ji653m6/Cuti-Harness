// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { useDeepAgentWorkspace } from '../src/features/deep-agent-v2/useDeepAgentWorkspace'
import type { DeepAgentEvent, DeepAgentSnapshot } from '../src/features/deep-agent-v2/types'

vi.mock('../src/i18n/LanguageContext', () => ({
  useLanguage: () => ({ language: 'en', t: (key: string) => key }),
}))

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

it('keeps one Session subscription across user turns and automatic Runtime continuation', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  let snapshot: DeepAgentSnapshot = {
    run: { id: 'project', project_id: 'project', thread_id: 'fixed-thread', title: 'Film',
      objective: 'Hello', status: 'completed', current_revision: 0, last_response: '',
      created_at: '2026-09-12T00:00:00Z', updated_at: '2026-09-12T00:00:00Z' },
    tasks: [], artifacts: [], selections: [], messages: [], last_event_sequence: 1,
  }
  let sink: ReadableStreamDefaultController<Uint8Array> | undefined
  let streamSignal: AbortSignal | undefined
  let postSignal: AbortSignal | undefined
  let acceptPost: (() => void) | undefined
  let subscriptions = 0
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (input.includes('/events?')) {
      subscriptions += 1
      streamSignal = options?.signal as AbortSignal
      const body = new ReadableStream<Uint8Array>({ start(controller) {
        sink = controller
        streamSignal?.addEventListener('abort', () => controller.close(), { once: true })
      } })
      return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    }
    if (options?.method === 'POST') {
      expect(JSON.parse(String(options.body)).thread_id).toBe('fixed-thread')
      postSignal = options.signal as AbortSignal
      await new Promise<void>((resolve) => { acceptPost = resolve })
      return Response.json({ code: 0, data: snapshot.run })
    }
    return Response.json({ code: 0, data: input.endsWith('/runs') ? [snapshot.run] : snapshot })
  }))
  let workspace: ReturnType<typeof useDeepAgentWorkspace> | undefined
  const container = document.createElement('div')
  const root = createRoot(container)
  function Conversation() {
    workspace = useDeepAgentWorkspace({ routeThreadId: 'fixed-thread' })
    return createElement('pre', null, workspace.state.messages.map(message => message.content).join('\n'))
  }
  const emit = async (sequence: number, type: string, payload = {}) => {
    const event: DeepAgentEvent = { id: `event-${sequence}`, run_id: 'project', sequence,
      type, payload, created_at: `2026-09-12T00:00:${String(sequence).padStart(2, '0')}Z` }
    await act(async () => { sink!.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)) })
  }
  try {
    await act(async () => { root.render(createElement(Conversation)) })
    expect(subscriptions).toBe(1)
    let sending: Promise<unknown> | undefined
    await act(async () => { sending = workspace!.sendMessage('Continue with the blue fox') })
    await emit(2, 'agent.started')
    await emit(3, 'chat.message.created', { message: { id: 'reply-2', run_id: 'project',
      role: 'assistant', content: 'Using the blue fox reference.', created_at: '2026-09-12T00:00:03Z' } })
    await emit(4, 'run.completed')
    expect(postSignal?.aborted).toBe(false)
    expect(workspace!.state.isSending).toBe(true)
    snapshot = { ...snapshot, last_event_sequence: 4 }
    await act(async () => { acceptPost!(); await sending })
    expect(workspace!.state.isSending).toBe(false)
    expect(streamSignal?.aborted).toBe(false)
    // No browser send: the Runtime checkpoint starts the next Harness turn.
    await emit(5, 'agent.started')
    expect(workspace!.state.snapshot?.run.status).toBe('planning')
    await emit(6, 'chat.message.created', { message: { id: 'reply-3', run_id: 'project',
      role: 'assistant', content: 'The next clip reuses that reference.', created_at: '2026-09-12T00:00:06Z' } })
    await emit(7, 'run.completed')
    expect(subscriptions).toBe(1)
    expect(container.textContent).toContain('Using the blue fox reference.')
    expect(container.textContent).toContain('The next clip reuses that reference.')
  } finally {
    await act(async () => { root.unmount() })
  }
  expect(streamSignal?.aborted).toBe(true)
})
