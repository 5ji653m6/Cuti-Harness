import { displayValue } from '@/utils/displayValue'
import { useEffect, useMemo, useRef } from 'react'
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Copy,
  Info,
  ListTree,
  Wrench,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useLanguage } from '@/i18n/LanguageContext'
import { interpolate, type Translate } from './labels'
import type { DeepAgentEvent } from './types'
import type { DeepAgentTokenUsage } from './types'

interface DeepAgentTracePanelProps {
  events: DeepAgentEvent[]
  open: boolean
  language: string
  onClose: () => void
  tokenUsage?: DeepAgentTokenUsage | null
}

type TraceTone = 'neutral' | 'success' | 'warning' | 'error'

const eventTone = (type: string): TraceTone => {
  if (
    type === 'run.failed' ||
    type === 'agent.failed' ||
    type === 'agent.coordination_failed'
  ) {
    return 'error'
  }
  if (type === 'task.failed') return 'warning'
  if (type === 'agent.tool.completed') return 'neutral'
  if (type === 'run.waiting_input' || type === 'run.interruption')
    return 'warning'
  if (type.includes('succeeded') || type === 'run.completed') return 'success'
  return 'neutral'
}

const eventCallId = (event: DeepAgentEvent): string => {
  const direct = event.payload.call_id || event.payload.callId
  if (direct) return displayValue(direct)
  const message = event.payload.message
  if (!message || typeof message !== 'object') return ''
  const source = (message as Record<string, unknown>).source
  return source && typeof source === 'object'
    ? displayValue((source as Record<string, unknown>).callId || '')
    : ''
}

const eventTitle = (
  event: DeepAgentEvent,
  t: Translate,
  toolNames: Map<string, string>,
): string => {
  const payload = event.payload
  const unknown = t('da.trace.unknown')
  if (event.type === 'agent.started')
    return t('da.trace.coordinationStarted')
  if (event.type === 'llm.request.started')
    return interpolate(t('da.trace.llmCall'), { model: displayValue(payload.model || unknown) })
  if (event.type === 'llm.context.ready')
    return t('da.trace.contextReady')
  if (event.type === 'llm.usage')
    return t('da.trace.tokenUsage')
  if (event.type === 'llm.attempt')
    return t('da.trace.llmRetry')
  if (event.type === 'agent.tool.started') {
    return interpolate(t('da.trace.toolCall'), { tool: displayValue(payload.tool || payload.name || unknown) })
  }
  if (event.type === 'agent.tool.completed') {
    const tool = displayValue(payload.tool || toolNames.get(eventCallId(event)) || unknown)
    return interpolate(t(payload.is_error ? 'da.trace.toolFailed' : 'da.trace.toolCompleted'), { tool })
  }
  if (event.type === 'agent.step.started')
    return interpolate(t('da.trace.stepStarted'), { step: displayValue(payload.step || '') })
  if (event.type === 'agent.step.completed')
    return interpolate(t('da.trace.stepCompleted'), { step: displayValue(payload.step || '') })
  if (event.type === 'agent.context.updated')
    return t('da.trace.contextUpdated')
  if (event.type === 'deepseek.permission/preset')
    return t('da.trace.permissionPreset')
  if (event.type === 'deepseek.sandbox/mode')
    return t('da.trace.sandboxMode')
  if (event.type === 'deepseek.approval/policy')
    return t('da.trace.approvalPolicy')
  if (event.type === 'deepseek.session/title')
    return t('da.trace.sessionTitle')
  if (event.type === 'plan.revised') {
    return interpolate(t('da.trace.planRevised'), { revision: displayValue(payload.revision || '') })
  }
  if (event.type === 'task.started') return t('da.trace.taskStarted')
  if (event.type === 'task.succeeded')
    return t('da.trace.taskSucceeded')
  if (event.type === 'task.failed') {
    return t('da.trace.taskFailedRetryable')
  }
  if (event.type === 'artifact.created')
    return t('da.trace.artifactCreated')
  if (
    event.type === 'agent.failed' ||
    event.type === 'agent.coordination_failed'
  ) {
    return t('da.trace.runTerminated')
  }
  if (event.type === 'run.failed') return t('da.trace.runFailed')
  if (event.type === 'run.completed') return t('da.trace.runCompleted')
  if (event.type === 'run.waiting_input')
    return t('da.trace.waitingInput')
  if (event.type === 'run.interruption')
    return t('da.trace.interruptHandled')
  if (event.type === 'chat.message.created')
    return t('da.trace.modelResponse')
  return event.type
}

const eventIcon = (type: string) => {
  const tone = eventTone(type)
  if (type === 'plan.revised') return ListTree
  if (type.includes('tool')) return Wrench
  if (tone === 'error' || tone === 'warning') return AlertTriangle
  if (tone === 'success') return CheckCircle2
  return BrainCircuit
}

