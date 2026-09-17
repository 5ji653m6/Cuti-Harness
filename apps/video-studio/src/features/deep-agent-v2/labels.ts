import { arrayItem } from '../../utils/arrayItem'
import { translations, type TranslationKey } from '../../i18n/translations'

export type Translate = (key: TranslationKey) => string

export function interpolate(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (text, [key, value]) => text.replace(new RegExp(`\\{${key}\\}`, 'g'), String(value)),
    template,
  )
}

export function hasTranslation(key: string): key is TranslationKey {
  return Object.hasOwn(translations.en, key)
}

export function lookup(t: Translate, key: string): string | undefined {
  if (!hasTranslation(key)) return undefined
  return t(key)
}

export function statusLabel(status: string, t: Translate): string {
  return lookup(t, `da.status.${status}`) || status.replace(/_/g, ' ')
}

export function skillDisplayName(skillId: string, t: Translate, fallback?: string): string {
  return lookup(t, `da.skill.${skillId}`) || fallback || skillId
}

export function skillDescription(skillId: string, t: Translate, fallback?: string): string {
  return lookup(t, `da.skill.${skillId}.desc`) || fallback || ''
}

export function skillUnavailableReason(reason: string | null | undefined, t: Translate): string {
  const text = (reason || '').trim()
  if (!text) return t('da.skill.unavailable')
  if (/openmontage/i.test(text)) return t('da.skill.unavailable.openMontage')
  if (/shotcraft|remotion/i.test(text)) return t('da.skill.unavailable.shotcraft')
  return text
}

export function capabilityLabel(capabilityId: string, t: Translate): string {
  return lookup(t, `da.cap.${capabilityId}`) || capabilityId
}

function numberedShotPart(value: string): string | null {
  const match = value.match(/^(?:(?:shot|segment)[-_]?)?(\d+)$/i)
  if (!match) return null
  return String(Number.parseInt(arrayItem(match, 1), 10))
}

export type StepEntityNames = Readonly<Record<string, string>>

function entityName(id: string, names: StepEntityNames): string {
  return names[id] || names[id.replace(/-/g, '_')] || id.replace(/[-_]/g, ' ')
}

export function planStepLabel(
  stepId: string,
  t: Translate,
  entityNames: StepEntityNames = {},
): string {
  const id = (stepId || '').trim()
  if (!id) return id
  const exact = lookup(t, `da.step.${id}`)
  if (exact) return exact

  const shotVideo = id.match(/^shot-(.+)-video$/i)
  if (shotVideo) {
    const n = numberedShotPart(arrayItem(shotVideo, 1))
    return n
      ? interpolate(t('da.step.shotVideo'), { n })
      : interpolate(t('da.step.shotVideoNamed'), { id: entityName(arrayItem(shotVideo, 1), entityNames) })
  }
  const shotKeyframe = id.match(/^shot-(.+)-keyframe$/i)
  if (shotKeyframe) {
    const n = numberedShotPart(arrayItem(shotKeyframe, 1))
    return interpolate(t('da.step.shotKeyframe'), { n: n || entityName(arrayItem(shotKeyframe, 1), entityNames) })
  }
  const characterRef = id.match(/^character-(.+)-reference$/i)
  if (characterRef) {
    return interpolate(t('da.step.characterReferenceNamed'), {
      id: entityName(arrayItem(characterRef, 1), entityNames),
    })
  }
  const sceneRef = id.match(/^scene-(.+)-reference$/i)
  if (sceneRef) {
    return interpolate(t('da.step.sceneReferenceNamed'), {
      id: entityName(arrayItem(sceneRef, 1), entityNames),
    })
  }
  const source = id.match(/^source-(\d+)$/i)
  if (source) {
    return interpolate(t('da.step.sourceNamed'), { n: arrayItem(source, 1) })
  }
  const productValidation = id.match(/^shot-(.+)-product-validation$/i)
  if (productValidation) {
    const n = numberedShotPart(arrayItem(productValidation, 1))
    return interpolate(t('da.step.shotProductValidation'), {
      n: n || entityName(arrayItem(productValidation, 1), entityNames),
    })
  }
  return id.replace(/[-_]/g, ' ')
}

export function artifactTitle(title: string | undefined, type: string, t: Translate): string {
  const raw = (title || '').trim()
  if (!raw) return planStepLabel(type, t) || type
  const exact = lookup(t, `da.step.${raw}`)
  if (exact) return exact
  if (
    /^shot-.+-video$/i.test(raw)
    || /^shot-.+-keyframe$/i.test(raw)
    || /^character-.+-reference$/i.test(raw)
  ) {
    return planStepLabel(raw, t)
  }
  return raw
}

export function runtimeMessage(message: string, t: Translate): string {
  const text = (message || '').trim()
  if (!text) return text
  const exactMessages: Record<string, TranslationKey> = {
    'Content moderation: awaiting Agent review': 'da.runtime.moderationReview',
    'Content moderation: repairing (1/1)': 'da.runtime.moderationRepair',
    'Content moderation: repair succeeded': 'da.runtime.moderationRecovered',
    'Content moderation: user revision required': 'da.runtime.moderationBlocked',
    'Executing initial video build': 'da.runtime.executingInitial',
    'Executing rebuild plan': 'da.runtime.executingRebuild',
    'Initial video build committed': 'da.runtime.committed',
    'Build committed': 'da.runtime.committed',
    'Build failed; the previous project version remains active': 'da.runtime.failedPreserved',
    'Agent planning failed; the previous project version remains active': 'da.runtime.agentPlanningFailed',
    'Retry queued': 'da.runtime.retryQueued',
    'Resumed by user; reconciling existing work': 'da.runtime.resuming',
    'Cancellation requested': 'da.runtime.cancellationRequested',
  }
  const exact = exactMessages[text]
  if (exact) return t(exact)
  const requestFailed = text.match(/Video Runtime request failed \((\d+)\)/i)
  if (requestFailed) {
    return interpolate(t('da.runtime.requestFailed'), { status: arrayItem(requestFailed, 1) })
  }
  const wavespeed = text.match(/^Waiting for wavespeed operation for (.+)$/i)
  if (wavespeed) {
    return interpolate(t('da.runtime.waitingWavespeed'), {
      step: planStepLabel(arrayItem(wavespeed, 1), t),
    })
  }
  const waiting = text.match(/^Waiting for .+ operation for (.+)$/i)
  if (waiting) {
    return interpolate(t('da.runtime.waitingProvider'), {
      step: planStepLabel(arrayItem(waiting, 1), t),
    })
  }
  const completed = text.match(/^Completed (\d+) of (\d+) (?:media |build )?steps$/i)
  if (completed) {
    return interpolate(t('da.runtime.completedSteps'), {
      done: arrayItem(completed, 1),
      total: arrayItem(completed, 2),
    })
  }
  return planStepLabel(text, t)
}

export function resultCountLabel(count: number, t: Translate): string {
  const key = count === 1 ? 'da.workspace.resultCount' : 'da.workspace.resultCountPlural'
  return interpolate(t(key), { n: count })
}
