import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { createIdempotencyKey, deepAgentV2Client, isStoppedResumeRequired } from './client'
import { replayDeepAgentEvents } from './eventParser'
import { runtimeMessage } from './labels'
import { deepAgentReducer, initialDeepAgentState } from './reducer'
import type {
  DeepAgentEvent,
  DeepAgentMessage,
  DeepAgentMessageOptions,
  DeepAgentSuggestion,
} from './types'
import { useLanguage } from '../../i18n/LanguageContext'

const SELECTED_RUN_KEY = 'cuti.deep-agent-v2.selected-run'
const sequenceKey = (runId: string) => `cuti.deep-agent-v2.sequence.${runId}`
const threadKey = (runId: string) => `cuti.deep-agent-v2.thread.${runId}`

const readSequence = (runId: string): number => {
  const value = Number(localStorage.getItem(sequenceKey(runId)) || '0')
  return Number.isFinite(value) && value > 0 ? value : 0
}

const persistThreadId = (runId: string, threadId?: string | null) => {
  const normalized = (threadId || '').trim()
  if (!runId || !normalized) return
  localStorage.setItem(threadKey(runId), normalized)
}

const readThreadId = (runId?: string | null): string | undefined => {
  if (!runId) return undefined
  const stored = (localStorage.getItem(threadKey(runId)) || '').trim()
  return stored || undefined
}

/** Stable 32-char hex id — matches backend default thread_id shape. */
export const createThreadId = (): string =>
  createIdempotencyKey().replace(/-/g, '').slice(0, 32)