const toneClass = (tone: TraceTone) => {
  if (tone === 'error') return 'text-destructive'
  if (tone === 'warning') return 'text-amber-600 dark:text-amber-400'
  if (tone === 'success') return 'text-emerald-500'
  return 'text-accent-purple'
}

const eventSummary = (event: DeepAgentEvent, zh: boolean): string => {
  const payload = event.payload
  if (event.type === 'run.waiting_input' || event.type === 'run.interruption') {
    return [
      payload.what_happened && `Now: ${displayValue(payload.what_happened)}`,
      payload.why_interrupted && `Why: ${displayValue(payload.why_interrupted)}`,
      payload.why_confirm && `Next: ${displayValue(payload.why_confirm)}`,
      payload.skill_name && `Skill: ${displayValue(payload.skill_name)}`,
      payload.skill_resource && `Resource: ${displayValue(payload.skill_resource)}`,
      payload.skill_policy && `Policy: ${displayValue(payload.skill_policy)}`,
      payload.capability_id && `Capability: ${displayValue(payload.capability_id)}`,
      payload.task_id && `Task: ${displayValue(payload.task_id)}`,
    ]
      .filter(Boolean)
      .join('\n')
  }
  if (event.type === 'plan.revised') {
    const tasks = Array.isArray(payload.tasks) ? payload.tasks : []
    return [
      payload.reason ? displayValue(payload.reason) : '',
      ...tasks.map((task) => {
        const value = task as Record<string, unknown>
        return `${displayValue(value.capability_id || 'task')}: ${displayValue(value.objective || '')}`
      }),
      payload.response ? displayValue(payload.response) : '',
    ]
      .filter(Boolean)
      .join('\n')
  }
  if (event.type === 'agent.tool.started') {
    return JSON.stringify(payload.input || payload.arguments || {}, null, 2)
  }
  if (event.type === 'agent.tool.completed') {
    if (payload.output) return displayValue(payload.output)
    if (payload.error) return typeof payload.error === 'string'
      ? payload.error
      : JSON.stringify(payload.error, null, 2)
    return zh ? '工具已返回结果。' : 'The tool returned a result.'
  }
  if (event.type === 'agent.started') return displayValue(payload.observation || '')
  if (event.type === 'llm.request.started') {
    return [
      `Provider: ${displayValue(payload.provider || 'unknown')}`,
      `${zh ? '模型' : 'Model'}: ${displayValue(payload.model || 'unknown')}`,
      `${zh ? '推理强度' : 'Reasoning effort'}: ${displayValue(payload.reasoning_effort || 'default')}`,
      `${zh ? '可用工具' : 'Available tools'}: ${displayValue(payload.tool_count || 0)}`,
    ].join('\n')
  }
  if (event.type === 'llm.context.ready') {
    return [
      `${zh ? '模型' : 'Model'}: ${displayValue(payload.model || 'unknown')}`,
      `${zh ? '上下文窗口' : 'Context window'}: ${Number(payload.context_window || 0).toLocaleString()} tokens`,
    ].join('\n')
  }
  if (event.type === 'llm.usage') {
    return [
      `scope: ${displayValue(payload.scope || 'unknown')}`,
      payload.capability_id && `stage: ${displayValue(payload.capability_id)}`,
      `input: ${Number(payload.input_tokens || 0).toLocaleString()}`,
      `output: ${Number(payload.output_tokens || 0).toLocaleString()}`,
      `cached: ${Number(payload.cached_tokens || 0).toLocaleString()}`,
      `reasoning: ${Number(payload.reasoning_tokens || 0).toLocaleString()}`,
      `total: ${Number(payload.total_tokens || 0).toLocaleString()}`,
      payload.requested_tokens && `requested (failed call): ${Number(payload.requested_tokens).toLocaleString()}`,
      `status: ${displayValue(payload.status || 'unknown')}`,
    ].filter(Boolean).join('\n')
  }
  if (event.type === 'llm.attempt') return JSON.stringify(payload, null, 2)
  if (event.type === 'agent.step.started') {
    return zh
      ? '模型正在根据当前上下文决定下一项动作；具体依据以随后记录的工具参数、工具结果和公开回复为准。'
      : 'The model is selecting the next action from current context; the following tool input, result, or public answer is the auditable record.'
  }
  if (event.type === 'agent.step.completed') {
    return `${zh ? '回合' : 'Turn'} ${displayValue(payload.turn || '-')} · ${zh ? '步骤' : 'Step'} ${displayValue(payload.step || '-')}`
  }
  if (event.type === 'agent.context.updated') {
    return `${zh ? '新增' : 'Inserted'}: ${displayValue(payload.inserted_count || 0)} · ${zh ? '移除' : 'Removed'}: ${displayValue(payload.removed_count || 0)}`
  }
  if (event.type === 'deepseek.permission/preset') return displayValue(payload.preset || '')
  if (event.type === 'deepseek.sandbox/mode') return displayValue(payload.mode || '')
  if (event.type === 'deepseek.approval/policy') return displayValue(payload.policy || '')
  if (event.type === 'deepseek.session/title') return displayValue(payload.title || '')
  if (event.type === 'chat.message.created') {
    const message = payload.message as Record<string, unknown> | undefined
    return message?.role === 'assistant' ? displayValue(message.content || '') : ''
  }
  if (payload.error) return displayValue(payload.error)
  if (payload.response) return displayValue(payload.response)
  if (payload.task_id) return `task_id: ${displayValue(payload.task_id)}`
  return ''
}

