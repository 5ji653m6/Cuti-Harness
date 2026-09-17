import { describe, expect, it } from 'vitest'

import { deepAgentReducer, initialDeepAgentState } from '../src/features/deep-agent-v2/reducer'
import { DeepAgentApiError, isStoppedResumeRequired } from '../src/features/deep-agent-v2/client'

const terminalSnapshot = (status: 'completed' | 'failed' | 'cancelled') => ({
  run: {
    id: 'project-1',
    project_id: 'project-1',
    thread_id: 'thread-1',
    status,
    updated_at: '2026-09-08T00:00:00Z',
  },
  tasks: [],
  artifacts: [],
  selections: [],
  messages: [],
  last_event_sequence: 1,
})

describe('Deep Agent terminal send state', () => {
  it('restores the provider credit error when opening a failed session', () => {
    const error = 'You have no credits remaining.'
    const next = deepAgentReducer({ ...initialDeepAgentState, selectedRunId: 'project-1' }, {
      type: 'HYDRATE', runId: 'project-1', snapshot: terminalSnapshot('failed') as never,
      messages: [], events: [{ id: 'failure', run_id: 'project-1', sequence: 1,
        type: 'run.failed', payload: { error }, created_at: '2026-09-14T00:00:00Z' }],
    })
    expect(next.notice).toEqual({ severity: 'error', message: error })
    expect(deepAgentReducer(next, { type: 'STREAM_NOTICE', notice: null }).notice).toEqual(next.notice)
    expect(deepAgentReducer(next, { type: 'STREAM_NOTICE', notice: {
      severity: 'warning', message: 'Reconnecting', interruptCategory: 'event-stream',
    } }).notice).toEqual(next.notice)
  })
  it('clears only the connection warning after reconnecting', () => {
    const disconnected = deepAgentReducer(initialDeepAgentState, { type: 'STREAM_NOTICE',
      notice: { severity: 'warning', message: 'Reconnecting', interruptCategory: 'event-stream' },
    })
    expect(deepAgentReducer(disconnected, { type: 'STREAM_NOTICE', notice: null }).notice).toBeNull()
  })
  it.each(['completed', 'failed', 'cancelled'] as const)(
    'keeps the current POST lock when a previous turn snapshot is %s',
    (status) => {
      const state = {
        ...initialDeepAgentState,
        selectedRunId: 'project-1',
        isSending: true,
      }

      const next = deepAgentReducer(state, {
        type: 'HYDRATE',
        runId: 'project-1',
        snapshot: terminalSnapshot(status) as never,
        messages: [],
        events: [],
      })

      expect(next.snapshot?.run.status).toBe(status)
      expect(next.isSending).toBe(true)
    },
  )

  it('accepts a newer turn by sequence despite an older project timestamp', () => {
    const initial = terminalSnapshot('completed')
    initial.run.updated_at = '2026-09-12T00:00:00Z'
    const next = deepAgentReducer({
      ...initialDeepAgentState, selectedRunId: 'project-1', snapshot: initial as never,
    }, {
      type: 'HYDRATE', runId: 'project-1', messages: [], events: [],
      snapshot: {
        ...terminalSnapshot('completed'),
        run: { ...terminalSnapshot('completed').run, status: 'running' },
        last_event_sequence: 2,
      } as never,
    })
    expect(next.snapshot?.run.status).toBe('running')
    expect(next.snapshot?.last_event_sequence).toBe(2)
    const replayed = deepAgentReducer(next, {
      type: 'EVENT', event: {
        id: 'old-end', run_id: 'project-1', sequence: 1, type: 'run.completed',
        payload: {}, created_at: '2026-09-12T00:00:00Z',
      },
    })
    expect(replayed.snapshot?.run.status).toBe('running')
    const stale = deepAgentReducer(replayed, {
      type: 'HYDRATE', runId: 'project-1', messages: [], events: [], snapshot: initial as never,
    })
    expect(stale.snapshot?.run.status).toBe('running')
    expect(stale.snapshot?.last_event_sequence).toBe(2)
  })

  it('recognizes the authoritative stopped-build conflict for resume fallback', () => {
    expect(isStoppedResumeRequired(new DeepAgentApiError(
      409,
      'Task stopped. Confirm resume before sending a continuation.',
      'task_stopped_resume_required',
    ))).toBe(true)
  })

  it('does not treat unrelated conflicts as a stopped-build resume request', () => {
    expect(isStoppedResumeRequired(new DeepAgentApiError(409, 'Project version conflict'))).toBe(false)
    expect(isStoppedResumeRequired(new DeepAgentApiError(422, 'Task stopped. Confirm resume before sending a continuation.'))).toBe(false)
  })
})