export function useDeepAgentWorkspace({
  autoSelect = true,
  routeThreadId = null,
}: {
  autoSelect?: boolean
  /** Thread id from the URL (`/create/:threadId`). */
  routeThreadId?: string | null
} = {}) {
  const { language, t } = useLanguage()
  const languageRef = useRef(language)
  const tRef = useRef(t)
  const [state, dispatch] = useReducer(deepAgentReducer, initialDeepAgentState)
  const [pendingThreadId, setPendingThreadId] = useState<string | null>(
    () => (routeThreadId || '').trim() || null,
  )
  const cursorRef = useRef(0)
  const autoSelectRef = useRef(autoSelect)
  const routeThreadIdRef = useRef((routeThreadId || '').trim() || null)
  const awaitingRouteThreadIdRef = useRef<string | null>(null)
  const pendingThreadIdRef = useRef(pendingThreadId)
  const selectedRunIdRef = useRef<string | null>(null)
  const selectionVersionRef = useRef(0)
  const sendingRef = useRef(false)
  const sendControllerRef = useRef<AbortController | null>(null)
  const listControllerRef = useRef<AbortController | null>(null)
  const hydrateControllerRef = useRef<AbortController | null>(null)
  autoSelectRef.current = autoSelect
  languageRef.current = language
  tRef.current = t
  pendingThreadIdRef.current = pendingThreadId
  selectedRunIdRef.current = state.selectedRunId

  const loadRuns = useCallback(async (preferredRunId?: string | null) => {
    listControllerRef.current?.abort()
    const controller = new AbortController()
    listControllerRef.current = controller
    const selectionVersion = selectionVersionRef.current
    dispatch({ type: 'RUNS_LOADING' })
    try {
      const runs = await deepAgentV2Client.listRuns(controller.signal)
      if (controller.signal.aborted) return
      runs.forEach((run) =>{  persistThreadId(run.id, run.thread_id) })
      dispatch({ type: 'RUNS_LOADED', runs })
      if (selectionVersion !== selectionVersionRef.current) return

      const routeThread = routeThreadIdRef.current
      if (routeThread) {
        const byThread = runs.find(run => run.thread_id === routeThread)
        if (byThread) {
          setPendingThreadId(null)
          localStorage.setItem(SELECTED_RUN_KEY, byThread.id)
          dispatch({
            type: 'SELECT_RUN',
            runId: byThread.id,
            lastSequence: readSequence(byThread.id),
          })
          return
        }
        // Draft conversation for this URL thread — do not auto-pick another run.
        pendingThreadIdRef.current = routeThread
        setPendingThreadId(routeThread)
        localStorage.removeItem(SELECTED_RUN_KEY)
        dispatch({ type: 'SELECT_RUN', runId: null })
        return
      }

      // A locally-created draft may exist just before React Router propagates
      // its thread id. Never let a concurrent list refresh replace that draft.
      if (pendingThreadIdRef.current) return
      if (!autoSelectRef.current && preferredRunId === undefined) return
      const stored = preferredRunId ?? localStorage.getItem(SELECTED_RUN_KEY)
      const selected = runs.some(run => run.id === stored) ? stored : runs[0]?.id
      if (selected) {
        localStorage.setItem(SELECTED_RUN_KEY, selected)
        dispatch({ type: 'SELECT_RUN', runId: selected, lastSequence: readSequence(selected) })
      }
    } catch (_error) {
      if (controller.signal.aborted) return
      dispatch({ type: 'NOTICE', notice: { severity: 'error', message: tRef.current('da.runtime.requestFailedGeneric') } })
    }
  }, [])

  const hydrateRun = useCallback(async (runId: string) => {
    hydrateControllerRef.current?.abort()
    const controller = new AbortController()
    hydrateControllerRef.current = controller
    dispatch({ type: 'HYDRATING', runId })
    try {
      const snapshot = await deepAgentV2Client.getRun(runId, controller.signal)
      if (controller.signal.aborted || selectedRunIdRef.current !== runId) return
      persistThreadId(runId, snapshot.run.thread_id)
      setPendingThreadId(null)
      const snapshotIsTerminal = ['waiting_input', 'completed', 'failed', 'cancelled']
        .includes(snapshot.run.status)
      const hydratedSequence = snapshotIsTerminal
        ? Math.max(readSequence(runId), snapshot.last_event_sequence || 0)
        : readSequence(runId)
      cursorRef.current = hydratedSequence
      localStorage.setItem(sequenceKey(runId), String(hydratedSequence))
      dispatch({
        type: 'HYDRATE',
        runId,
        snapshot,
        messages: snapshot.messages,
        events: snapshot.events ?? [],
      })
    } catch (_error) {
      if (controller.signal.aborted) return
      dispatch({ type: 'NOTICE', notice: { severity: 'error', message: tRef.current('da.runtime.requestFailedGeneric') } })
    }
  }, [])

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  // When the URL thread changes (back/forward or pasted link), re-resolve selection.
  useEffect(() => {
    const next = (routeThreadId || '').trim() || null
    const awaiting = awaitingRouteThreadIdRef.current
    if (awaiting && next !== awaiting) return
    if (awaiting === next) awaitingRouteThreadIdRef.current = null
    routeThreadIdRef.current = next
    if (!next) return
    const match = state.runs.find(run => run.thread_id === next)
    if (match) {
      if (selectedRunIdRef.current !== match.id) {
        selectionVersionRef.current += 1
        hydrateControllerRef.current?.abort()
        setPendingThreadId(null)
        localStorage.setItem(SELECTED_RUN_KEY, match.id)
        dispatch({ type: 'SELECT_RUN', runId: match.id, lastSequence: readSequence(match.id) })
      }
      return
    }
    if (state.isLoadingRuns) return
    if (selectedRunIdRef.current !== null || pendingThreadId !== next) {
      selectionVersionRef.current += 1
      hydrateControllerRef.current?.abort()
      setPendingThreadId(next)
      localStorage.removeItem(SELECTED_RUN_KEY)
      dispatch({ type: 'SELECT_RUN', runId: null })
    }
  }, [pendingThreadId, routeThreadId, state.isLoadingRuns, state.runs])

  useEffect(() => {
    if (state.selectedRunId) void hydrateRun(state.selectedRunId)
  }, [hydrateRun, state.selectedRunId])

  useEffect(() => () => {
    listControllerRef.current?.abort()
    hydrateControllerRef.current?.abort()
    sendControllerRef.current?.abort()
  }, [])

  const streamReady = Boolean(
    state.selectedRunId && state.snapshot?.run.id === state.selectedRunId,
  )
  // A turn ending does not close the Session: user follow-ups and Runtime
  // checkpoints can start another turn without a browser POST.
  const shouldStream = streamReady

  useEffect(() => {
    const runId = state.selectedRunId
    if (!runId || !shouldStream) return
    const controller = new AbortController()
    cursorRef.current = readSequence(runId)
    let stopped = false
    const isAborted = () => controller.signal.aborted

    const connect = async () => {
      dispatch({ type: 'STREAMING', streaming: true })
      while (!stopped && !controller.signal.aborted) {
        try {
          const response = await fetch(deepAgentV2Client.eventsUrl(runId, cursorRef.current), {
            credentials: 'include',
            headers: { 'X-App-Language': languageRef.current },
            signal: controller.signal,
          })
          if (response.ok) dispatch({ type: 'STREAM_NOTICE', notice: null })
          await replayDeepAgentEvents(response, (event: DeepAgentEvent) => {
            cursorRef.current = Math.max(cursorRef.current, event.sequence)
            localStorage.setItem(sequenceKey(runId), String(cursorRef.current))
            dispatch({ type: 'EVENT', event })
          })
        } catch (_error) {
          if (isAborted()) break
          dispatch({
            type: 'STREAM_NOTICE',
            notice: {
              severity: 'warning',
              interruptCategory: 'event-stream',
              message: languageRef.current === 'zh'
                ? '事件连接中断，正在重新连接……'
                : 'Event stream interrupted, reconnecting…',
            },
          })
        }
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      if (!stopped) dispatch({ type: 'STREAMING', streaming: false })
    }
    void connect()
    return () => {
      stopped = true
      controller.abort()
      dispatch({ type: 'STREAMING', streaming: false })
    }
  }, [state.selectedRunId, shouldStream])

  const selectRun = useCallback((runId: string) => {
    if (selectedRunIdRef.current === runId) return
    selectionVersionRef.current += 1
    hydrateControllerRef.current?.abort()
    setPendingThreadId(null)
    localStorage.setItem(SELECTED_RUN_KEY, runId)
    dispatch({ type: 'SELECT_RUN', runId, lastSequence: readSequence(runId) })
  }, [])

  const newSession = useCallback((threadId?: string) => {
    const nextThreadId = (threadId || createThreadId()).trim()
    selectionVersionRef.current += 1
    hydrateControllerRef.current?.abort()
    localStorage.removeItem(SELECTED_RUN_KEY)
    // Update all synchronous selection refs before React Router propagates
    // the new URL. Otherwise a render with the old route can restore the
    // previously selected run and make the New conversation click look inert.
    awaitingRouteThreadIdRef.current = nextThreadId
    routeThreadIdRef.current = nextThreadId
    pendingThreadIdRef.current = nextThreadId
    selectedRunIdRef.current = null
    setPendingThreadId(nextThreadId)
    dispatch({ type: 'SELECT_RUN', runId: null })
    return nextThreadId
  }, [])

  const resolveSessionThreadId = useCallback((runId?: string | null): string | undefined => {
    if (!runId) {
      return (pendingThreadId || routeThreadIdRef.current || '').trim() || undefined
    }
    const fromSnapshot = state.snapshot?.run.id === runId
      ? state.snapshot.run.thread_id
      : undefined
    const fromRuns = state.runs.find(run => run.id === runId)?.thread_id
    return (fromSnapshot || fromRuns || readThreadId(runId) || pendingThreadId || '').trim() || undefined
  }, [pendingThreadId, state.runs, state.snapshot])

  const sendMessage = useCallback(async (
    content: string,
    options: DeepAgentMessageOptions = {},
  ) => {
    const normalized = content.trim()
    if (!normalized || sendingRef.current) return undefined
    const controller = new AbortController()
    sendControllerRef.current?.abort()
    sendControllerRef.current = controller
    sendingRef.current = true
    dispatch({ type: 'SENDING', sending: true })
    dispatch({ type: 'NOTICE', notice: null })
    const optimisticId = `optimistic-user-${createIdempotencyKey()}`
    const optimisticMessage: DeepAgentMessage = {
      id: optimisticId,
      run_id: state.selectedRunId || 'pending',
      role: 'user',
      content: normalized,
      created_at: new Date().toISOString(),
    }
    dispatch({ type: 'OPTIMISTIC_MESSAGE', message: optimisticMessage })
    try {
      if (!state.selectedRunId) {
        const threadId = (
          options.thread_id
          || pendingThreadId
          || routeThreadIdRef.current
          || createThreadId()
        ).trim()
        const run = await deepAgentV2Client.createRun(normalized, threadId, {
          ...options,
          thread_id: threadId,
        }, controller.signal)
        persistThreadId(run.id, run.thread_id || threadId)
        setPendingThreadId(null)
        selectionVersionRef.current += 1
        localStorage.setItem(SELECTED_RUN_KEY, run.id)
        dispatch({ type: 'SELECT_RUN', runId: run.id, lastSequence: 0 })
        dispatch({ type: 'RUNS_LOADED', runs: await deepAgentV2Client.listRuns() })
        return run
      }
      const threadId = options.thread_id || resolveSessionThreadId(state.selectedRunId)
      const payload: DeepAgentMessageOptions = {
        ...options,
        ...(threadId ? { thread_id: threadId } : {}),
      }
      const stopped = state.snapshot?.run.status === 'cancelled'
      const resumeMessage = language === 'zh'
        ? '任务已停止。确认恢复并发送这条消息？已完成素材会保留；已提交的外部生成可能仍在运行，恢复时会先查询原任务。'
        : 'This task is stopped. Resume it and send this message? Completed media will be preserved, and submitted provider jobs will be reconciled before retrying.'
      const confirmResume = () => window.confirm(resumeMessage)
      if (stopped && !confirmResume()) {
        dispatch({ type: 'REMOVE_MESSAGE', messageId: optimisticId })
        return
      }
      let run
      if (stopped) {
        run = await deepAgentV2Client.resumeRun(
          state.selectedRunId,
          normalized,
          payload,
          controller.signal,
        )
      } else {
        try {
          run = await deepAgentV2Client.sendMessage(
            state.selectedRunId,
            normalized,
            payload,
            controller.signal,
          )
        } catch (error) {
          // Runtime build state is authoritative. If the page held a stale
          // non-cancelled snapshot, offer the same recovery path and retry the
          // user's message exactly once through /resume.
          if (!isStoppedResumeRequired(error)) throw error
          if (!confirmResume()) {
            dispatch({ type: 'REMOVE_MESSAGE', messageId: optimisticId })
            return
          }
          run = await deepAgentV2Client.resumeRun(
            state.selectedRunId,
            normalized,
            payload,
            controller.signal,
          )
        }
      }
      persistThreadId(state.selectedRunId, run.thread_id || threadId)
      await hydrateRun(state.selectedRunId)
      return run
    } catch (error) {
      dispatch({ type: 'REMOVE_MESSAGE', messageId: optimisticId })
      if (error instanceof DOMException && error.name === 'AbortError') return undefined
      dispatch({ type: 'NOTICE', notice: { severity: 'error', message: error instanceof Error && error.message ? runtimeMessage(error.message, t) : t('da.runtime.requestFailedGeneric') } })
      throw error
    } finally {
      // An aborted older request may unwind after a resumed message already
      // started. Only its own controller may release the current send lock.
      if (sendControllerRef.current === controller) {
        sendControllerRef.current = null
        sendingRef.current = false
        dispatch({ type: 'SENDING', sending: false })
      }
    }
  }, [hydrateRun, language, pendingThreadId, resolveSessionThreadId, state.selectedRunId, state.snapshot?.run.status, t])

  const sendSuggestion = useCallback(async (
    suggestion: DeepAgentSuggestion,
    options: DeepAgentMessageOptions = {},
  ) => {
    let content = suggestion.message || suggestion.label
    const threadId = options.thread_id || resolveSessionThreadId(state.selectedRunId)
    const generationInput = suggestion.is_direct_generate && suggestion.generation_input
      ? {
        ...suggestion.generation_input,
        ...(threadId ? { thread_id: threadId } : {}),
      }
      : suggestion.generation_input
    if (suggestion.is_direct_generate && generationInput) {
      content = `${content}\n\nGeneration input:\n${JSON.stringify(generationInput)}`
    }
    await sendMessage(content, {
      ...options,
      ...(threadId ? { thread_id: threadId } : {}),
    })
  }, [resolveSessionThreadId, sendMessage, state.selectedRunId])

  const cancel = useCallback(async () => {
    if (!state.selectedRunId) return
    // Release the local composer before waiting for the two durable cancellation
    // calls (Video Build + DeepSeek Session). The server snapshot remains the
    // source of truth and hydrateRun reconciles the final state below.
    sendControllerRef.current?.abort()
    sendControllerRef.current = null
    sendingRef.current = false
    dispatch({ type: 'SENDING', sending: false })
    try {
      await deepAgentV2Client.cancelRun(state.selectedRunId)
    } finally {
      // The BFF stops the durable Video Build before asking DeepSeek Harness to
      // cancel its active turn. If the latter transport call fails, cancellation
      // has still partially succeeded; always reconcile instead of leaving the
      // browser on its pre-stop running snapshot.
      await hydrateRun(state.selectedRunId)
    }
  }, [hydrateRun, state.selectedRunId])

  const deleteRun = useCallback(async (runId: string) => {
    const deletingSelected = selectedRunIdRef.current === runId
    const result = await deepAgentV2Client.deleteRun(runId)
    localStorage.removeItem(sequenceKey(runId))
    localStorage.removeItem(threadKey(runId))
    if (localStorage.getItem(SELECTED_RUN_KEY) === runId) {
      localStorage.removeItem(SELECTED_RUN_KEY)
    }
    if (deletingSelected) {
      selectionVersionRef.current += 1
      hydrateControllerRef.current?.abort()
      selectedRunIdRef.current = null
      dispatch({ type: 'SELECT_RUN', runId: null })
    }
    await loadRuns(null)
    return result
  }, [loadRuns])

  const resume = useCallback(async (
    response: string,
    options: DeepAgentMessageOptions = {},
  ) => {
    if (!state.selectedRunId) return
    const threadId = options.thread_id || resolveSessionThreadId(state.selectedRunId)
    await deepAgentV2Client.resumeRun(state.selectedRunId, response, {
      ...options,
      ...(threadId ? { thread_id: threadId } : {}),
    })
    localStorage.setItem(sequenceKey(state.selectedRunId), String(cursorRef.current))
    await hydrateRun(state.selectedRunId)
  }, [hydrateRun, resolveSessionThreadId, state.selectedRunId])

  const selectArtifact = useCallback(async (versionId: string) => {
    if (!state.selectedRunId) return
    await deepAgentV2Client.selectArtifact(state.selectedRunId, versionId)
    await hydrateRun(state.selectedRunId)
  }, [hydrateRun, state.selectedRunId])

  const extractFrame = useCallback(async (options: {
    timestamp: number
    versionId?: string
    videoUrl?: string
  }) => {
    if (!state.selectedRunId) return null
    const artifact = await deepAgentV2Client.extractFrame(state.selectedRunId, {
      timestamp: options.timestamp,
      versionId: options.versionId,
      videoUrl: options.videoUrl,
      select: true,
    })
    await hydrateRun(state.selectedRunId)
    return artifact
  }, [hydrateRun, state.selectedRunId])

  const refresh = useCallback(
    () => state.selectedRunId ? hydrateRun(state.selectedRunId) : loadRuns(),
    [hydrateRun, loadRuns, state.selectedRunId],
  )

  const loadFullTrace = useCallback(async () => {
    const runId = selectedRunIdRef.current
    if (!runId) return
    try {
      const events = await deepAgentV2Client.getEventLog(runId)
      if (selectedRunIdRef.current !== runId) return
      dispatch({ type: 'TRACE_EVENTS', runId, events })
    } catch {
      // Trace is optional. Keep the tailed snapshot events on screen.
    }
  }, [])

  const activeThreadId = (
    resolveSessionThreadId(state.selectedRunId)
    || pendingThreadId
    || routeThreadIdRef.current
    || ''
  ).trim() || undefined

  return {
    state,
    sessionThreadId: activeThreadId,
    pendingThreadId,
    loadRuns,
    selectRun,
    newSession,
    sendMessage,
    sendSuggestion,
    cancel,
    deleteRun,
    resume,
    selectArtifact,
    extractFrame,
    refresh,
    loadFullTrace,
  }
}
