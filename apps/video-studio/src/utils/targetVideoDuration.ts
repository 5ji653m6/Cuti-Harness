import { DEFAULT_VIDEO_OPTIONS } from '@/constants/defaults'
import { getAudioFileDurationSec } from '@/utils/audioCrop'
import { isAudioFile } from '@/utils/fileUploadUtils'

/** Parse explicit target video length from user message (e.g. "30s", "30 sec", "30秒", "1:30"). */
export function parseTargetDurationFromText(text: string): number | null {
  const normalized = (text || '').trim()
  if (!normalized) return null

  const secMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:秒|s\b|sec\b|secs\b|second\b|seconds\b)/i)
  if (secMatch) {
    const value = Number(secMatch[1])
    if (Number.isFinite(value) && value > 0) {
      return Math.max(5, Math.min(600, Math.round(value)))
    }
  }

  const minMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:分钟|min\b|mins\b|minute\b|minutes\b)/i)
  if (minMatch) {
    const value = Number(minMatch[1]) * 60
    if (Number.isFinite(value) && value > 0) {
      return Math.max(5, Math.min(600, Math.round(value)))
    }
  }

  const mmssMatch = normalized.match(/\b(\d{1,2}):(\d{2})\b/)
  if (mmssMatch) {
    const value = Number(mmssMatch[1]) * 60 + Number(mmssMatch[2])
    if (Number.isFinite(value) && value > 0) {
      return Math.max(5, Math.min(600, Math.round(value)))
    }
  }

  return null
}

/** Latest explicit duration from multiple texts (newest non-empty text wins). */
export function parseTargetDurationFromTexts(texts: string[]): number | null {
  for (let i = texts.length - 1; i >= 0; i--) {
    const text = texts[i]
    if (text === undefined) continue
    const fromText = parseTargetDurationFromText(text)
    if (fromText != null) return fromText
  }
  return null
}

/**
 * Target for auto-cropping uploaded audio.
 * Only when the user explicitly states a duration in text, or has changed the duration control
 * (not the default 30s panel value on a fresh session).
 */
export function resolveAutoCropTargetDurationSec(
  panelDurationSec: number,
  messageText?: string,
  options?: { panelDurationExplicit?: boolean },
): number | null {
  const fromText = messageText ? parseTargetDurationFromText(messageText) : null
  if (fromText != null) return fromText
  if (!options?.panelDurationExplicit) return null
  const panel = panelDurationSec
  if (!Number.isFinite(panel) || panel <= 0) return null
  return Math.max(5, Math.min(600, Math.round(panel)))
}

/** Duration sent to backend in user_option (text override, else panel). */
export function resolveUserOptionDurationSec(
  panelDurationSec: number,
  messageText?: string,
): number {
  const fromText = messageText ? parseTargetDurationFromText(messageText) : null
  if (fromText != null) return fromText
  const panel = panelDurationSec
  return Number.isFinite(panel) && panel > 0 ? panel : DEFAULT_VIDEO_OPTIONS.duration
}

export type SendDurationPlan = {
  userOptionDurationSec: number
  cropTargetSec: number | null
  panelDurationSec?: number
}

/**
 * Resolve duration/crop for submit from attached files (source of truth for audio length).
 * Avoids stale panel default (30s) when upload sync has not finished yet.
 */
export async function resolveSendDurationPlan(
  files: File[],
  panelDurationSec: number,
  messageText?: string,
  options?: { panelDurationExplicit?: boolean; messageTexts?: string[]; explicitDurationSec?: number | null },
): Promise<SendDurationPlan> {
  const panel = panelDurationSec
  const safePanel =
    Number.isFinite(panel) && panel > 0 ? panel : DEFAULT_VIDEO_OPTIONS.duration
  const durationTexts = options?.messageTexts?.length
    ? options.messageTexts
    : messageText
      ? [messageText]
      : []
  const explicitDuration = Number(options?.explicitDurationSec)
  const fromText =
    Number.isFinite(explicitDuration) && explicitDuration > 0
      ? Math.max(5, Math.min(600, Math.round(explicitDuration)))
      : parseTargetDurationFromTexts(durationTexts)
  const audioFile = files.find(file => isAudioFile(file))

  if (audioFile) {
    let audioSec = safePanel
    try {
      audioSec = await getAudioFileDurationSec(audioFile)
    } catch {
      // keep panel fallback
    }
    if (fromText != null) {
      const cropTarget = fromText < audioSec - 0.05 ? fromText : null
      return {
        userOptionDurationSec: fromText,
        cropTargetSec: cropTarget,
        panelDurationSec: fromText,
      }
    }
    return {
      userOptionDurationSec: audioSec,
      cropTargetSec: null,
      panelDurationSec: audioSec,
    }
  }

  const fallbackText = durationTexts.length ? durationTexts.join('\n') : messageText
  return {
    userOptionDurationSec:
      fromText != null ? fromText : resolveUserOptionDurationSec(safePanel, fallbackText),
    cropTargetSec:
      fromText != null
        ? fromText
        : resolveAutoCropTargetDurationSec(safePanel, fallbackText, options),
  }
}
