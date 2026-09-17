import type { DeepAgentEvent, DeepAgentNotice } from './types'

const STEP_LABELS_ZH: Record<string, string> = {
  after_music: '配乐已经生成好了',
  after_outline: '故事大纲已经写好了',
  after_character: '角色形象已经设计好了',
  after_storyboard_detail: '分镜已经排好了',
  after_keyframe_reflection: '关键画面已经准备好了',
  after_shots: '各镜头视频已经生成好了',
  music: '配乐生成',
  outline: '大纲生成',
  character: '角色生成',
}

const STEP_LABELS_EN: Record<string, string> = {
  after_music: 'Music is ready',
  after_outline: 'Story outline is ready',
  after_character: 'Character design is ready',
  after_storyboard_detail: 'Storyboard details are ready',
  after_keyframe_reflection: 'Keyframes are ready',
  after_shots: 'Shot videos are ready',
  music: 'Music generation',
  outline: 'Outline generation',
  character: 'Character generation',
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function pickString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function parseLabeledResponse(text: string): {
  what: string
  why: string
  need: string
} {
  const what = text.match(/发生了什么[：:]\s*([^\n]+)/)?.[1]?.trim() || ''
  const why = text.match(/为什么中断[：:]\s*([^\n]+)/)?.[1]?.trim() || ''
  const need = text.match(/为什么需要确认[：:]\s*([^\n]+)/)?.[1]?.trim()
    || text.match(/Why confirm[：:]\s*([^\n]+)/i)?.[1]?.trim()
    || ''
  return { what, why, need }
}

/** Build a plain-language waiting-input notice from event payload / last_response. */
export function buildWaitingInputNotice(input: {
  payload?: Record<string, unknown> | null
  lastResponse?: string | null
  zh?: boolean
}): DeepAgentNotice {
  const zh = input.zh !== false
  const payload = input.payload || {}
  const interrupt = asRecord(payload.interrupt_data)
  const interruption = asRecord(payload.interruption)
  const failure = asRecord(interrupt.failure)
  const step = pickString(
    payload.stage,
    interruption.stage,
    interrupt.step,
    interrupt.stage,
    payload.step,
  )
  const labeled = parseLabeledResponse(pickString(payload.response, input.lastResponse))

  const stepLabel = (zh ? STEP_LABELS_ZH : STEP_LABELS_EN)[step] || ''
  const messageDefault = pickString(
    interrupt.message_default,
    interrupt.message,
    interrupt.content,
    payload.message,
  )

  let what = pickString(
    payload.what_happened,
    interruption.what_happened,
    interrupt.what_happened,
    labeled.what,
    stepLabel,
    messageDefault,
  )
  let why = pickString(
    payload.why_interrupted,
    interruption.why_interrupted,
    interrupt.why_interrupted,
    labeled.why,
    failure.user_message,
    failure.message,
    messageDefault,
  )
  let need = pickString(
    payload.why_confirm,
    interruption.what_next,
    interrupt.why_confirm,
    labeled.need,
  )

  const disableAuto = Boolean(
    payload.disable_auto_resume
    ?? interrupt.disable_auto_resume
    ?? Object.keys(failure).length > 0,
  )
  const willAuto = !disableAuto && Boolean(
    payload.will_auto_resume
    ?? interrupt.will_auto_resume,
  )
  const secondsValue = payload.auto_resume_seconds ?? interrupt.auto_resume_seconds
  const secondsRaw = Number(secondsValue)
  const seconds = secondsValue !== undefined && Number.isFinite(secondsRaw) && secondsRaw >= 0
    ? secondsRaw
    : (willAuto ? 15 : undefined)
  const confirmationRequired = Boolean(
    payload.confirmation_required
    ?? interruption.requires_confirmation
    ?? (!willAuto),
  )
  const interruptCategory = pickString(
    payload.interrupt_category,
    interruption.category,
  )
  const skillName = pickString(payload.skill_name, interruption.skill_name)
  const skillResource = pickString(payload.skill_resource, interruption.skill_resource)
  const skillPolicy = pickString(payload.skill_policy, interruption.skill_policy)
  const capabilityId = pickString(payload.capability_id, interruption.capability_id)
  const taskId = pickString(payload.task_id, interruption.task_id)

  if (!what) {
    what = zh
      ? '视频制作做到一半先停住了'
      : 'Video production paused mid-way'
  }
  if (!why) {
    why = Object.keys(failure).length > 0
      ? (zh
        ? '这一步生成失败了，系统先停下来，避免带着错误继续做。'
        : 'This step failed, so production paused to avoid continuing with bad results.')
      : (messageDefault
        || (zh
          ? '系统做完当前这一步后会稍停一下，方便你确认结果再进入下一步。'
          : 'The system pauses after each major step so you can confirm before continuing.'))
  }
  if (!need) {
    need = willAuto
      ? (zh
        ? `你已经同意开始生成。大约 ${seconds || 15} 秒后会自动继续；也可以马上点「继续生成」。`
        : `You already asked to generate. It will auto-continue in about ${seconds || 15}s, or tap Continue now.`)
      : (zh
        ? '需要你点一下「继续生成」，系统才会进入下一步（例如做分镜、画面或成片）。'
        : 'Tap Continue generation so the system can move to the next step.')
  }

  // Strip jargon if it leaked from older backend strings.
  const scrub = (text: string) => text
    .replace(/阶段门控/g, '当前步骤')
    .replace(/门控/g, '检查点')
    .replace(/下游生成/g, '视频生成')
    .replace(/VideoAgent/g, '视频制作')

  what = scrub(what)
  why = scrub(why)
  need = scrub(need)

  return {
    severity: willAuto ? 'info' : (Object.keys(failure).length > 0 ? 'error' : 'warning'),
    message: zh
      ? `现在：${what}\n原因：${why}\n接下来：${need}`
      : `Now: ${what}\nWhy: ${why}\nNext: ${need}`,
    whatHappened: what,
    whyInterrupted: why,
    whyConfirm: need,
    confirmationRequired,
    interruptCategory: interruptCategory || undefined,
    skillName: skillName || undefined,
    skillResource: skillResource || undefined,
    skillPolicy: skillPolicy || undefined,
    capabilityId: capabilityId || undefined,
    taskId: taskId || undefined,
    stage: step || undefined,
    willAutoResume: willAuto,
    autoResumeSeconds: seconds,
  }
}

export function waitingInputNoticeFromEvents(
  events: DeepAgentEvent[],
  lastResponse?: string | null,
  zh = true,
): DeepAgentNotice | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i]
    if (!event) continue
    if (event.type !== 'run.waiting_input') continue
    return buildWaitingInputNotice({
      payload: event.payload,
      lastResponse,
      zh,
    })
  }
  if (lastResponse?.trim()) {
    return buildWaitingInputNotice({ lastResponse, zh })
  }
  return null
}
