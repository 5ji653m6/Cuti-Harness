import { displayValue } from '../../utils/displayValue'
import { parseActionSuggestions } from '../../utils/actionSuggestions'
import type {
  DeepAgentEvent,
  DeepAgentMessage,
  DeepAgentNotice,
  DeepAgentRunStatus,
  DeepAgentRunSummary,
  DeepAgentSnapshot,
  DeepAgentSuggestion,
  DeepAgentTask,
  DeepAgentWorkspaceState,
} from './types'
import { buildWaitingInputNotice, waitingInputNoticeFromEvents } from './waitingInputNotice'

function uiIsZh(): boolean {
  try {
    return (localStorage.getItem('language') || 'en') === 'zh'
  } catch {
    return false
  }
}

export const initialDeepAgentState: DeepAgentWorkspaceState = {
  runs: [],
  selectedRunId: null,
  snapshot: null,
  messages: [],
  traceEvents: [],
  suggestions: [],
  lastSequence: 0,
  seenEventIds: [],
  isLoadingRuns: true,
  isHydrating: false,
  isStreaming: false,
  isSending: false,
  notice: null,
}

export type DeepAgentAction =
  | { type: 'RUNS_LOADING' }
  | { type: 'RUNS_LOADED'; runs: DeepAgentRunSummary[] }
  | { type: 'SELECT_RUN'; runId: string | null; lastSequence?: number }
  | { type: 'HYDRATING'; runId: string }
  | {
    type: 'HYDRATE'
    runId: string
    snapshot: DeepAgentSnapshot
    messages: DeepAgentMessage[]
    events: DeepAgentEvent[]
  }
  | { type: 'OPTIMISTIC_MESSAGE'; message: DeepAgentMessage }
  | { type: 'REMOVE_MESSAGE'; messageId: string }
  | { type: 'EVENT'; event: DeepAgentEvent }
  | { type: 'TRACE_EVENTS'; runId: string; events: DeepAgentEvent[] }
  | { type: 'STREAMING'; streaming: boolean }
  | { type: 'SENDING'; sending: boolean }
  | { type: 'NOTICE'; notice: DeepAgentNotice | null }
  | { type: 'STREAM_NOTICE'; notice: DeepAgentNotice | null }

const replaceById = <T extends { id: string }>(items: T[], next: T): T[] => {
  const index = items.findIndex(item => item.id === next.id)
  if (index < 0) return [...items, next]
  const copy = [...items]
  copy[index] = next
  return copy
}

const mergeMessages = (messages: DeepAgentMessage[]): DeepAgentMessage[] => {
  const byId = new Map<string, DeepAgentMessage>()
  messages.forEach(message => byId.set(message.id, message))
  const unique = [...byId.values()].filter((message, _, all) => {
    if (!message.id.startsWith('optimistic-')) return true
    return !all.some(candidate =>
      !candidate.id.startsWith('optimistic-') &&
      (message.run_id === 'pending' || candidate.run_id === message.run_id) &&
      candidate.role === message.role &&
      candidate.content === message.content &&
      candidate.created_at >= message.created_at,
    )
  })
  return unique.sort((a, b) => a.created_at.localeCompare(b.created_at))
}

const isTraceEvent = (event: DeepAgentEvent): boolean =>
  event.type !== 'agent.message.delta'

const mergeTraceEvents = (events: DeepAgentEvent[]): DeepAgentEvent[] => {
  const byId = new Map<string, DeepAgentEvent>()
  events.filter(isTraceEvent).forEach(event => byId.set(event.id, event))
  return [...byId.values()]
    .sort((a, b) => a.sequence - b.sequence)
    .slice(-500)
}

const mergeEntityById = <T extends { id: string; updated_at?: string; created_at?: string }>(
  durable: T[],
  live: T[],
): T[] => {
  const merged = new Map(durable.map(item => [item.id, item]))
  live.forEach((item) => {
    const current = merged.get(item.id)
    const currentTime = current?.updated_at || current?.created_at || ''
    const liveTime = item.updated_at || item.created_at || ''
    if (!current || liveTime > currentTime) merged.set(item.id, item)
  })
  return [...merged.values()]
}

const mergeRuns = (
  durable: DeepAgentRunSummary[],
  live: DeepAgentRunSummary[],
): DeepAgentRunSummary[] => {
  const merged = mergeEntityById(durable, live)
  const liveById = new Map(live.map(item => [item.id, item]))
  return merged.map((run) => {
    const previous = liveById.get(run.id)
    if (previous?.last_response && !run.last_response) {
      return { ...run, last_response: previous.last_response }
    }
    return run
  })
}

