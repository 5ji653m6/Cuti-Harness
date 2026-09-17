import type { MediaRecord, KeyframeData } from './chatTypes'
/** 与后端 KeyframeListResponse 对齐：首尾帧模式每镜两条根记录（frame_index 0 / -1），勿按 shot_number 去重丢尾帧。 */

export function getKeyframeFrameIndex(keyframe: MediaRecord): number {
  const versions = keyframe.versions
  if (Array.isArray(versions) && versions.length > 0) {
    const fi = versions[0]?.frame_index
    if (fi != null && Number.isFinite(fi)) {
      return fi
    }
  }
  const rootFi = keyframe.frame_index
  if (rootFi != null && Number.isFinite(rootFi)) {
    return rootFi
  }
  return 0
}

function frameIndexDisplayRank(frameIndex: number): number {
  if (frameIndex === 0) return 0
  if (frameIndex === -1) return 2
  return 1
}

export function sortKeyframesForDisplay(keyframes: MediaRecord[]): MediaRecord[] {
  return [...keyframes].sort((a, b) => {
    const shotA = (a.shot_number ?? 0)
    const shotB = (b.shot_number ?? 0)
    if (shotA !== shotB) return shotA - shotB
    const fa = getKeyframeFrameIndex(a)
    const fb = getKeyframeFrameIndex(b)
    const ra = frameIndexDisplayRank(fa)
    const rb = frameIndexDisplayRank(fb)
    if (ra !== rb) return ra - rb
    return fa - fb
  })
}

/** 与后端 _infer_continuity_from_keyframe_response_counts 一致：同一镜多条根记录或已有尾帧才算首尾帧模式。 */
export function inferContinuityFromKeyframeRecords(keyframes: MediaRecord[]): boolean {
  if (!keyframes.length) return false
  if (keyframes.some(kf => getKeyframeFrameIndex(kf) === -1)) return true
  const perShot = new Map<number, number>()
  for (const kf of keyframes) {
    const sn = (kf.shot_number ?? 0)
    if (sn < 1) continue
    perShot.set(sn, (perShot.get(sn) ?? 0) + 1)
  }
  return Array.from(perShot.values()).some(c => c >= 2)
}

export type KeyframeDisplayMetrics = {
  displayKeyframes: MediaRecord[]
  shotSlotTotal: number
  /** 分镜 Tab 计数分母：仅在实际首尾帧数据存在时用 API total(2×镜数)，否则用镜数 */
  expectedRecordTotal: number
  usesContinuityLayout: boolean
}

export function resolveKeyframeDisplayMetrics(
  keyframesData: KeyframeData | undefined,
  totalCount?: number,
): KeyframeDisplayMetrics {
  const keyframes = keyframesData?.keyframes || []
  const shotSlotTotal =
    typeof keyframesData?.shot_total === 'number' && Number.isFinite(keyframesData.shot_total) && keyframesData.shot_total > 0
      ? keyframesData.shot_total
      : Number.isFinite(totalCount) && (totalCount as number) > 0
        ? (totalCount as number)
        : 0
  const apiExpectedTotal =
    typeof keyframesData?.total === 'number' && Number.isFinite(keyframesData.total) && keyframesData.total > 0
      ? keyframesData.total
      : shotSlotTotal > 0
        ? shotSlotTotal
        : keyframes.length
  const sorted = sortKeyframesForDisplay(keyframes)
  const usesContinuityLayout =
    shotSlotTotal > 0 && inferContinuityFromKeyframeRecords(sorted)
  const expectedRecordTotal = usesContinuityLayout
    ? apiExpectedTotal > shotSlotTotal
      ? apiExpectedTotal
      : shotSlotTotal * 2
    : shotSlotTotal > 0
      ? shotSlotTotal
      : keyframes.length

  return {
    displayKeyframes: buildDisplayKeyframesFromSorted(sorted, shotSlotTotal, usesContinuityLayout),
    shotSlotTotal,
    expectedRecordTotal,
    usesContinuityLayout,
  }
}

function buildDisplayKeyframesFromSorted(
  sorted: MediaRecord[],
  shotSlotTotal: number,
  continuityMode: boolean,
): MediaRecord[] {
  if (continuityMode) {
    const bySlot = new Map<string, MediaRecord>()
    for (const kf of sorted) {
      const sn = (kf.shot_number ?? 0)
      if (sn < 1) continue
      const fi = getKeyframeFrameIndex(kf)
      bySlot.set(`${sn}:${fi}`, kf)
    }
    const slots: MediaRecord[] = []
    for (let sn = 1; sn <= shotSlotTotal; sn++) {
      for (const fi of [0, -1] as const) {
        slots.push(
          bySlot.get(`${sn}:${fi}`) ?? {
            shot_number: sn,
            frame_index: fi,
            versions: [],
          },
        )
      }
    }
    return slots
  }

  if (shotSlotTotal > 0) {
    const byShot = new Map<number, MediaRecord>()
    for (const kf of sorted) {
      const sn = (kf.shot_number ?? 0)
      if (sn > 0 && !byShot.has(sn)) {
        byShot.set(sn, kf)
      }
    }
    return Array.from({ length: shotSlotTotal }, (_, index) => {
      const sn = index + 1
      return (
        byShot.get(sn) ?? {
          shot_number: sn,
          frame_index: 0,
          versions: [],
        }
      )
    })
  }

  return sorted
}

/** @deprecated 请用 resolveKeyframeDisplayMetrics */
export function buildDisplayKeyframesFromApi(
  keyframesData: KeyframeData | undefined,
  totalCount?: number,
): MediaRecord[] {
  return resolveKeyframeDisplayMetrics(keyframesData, totalCount).displayKeyframes
}

export function keyframeDisplayReactKey(keyframe: MediaRecord, fallbackIndex: number): string {
  if (keyframe.uuid) return keyframe.uuid
  const sn = keyframe.shot_number ?? fallbackIndex + 1
  return `shot-${sn}-frame-${getKeyframeFrameIndex(keyframe)}`
}
