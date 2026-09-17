import { displayValue } from '@/utils/displayValue'
import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Circle, Loader2, Wrench } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import { useLanguage } from '@/i18n/LanguageContext'
import { capabilityLabel, interpolate, planStepLabel, skillDisplayName } from './labels'
import type { DeepAgentEvent, DeepAgentRunStatus, DeepAgentTask } from './types'

export interface RuntimeProductionProgress {
  buildId: string
  status: string
  progress: number
  message: string
  error?: string
  phase?: string | null
  checkpoint?: {
    status: string
    nextPhase: string
    artifactCount: number
    unresolvedSections: string[]
  } | null
  steps: Array<{ id: string; name: string; status: string; error?: string; skills: string[] }>
}

function nestedCallId(payload: Record<string, unknown>): string {
  const message = payload.message
  if (!message || typeof message !== 'object') return ''
  const source = (message as Record<string, unknown>).source
  return source && typeof source === 'object'
    ? displayValue((source as Record<string, unknown>).callId || '')
    : ''
}

function localizedRuntimeMessage(
  runtime: RuntimeProductionProgress,
  zh: boolean,
  unknownFailure: string,
): string {
  if (runtime.error) return unknownFailure
  const messages: Record<string, readonly [string, string]> = {
    queued: ['制作任务已排队', 'Production is queued'],
    running: ['正在执行当前制作步骤', 'Running the current production step'],
    waiting_external: ['正在等待生成服务返回结果', 'Waiting for the generation provider'],
    waiting_agent: ['Agent 正在根据已有素材规划下一步', 'The Agent is planning the next step from completed media'],
    completed: ['视频制作已完成', 'Video production is complete'],
    failed: ['制作失败，已完成素材仍会保留', 'Production failed; completed media is preserved'],
    cancelled: ['制作已停止，已完成素材仍会保留', 'Production stopped; completed media is preserved'],
  }
  const message = messages[runtime.status]
  return message ? message[zh ? 0 : 1] : runtime.message
}

function localizedSection(section: string, zh: boolean): string {
  if (!zh) return section.replace(/_/g, ' ')
  const labels: Record<string, string> = {
    characters: '角色设定', shots: '镜头规划', audio: '音频', timeline: '时间线',
    subtitles: '字幕', story: '故事', script: '剧本', scenes: '场景',
  }
  return labels[section] || section.replace(/_/g, ' ')
}

