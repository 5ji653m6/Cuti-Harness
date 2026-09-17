/**
 * VideoOptionsPanel 的纯数据常量与映射。
 *
 * 单独抽出文件的目的：vite-plugin-react-swc 的 Fast Refresh 要求 .tsx 组件文件
 * 只能 export React 组件，混 export 非组件（如下方常量）会触发
 *   "hmr invalidate ... Could not Fast Refresh (XXX export is incompatible)"
 * 进而导致依赖该面板的父组件（GenerationBox / MessageArea）整体冷重载，
 * 表现为 popover 内开关在 HMR 后看似「点击没反应」（实际是浏览器仍在跑旧 closure）。
 *
 * 仅放数据；不要把组件搬进来。
 */

export const VIDEO_MODEL_OPTIONS = [
  { value: 'seedance_1_0_pro_fast', label: 'Seedance 1.0 Pro Fast' },
  { value: 'seedance_1_5_pro_fast', label: 'Seedance 1.5 Pro Fast' },
  { value: 'seedance_2_i2v', label: 'Seedance 2.0' },
  { value: 'seedance_2_i2v_turbo', label: 'Seedance 2.0 Turbo' },
  { value: 'seedance_2_fast_i2v', label: 'Seedance 2.0 Fast' },
  { value: 'seedance_2_fast_i2v_turbo', label: 'Seedance 2.0 Fast Turbo' },
  { value: 'kling_v3_std', label: 'Kling v3 Std' },
  { value: 'happyhorse_1_0_i2v', label: 'HappyHorse 1.0' },
  { value: 'happyhorse_1_1_i2v', label: 'HappyHorse 1.1' },
  { value: 'sora', label: 'Sora' },
  { value: 'sora2_pro', label: 'Sora2 Pro' },
] as const

/** Create 页 selectedModel 为 label 时，用此映射转成 value 传给面板 */
export const VIDEO_MODEL_LABEL_TO_VALUE: Record<string, string> = Object.fromEntries(
  VIDEO_MODEL_OPTIONS.map(m => [m.label, m.value]),
)

/** 视频模型 value 转成 label，供 Create 页 onModelChange 使用 */
export const VIDEO_MODEL_VALUE_TO_LABEL: Record<string, string> = Object.fromEntries(
  VIDEO_MODEL_OPTIONS.map(m => [m.value, m.label]),
)
