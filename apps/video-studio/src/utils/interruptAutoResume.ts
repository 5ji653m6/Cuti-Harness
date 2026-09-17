/** 将后端 interrupt_auto_resume_scheduled 事件合并进已有 interrupt 消息 */
export function patchInterruptAutoResumeScheduled<T extends {
  event_type?: string
  message_id?: string | number
  interrupt_data?: Record<string, unknown>
  event_data?: { interrupt_data?: Record<string, unknown> }
}>(
  messages: T[],
  event: {
    interrupt_msgid?: number | string
    auto_resume_at?: string
    auto_continue_seconds?: number
  },
): T[] | null {
  const rawMid = event.interrupt_msgid
  if (rawMid == null || !event.auto_resume_at) return null
  const mid = Number(rawMid)
  if (!Number.isFinite(mid)) return null

  const idx = messages.findIndex(
    m => m.event_type === 'interrupt' && Number(m.message_id) === mid,
  )
  if (idx < 0) return null

  const msg = messages[idx]
  if (!msg) return messages
  const prevInterrupt =
    msg.interrupt_data ?? msg.event_data?.interrupt_data ?? {}
  const interruptData = {
    ...prevInterrupt,
    auto_resume_at: event.auto_resume_at,
    ...(event.auto_continue_seconds != null
      ? { auto_continue_seconds: event.auto_continue_seconds }
      : {}),
  }

  const next = [...messages]
  next[idx] = {
    ...msg,
    interrupt_data: interruptData,
    event_data: {
      ...(msg.event_data ?? {}),
      interrupt_data: interruptData,
    },
  }
  return next
}

export function remainingSecondsUntil(isoDeadline: string): number {
  const ms = new Date(isoDeadline).getTime() - Date.now()
  if (!Number.isFinite(ms)) return 0
  return Math.max(0, Math.ceil(ms / 1000))
}
