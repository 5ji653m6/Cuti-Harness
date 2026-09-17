/**
 * 按当前选中的 image_tool / video_tool 拉取支持的 resolution、aspect_ratio 选项与说明。
 * Create 页与首页共用同一逻辑，由 VideoOptionsPanel 消费。
 */
import { useState, useEffect, useCallback } from 'react'
import { agentApi } from '@/services/api'

/** 前端视频模型 value 到后端 video_tool 枚举的映射 */
const VIDEO_MODEL_TO_BACKEND: Record<string, string> = {
  seedance_1_0_pro_fast: 'pollo_seedance',
  seedance_1_5_pro_fast: 'pollo_seedance_v1_5',
  seedance_2_i2v: 'seedance_2_i2v',
  seedance_2_i2v_turbo: 'seedance_2_i2v_turbo',
  seedance_2_fast_i2v: 'seedance_2_fast_i2v',
  seedance_2_fast_i2v_turbo: 'seedance_2_fast_i2v_turbo',
  pollo_seedance: 'pollo_seedance',
  pollo_seedance_v1_5: 'pollo_seedance_v1_5',
  wan_2_5: 'wan_2_5',
  wan_2_6_flash: 'wan_2_6_flash',
  kling_v3_std: 'kling_v3_std',
  happyhorse_1_0_i2v: 'happyhorse_1_0_i2v',
  happyhorse_1_1_i2v: 'happyhorse_1_1_i2v',
  sora: 'openai_sora',
  sora2_pro: 'openai_sora_pro',
}

export interface VideoOptionsCapabilities {
  aspect_ratios: { value: string; label: string }[]
  resolutions: { value: string; label: string }[]
  warnings: string[]
  /** 口型视频模型列表（与后端 LIPSYNC_VIDEO_TOOL_OPTIONS 一致，供下拉使用） */
  lipsync_video_tools?: { value: string; label: string }[]
}

const DEFAULT_RESOLUTIONS = [
  { value: '480p', label: '480p' },
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
]
const DEFAULT_ASPECT_RATIOS = [
  { value: '16:9', label: '16:9' },
  { value: '1:1', label: '1:1' },
  { value: '9:16', label: '9:16' },
]

export function useVideoOptionsCapabilities(
  imageTool: string,
  videoModel: string,
  lipsyncTool?: string,
): {
  capabilities: VideoOptionsCapabilities | null
  loading: boolean
  error: Error | null
  refetch: () => void
} {
  const [capabilities, setCapabilities] = useState<VideoOptionsCapabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const fetchCapabilities = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const videoTool = VIDEO_MODEL_TO_BACKEND[videoModel] || videoModel
      const res = await agentApi.getOptionsCapabilities({
        image_tool: imageTool || undefined,
        video_tool: videoTool || undefined,
        lipsync_tool: lipsyncTool || undefined,
      })
      setCapabilities(res.data)
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
      setCapabilities({
        aspect_ratios: DEFAULT_ASPECT_RATIOS,
        resolutions: DEFAULT_RESOLUTIONS,
        warnings: [],
      })
    } finally {
      setLoading(false)
    }
  }, [imageTool, videoModel, lipsyncTool])

  useEffect(() => {
    void fetchCapabilities()
  }, [fetchCapabilities])

  return {
    capabilities,
    loading,
    error,
    refetch: () => { void fetchCapabilities() },
  }
}

export function getEffectiveResolutionOptions(capabilities: VideoOptionsCapabilities | null) {
  return capabilities?.resolutions.length ? capabilities.resolutions : DEFAULT_RESOLUTIONS
}

export function getEffectiveAspectRatioOptions(capabilities: VideoOptionsCapabilities | null) {
  return capabilities?.aspect_ratios.length ? capabilities.aspect_ratios : DEFAULT_ASPECT_RATIOS
}