const suggestionsFromSnapshot = (snapshot: DeepAgentSnapshot): DeepAgentSuggestion[] => {
  const artifact = [...snapshot.artifacts].reverse().find(
    item => item.type === 'action_suggestions',
  )
  const raw = artifact?.metadata.suggestions
  return parseActionSuggestions(raw)
}

const mergeSelections = (
  durable: DeepAgentSnapshot['selections'],
  live: DeepAgentSnapshot['selections'],
): DeepAgentSnapshot['selections'] => {
  const merged = new Map(durable.map(item => [item.type, item]))
  live.forEach((item) => {
    const current = merged.get(item.type)
    if (!current || item.updated_at > current.updated_at) merged.set(item.type, item)
  })
  return [...merged.values()]
}

const eventRunStatus = (eventType: string): DeepAgentRunStatus | null => {
  const statuses: Record<string, DeepAgentRunStatus> = {
    'run.created': 'planning',
    'agent.started': 'planning',
    'run.waiting_input': 'waiting_input',
    'run.completed': 'completed',
    'run.failed': 'failed',
    'agent.failed': 'failed',
    'run.cancelled': 'cancelled',
  }
  return statuses[eventType] ?? null
}

function applyEvent(state: DeepAgentWorkspaceState, event: DeepAgentEvent): DeepAgentWorkspaceState {
  if (!state.snapshot || state.snapshot.run.id !== event.run_id) return state
  const snapshot: DeepAgentSnapshot = {
    ...state.snapshot,
    run: { ...state.snapshot.run },
    tasks: [...state.snapshot.tasks],
    artifacts: [...state.snapshot.artifacts],
    selections: [...state.snapshot.selections],
    messages: [...state.snapshot.messages],
  }
  let messages = state.messages
  let suggestions = state.suggestions
  let notice = state.notice
  const payload = event.payload

  if (event.type === 'chat.message.created') {
    const message = payload.message as DeepAgentMessage | undefined
    if (message?.id) {
      const withoutStreamCopy = message.role === 'assistant'
        ? messages.filter(item => !item.id.startsWith(`stream-${event.run_id}`))
        : messages
      messages = mergeMessages([...withoutStreamCopy, message])
      snapshot.messages = mergeMessages([...snapshot.messages, message])
      if (message.role === 'user') suggestions = []
    }
  } else if (event.type === 'agent.message.delta') {
    const delta = displayValue(payload.delta ?? payload.content ?? '')
    const messageId = displayValue(payload.message_id ?? `stream-${event.run_id}`)
    const alreadyFinalized = messages.some(message =>
      message.role === 'assistant' &&
      !message.id.startsWith('stream-') &&
      message.created_at >= event.created_at,
    )
    if (alreadyFinalized) return { ...state, snapshot, messages, suggestions }
    const existing = messages.find(message => message.id === messageId)
    const message: DeepAgentMessage = {
      id: messageId,
      run_id: event.run_id,
      role: 'assistant',
      content: `${existing?.content ?? ''}${delta}`,
      created_at: existing?.created_at ?? event.created_at,
    }
    messages = replaceById(messages, message)
  } else if (event.type === 'dialog.action_suggestions.created') {
    const raw = payload.action_suggestions ?? payload.suggestions
    const parsed = parseActionSuggestions(raw) as DeepAgentSuggestion[]
    if (Array.isArray(raw)) {
      suggestions = parsed.map((item, index) => ({
        ...item,
        generation_input:
          typeof raw[index] === 'object' && raw[index] !== null
            ? (raw[index] as Record<string, unknown>).generation_input as Record<string, unknown> | undefined
            : undefined,
      }))
    } else {
      suggestions = parsed
    }
  } else if (event.type === 'plan.revised') {
    const tasks = Array.isArray(payload.tasks) ? payload.tasks as DeepAgentTask[] : []
    tasks.forEach((task) => {
      snapshot.tasks = replaceById(snapshot.tasks, task)
    })
    snapshot.run.current_revision = Number(payload.revision ?? snapshot.run.current_revision)
    snapshot.run.status = payload.waiting_for_input ? 'waiting_input' : 'running'
    const cancelledTaskIds = new Set(
      Array.isArray(payload.cancelled_task_ids) ? payload.cancelled_task_ids.map(String) : [],
    )
    snapshot.tasks = snapshot.tasks.map(task =>
      cancelledTaskIds.has(task.id) ? { ...task, status: 'cancelled' } : task,
    )
  } else if (event.type.startsWith('task.')) {
    const taskId = displayValue(payload.task_id ?? '')
    const index = snapshot.tasks.findIndex(task => task.id === taskId)
    if (index >= 0) {
      const existingTask = snapshot.tasks[index]
      if (!existingTask) return state
      const task = { ...existingTask }
      if (event.type === 'task.started') task.status = 'running'
      if (event.type === 'task.waiting_external') task.status = 'waiting_external'
      if (event.type === 'task.succeeded') task.status = 'succeeded'
      if (event.type === 'task.cancelled') task.status = 'cancelled'
      if (event.type === 'task.failed') {
        task.status = 'failed'
        task.error = displayValue(payload.error ?? '')
        const runStillActive = !['failed', 'cancelled', 'completed'].includes(snapshot.run.status)
        if (runStillActive) {
          notice = {
            severity: 'warning',
            message: task.error
              ? `Generation attempt failed (agent may retry): ${task.error}`
              : 'Generation attempt failed; the agent may retry with a revised plan.',
          }
        }
      }
      if (event.type === 'task.progress') {
        const rawProgress = payload.progress ?? payload.progress_percent ?? payload.percent
        const progress = Number(rawProgress)
        if (Number.isFinite(progress)) task.progress = progress > 1 ? progress : progress * 100
        task.progress_message = displayValue(payload.message ?? payload.status ?? '')
      }
      if (typeof payload.remote_operation_id === 'string') {
        task.remote_operation_id = payload.remote_operation_id
      }
      if (typeof payload.remote_thread_id === 'string') {
        task.remote_thread_id = payload.remote_thread_id
      }
      task.updated_at = event.created_at
      snapshot.tasks[index] = task
    }
  } else if (event.type === 'artifact.created') {
    const artifact = payload.artifact as DeepAgentSnapshot['artifacts'][number] | undefined
    if (artifact?.id) snapshot.artifacts = replaceById(snapshot.artifacts, artifact)
  } else if (event.type === 'artifact.selected') {
    const selection = payload.selection as DeepAgentSnapshot['selections'][number] | undefined
    if (selection?.artifact_version_id) {
      snapshot.selections = [
        ...snapshot.selections.filter(item => item.type !== selection.type),
        selection,
      ]
    }
  }

  const status = eventRunStatus(event.type)
  if (status) snapshot.run.status = status
  if (typeof payload.response === 'string') snapshot.run.last_response = payload.response
  snapshot.run.updated_at = event.created_at
  // Replayed messages may predate a hydrated snapshot. Their content can still
  // be needed, but their turn status must not overwrite the newer projection.
  if (event.sequence <= (state.snapshot.last_event_sequence || 0)) {
    snapshot.run = state.snapshot.run
  }
  snapshot.last_event_sequence = Math.max(state.snapshot.last_event_sequence || 0, event.sequence)

  if (event.type === 'run.failed' || event.type === 'agent.failed') {
    notice = {
      severity: 'error',
      message: displayValue(payload.error || payload.message || 'Run failed'),
    }
  } else if (event.type === 'run.waiting_input' || event.type === 'run.interruption') {
    notice = buildWaitingInputNotice({
      payload: payload,
      lastResponse: typeof payload.response === 'string' ? payload.response : snapshot.run.last_response,
      zh: uiIsZh(),
    })
  } else if (event.type === 'run.completed') {
    if (notice?.severity !== 'error') notice = null
  } else if (event.type === 'task.succeeded' || event.type === 'plan.revised') {
    if (notice?.severity === 'warning' && snapshot.run.status !== 'waiting_input') {
      notice = null
    }
  }

  const runs = state.runs.map(run =>
    run.id === event.run_id
      ? { ...run, status: snapshot.run.status, last_response: snapshot.run.last_response, updated_at: snapshot.run.updated_at }
      : run,
  ).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  return { ...state, snapshot, messages, suggestions, runs, notice }
}