export function DeepAgentTracePanel({
  events,
  open,
  language,
  onClose,
  tokenUsage,
}: DeepAgentTracePanelProps) {
  const { t } = useLanguage()
  const bottomRef = useRef<HTMLDivElement>(null)
  const zh = language === 'zh'
  const { visibleEvents, toolNames, executionIssueCount } = useMemo(() => {
    const names = new Map<string, string>()
    events.forEach((event) => {
      if (event.type !== 'agent.tool.started') return
      const callId = eventCallId(event)
      if (callId) names.set(callId, displayValue(event.payload.tool || event.payload.name || 'unknown'))
    })
    return {
      toolNames: names,
      executionIssueCount: events.filter(
        event =>
          (event.type === 'agent.tool.completed' && event.payload.is_error === true) ||
          event.type === 'task.failed',
      ).length,
      visibleEvents: events.filter((event) => {
        if (event.type === 'chat.message.created') {
          const message = event.payload.message as
            Record<string, unknown> | undefined
          return message?.role === 'assistant'
        }
        return true
      }),
    }
  }, [events])

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [open, visibleEvents.length])

  if (!open) return null

  const copyTrace = async () => {
    await navigator.clipboard.writeText(
      visibleEvents.map(event => JSON.stringify(event)).join('\n'),
    )
    toast.success(t('da.trace.copied'))
  }

  return (
    <div className="fixed bottom-4 right-4 z-[70] flex h-[min(560px,72vh)] w-[min(460px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-border/70 bg-background/95 shadow-2xl backdrop-blur">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border/60 px-3">
        <div className="flex min-w-0 items-center gap-2">
          <BrainCircuit className="h-4 w-4 text-accent-purple" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">
              {t('da.trace.title')}
            </div>
            <div className="text-[10px] text-muted-foreground">
              {t('da.trace.subtitle')}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => void copyTrace()}
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-2 p-3">
          {tokenUsage && (
            <div className="grid grid-cols-3 gap-2 rounded-lg border border-accent-purple/25 bg-accent-purple/5 p-2.5 text-center">
              <div><div className="text-sm font-semibold">{tokenUsage.total_tokens.toLocaleString()}</div><div className="text-[10px] text-muted-foreground">{t('da.trace.totalTokens')}</div></div>
              <div><div className="text-sm font-semibold">{tokenUsage.calls}</div><div className="text-[10px] text-muted-foreground">{t('da.trace.llmCalls')}</div></div>
              <div><div className="text-sm font-semibold">{tokenUsage.failed_calls + tokenUsage.retry_attempts + executionIssueCount}</div><div className="text-[10px] text-muted-foreground">{t('da.trace.failedRetried')}</div></div>
              <div className="col-span-3 text-left text-[10px] text-muted-foreground">
                {t('da.trace.input')}: {tokenUsage.input_tokens.toLocaleString()} · {t('da.trace.output')}: {tokenUsage.output_tokens.toLocaleString()} · {t('da.trace.cached')}: {tokenUsage.cached_tokens.toLocaleString()}
              </div>
            </div>
          )}
          {visibleEvents.length === 0 && (
            <div className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
              {t('da.trace.empty')}
            </div>
          )}
          {visibleEvents.map((event) => {
            const Icon = eventIcon(event.type)
            const summary = eventSummary(event, zh)
            const tone = event.type === 'agent.tool.completed' && event.payload.is_error
              ? 'warning'
              : eventTone(event.type)
            return (
              <div
                key={event.id}
                className={
                  tone === 'warning'
                    ? 'rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5'
                    : tone === 'error'
                      ? 'rounded-lg border border-destructive/30 bg-destructive/5 p-2.5'
                      : 'rounded-lg border border-border/60 bg-muted/20 p-2.5'
                }
              >
                <div className="flex items-start gap-2">
                  <Icon
                    className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${toneClass(tone)}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium">
                        {eventTitle(event, t, toolNames)}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {new Date(event.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                    {summary && (
                      <pre className="mt-1.5 max-h-36 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-muted-foreground">
                        {summary}
                      </pre>
                    )}
                    {tone === 'warning' && (
                      <div className="mt-1 flex items-center gap-1 text-[10px] text-amber-700 dark:text-amber-300">
                        <Info className="h-3 w-3" />
                        {t('da.trace.retryable')}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  )
}