export function AgentProductionProgress({
  status,
  isSending,
  isRunning,
  events,
  tasks,
  runtime,
  upload = null,
}: {
  status?: DeepAgentRunStatus
  isSending: boolean
  isRunning: boolean
  events: DeepAgentEvent[]
  tasks: DeepAgentTask[]
  runtime: RuntimeProductionProgress | null
  language?: 'zh' | 'en'
  upload?: { percent: number; phase: 'uploading' | 'saving' } | null
}) {
  const { language, t } = useLanguage()
  const [expanded, setExpanded] = useState(true)
  const zh = language === 'zh'
  const completedCallIds = new Set(
    events.filter(event => event.type === 'agent.tool.completed')
      .map(event => nestedCallId(event.payload))
      .filter(Boolean),
  )
  const tools = events.filter(event => event.type === 'agent.tool.started')
    .map(event => ({
      id: displayValue(event.payload.callId || event.id),
      name: displayValue(event.payload.tool || event.payload.name || 'tool'),
    }))
    .slice(-6)
  const hasBuildTool = tools.some(tool => tool.name === 'video_project_build')
  const hasVisibleActivity = Boolean(upload) || isSending || isRunning || Boolean(runtime) || tools.length > 0 || tasks.length > 0
  if (!hasVisibleActivity) return null

  const runtimeActive = runtime && ['queued', 'running', 'waiting_external', 'waiting_agent'].includes(runtime.status)
  const stoppedWithoutBuild = status === 'completed' && !runtime && !hasBuildTool
  const failed = status === 'failed' || status === 'cancelled' || runtime?.status === 'failed'
  const heading = upload
    ? (
      upload.phase === 'saving'
        ? t('da.progress.savingUpload')
        : interpolate(t('da.progress.uploading'), { percent: Math.max(0, Math.min(100, Math.round(upload.percent))) })
    )
    : failed
      ? t('da.progress.didNotFinish')
      : stoppedWithoutBuild
        ? t('da.progress.noBuild')
        : runtime?.status === 'waiting_agent'
          ? (zh ? 'Agent 正在规划下一阶段' : 'Agent is planning the next phase')
          : runtimeActive
            ? t('da.progress.producing')
            : runtime?.status === 'completed'
              ? t('da.progress.completed')
              : isSending
                ? t('da.progress.submitting')
                : t('da.progress.interpreting')
  const progressValue = upload
    ? Math.max(0, Math.min(100, upload.percent))
    : runtime
      ? Math.max(0, Math.min(100, runtime.progress * 100))
      : tools.length > 0 ? (hasBuildTool ? 20 : 10) : 4

  return (
    <div
      className={`mx-4 mt-3 rounded-xl border p-3 text-sm shadow-sm ${
        stoppedWithoutBuild || failed
          ? 'border-amber-500/40 bg-amber-500/10'
          : 'border-accent-purple/30 bg-accent-purple/[0.06]'
      }`}
      data-testid="agent-production-progress"
    >
      <div className="flex items-start gap-2">
        {stoppedWithoutBuild || failed ? (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        ) : runtime?.status === 'completed' ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
        ) : (
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-accent-purple" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <p className="font-medium">{heading}</p>
            <div className="flex shrink-0 items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">
                {Math.round(progressValue)}%
              </span>
              <button
                type="button"
                className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-purple/60"
                aria-expanded={expanded}
                aria-label={expanded ? t('da.progress.collapse') : t('da.progress.expand')}
                title={expanded ? t('da.progress.collapse') : t('da.progress.expand')}
                onClick={() =>{  setExpanded(value => !value) }}
              >
                {expanded ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
          <Progress value={progressValue} className="mt-2 h-1.5" />
          {expanded && (
            <>
              <p className="mt-2 text-xs text-muted-foreground">
                {upload
                  ? (upload.phase === 'saving' ? t('da.progress.savingUploadHint') : t('da.progress.uploadingHint'))
                  : stoppedWithoutBuild
                    ? t('da.progress.noBuildHint')
                    : runtime
                      ? localizedRuntimeMessage(runtime, zh, t('da.runtime.unknownFailure'))
                      : t('da.progress.defaultHint')}
              </p>

              {runtime?.checkpoint && (
                <div className="mt-2 rounded-md border border-accent-purple/20 bg-background/60 px-2.5 py-2 text-xs">
                  <p className="font-medium">
                    {zh ? '当前阶段' : 'Current phase'}: {runtime.phase || runtime.checkpoint.nextPhase}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {zh
                      ? `已获得 ${runtime.checkpoint.artifactCount} 个真实产物，正在补全：${runtime.checkpoint.unresolvedSections.map(section => localizedSection(section, true)).join('、') || '下一阶段参数'}`
                      : `${runtime.checkpoint.artifactCount} real artifacts ready; resolving ${runtime.checkpoint.unresolvedSections.map(section => localizedSection(section, false)).join(', ') || 'next-phase parameters'}`}
                  </p>
                </div>
              )}

              {tools.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {tools.map((tool) => {
                    const done = completedCallIds.has(tool.id)
                    return (
                      <div key={tool.id} className="flex items-center gap-2 text-xs">
                        {done ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                        ) : (
                          <Wrench className="h-3.5 w-3.5 text-accent-purple" />
                        )}
                        <span>{capabilityLabel(tool.name, t)}</span>
                        <span className="ml-auto text-[10px] text-muted-foreground">
                          {done ? t('da.progress.completedLabel') : t('da.progress.runningLabel')}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}

              {runtime && runtime.steps.length > 0 && (
                <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                  {runtime.steps.map(step => (
                    <div key={step.id} className="min-w-0 text-xs">
                      <div className="flex min-w-0 items-center gap-2">
                        {step.status === 'completed' ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                        ) : ['running', 'waiting_external'].includes(step.status) ? (
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent-purple" />
                        ) : (
                          <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span className="truncate" title={step.error || step.name}>
                          {planStepLabel(step.name, t)}
                        </span>
                      </div>
                      {step.skills.length > 0 && (
                        <p
                          className="ml-5 mt-0.5 truncate text-[10px] text-muted-foreground"
                          title={step.skills.join(', ')}
                        >
                          {interpolate(t('da.workspace.skillPrefix'), {
                            skills: step.skills.map(id => skillDisplayName(id, t)).join(', '),
                          })}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