export function deepAgentReducer(
  state: DeepAgentWorkspaceState,
  action: DeepAgentAction,
): DeepAgentWorkspaceState {
  switch (action.type) {
    case 'RUNS_LOADING':
      return { ...state, isLoadingRuns: true, notice: null }
    case 'RUNS_LOADED':
      return {
        ...state,
        runs: mergeRuns(action.runs, state.runs)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
        isLoadingRuns: false,
      }
    case 'SELECT_RUN':
      if (
        action.runId &&
        action.runId === state.selectedRunId &&
        state.snapshot?.run.id === action.runId
      ) {
        return {
          ...state,
          lastSequence: action.lastSequence ?? state.lastSequence,
          notice: null,
        }
      }
      return {
        ...state,
        selectedRunId: action.runId,
        snapshot: null,
        messages: state.messages.filter(message =>
          message.id.startsWith('optimistic-') && message.run_id === 'pending',
        ),
        traceEvents: [],
        suggestions: [],
        lastSequence: action.lastSequence ?? 0,
        seenEventIds: [],
        isHydrating: Boolean(action.runId),
        notice: null,
      }
    case 'HYDRATING':
      if (action.runId !== state.selectedRunId) return state
      return { ...state, isHydrating: true, notice: null }
    case 'HYDRATE':
      if (action.runId !== state.selectedRunId || action.snapshot.run.id !== action.runId) {
        return state
      }
      {
        const liveSnapshot = state.snapshot?.run.id === action.runId ? state.snapshot : null
        const snapshot: DeepAgentSnapshot = liveSnapshot
          ? {
            ...action.snapshot,
            run: (liveSnapshot.last_event_sequence || 0) > (action.snapshot.last_event_sequence || 0)
              ? liveSnapshot.run
              : action.snapshot.run,
            last_event_sequence: Math.max(
              liveSnapshot.last_event_sequence || 0, action.snapshot.last_event_sequence || 0,
            ),
            tasks: mergeEntityById(action.snapshot.tasks, liveSnapshot.tasks),
            artifacts: mergeEntityById(action.snapshot.artifacts, liveSnapshot.artifacts),
            selections: mergeSelections(action.snapshot.selections, liveSnapshot.selections),
            messages: mergeMessages([
              ...action.snapshot.messages,
              ...liveSnapshot.messages,
            ]),
          }
          : action.snapshot
        const messages = mergeMessages([
          ...state.messages.filter(message =>
            message.run_id === action.runId &&
            (message.id.startsWith('optimistic-') || message.id.startsWith('stream-')),
          ),
          ...snapshot.messages,
          ...action.messages,
        ])
        const failureEvent = snapshot.run.status === 'failed'
          ? [...action.events].reverse().find(event =>
            event.run_id === action.runId &&
            (event.type === 'run.failed' || event.type === 'agent.failed'))
          : undefined
        return {
          ...state,
          snapshot,
          messages,
          traceEvents: mergeTraceEvents([
            ...state.traceEvents.filter(event => event.run_id === action.runId),
            ...action.events,
          ]),
          suggestions: suggestionsFromSnapshot(snapshot),
          isHydrating: false,
          notice: snapshot.run.status === 'waiting_input'
            ? (
              waitingInputNoticeFromEvents(
                action.events,
                snapshot.run.last_response,
                uiIsZh(),
              )
                || buildWaitingInputNotice({
                  lastResponse: snapshot.run.last_response,
                  zh: uiIsZh(),
                })
            )
            : failureEvent
              ? { severity: 'error', message: displayValue(failureEvent.payload.error || failureEvent.payload.message || 'Run failed') }
              : state.notice?.severity === 'error'
                ? state.notice
                : null,
        }
      }
    case 'OPTIMISTIC_MESSAGE':
      return {
        ...state,
        messages: mergeMessages([...state.messages, action.message]),
        suggestions: action.message.role === 'user' ? [] : state.suggestions,
      }
    case 'REMOVE_MESSAGE':
      return {
        ...state,
        messages: state.messages.filter(message => message.id !== action.messageId),
      }
    case 'EVENT': {
      if (
        action.event.run_id !== state.selectedRunId ||
        state.seenEventIds.includes(action.event.id)
      ) {
        return state
      }
      const next = applyEvent(state, action.event)
      return {
        ...next,
        traceEvents: mergeTraceEvents([...state.traceEvents, action.event]),
        lastSequence: Math.max(state.lastSequence, action.event.sequence),
        seenEventIds: [...state.seenEventIds, action.event.id].slice(-1000),
      }
    }
    case 'TRACE_EVENTS':
      if (action.runId !== state.selectedRunId) return state
      return {
        ...state,
        traceEvents: mergeTraceEvents([
          ...state.traceEvents.filter(event => event.run_id === action.runId),
          ...action.events,
        ]),
      }
    case 'STREAMING':
      return { ...state, isStreaming: action.streaming }
    case 'SENDING':
      return { ...state, isSending: action.sending }
    case 'STREAM_NOTICE':
      if (state.notice && state.notice.interruptCategory !== 'event-stream') return state
      return { ...state, notice: action.notice }
    case 'NOTICE':
      return action.notice === null
        ? { ...state, notice: null }
        : { ...state, notice: action.notice, isLoadingRuns: false, isHydrating: false }
    default:
      return state
  }
}
