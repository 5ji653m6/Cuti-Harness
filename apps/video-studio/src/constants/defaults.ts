/**
 * 与后端 user_options / tool_enums.DefaultValues.DEFAULT_IMAGE_TOOL_NAME 对应：默认图像工具（GPT Image 2）。
 * 改默认时只改此处与后端 tool_enums.DefaultValues.IMAGE_MODEL。
 */
export type ImageGenerationToolType = 'nano_banana' | 'nano_banana_2' | 'nano_banana_pro' | 'seedream' | 'gpt_image_2'

export const DEFAULT_IMAGE_GENERATION_TOOL: ImageGenerationToolType = 'gpt_image_2'

/** 首页与 Create 页共用的默认选项（保持一致），类型显式声明避免 useState 推断为字面量 */
export const DEFAULT_VIDEO_OPTIONS: {
  duration: number
  aspectRatio: '16:9' | '1:1' | '9:16'
  resolution: '480p' | '720p' | '1080p'
  lipsyncCoverage: number
  enableContinuityMode: boolean
  enableKeyframeReflection: boolean
  selectedModel: string
  /** 口型视频模型（仅对口型镜头生效）；默认 auto 与后端 UserOption 一致，由 per_shot routing 按分辨率选 WAN 2.2 / Kling 等 */
  lipsyncVideoModel: string
  /** 首页 Full Auto = 暂停点 15s 倒计时后自动继续；仅前端生效，刷新/关 tab 会丢失，后端不保存 */
  autoContinueOnInterrupt: boolean
} = {
  duration: 30,
  aspectRatio: '16:9',
  resolution: '1080p',
  lipsyncCoverage: 50,
  enableContinuityMode: false,
  enableKeyframeReflection: false,
  selectedModel: 'Auto',
  lipsyncVideoModel: 'auto',
  autoContinueOnInterrupt: true, // 与首页 isFullAuto 默认 true 一致
}
