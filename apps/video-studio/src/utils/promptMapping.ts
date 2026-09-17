/**
 * 前端展示文案与后端实际 prompt 的映射。
 * 用户在前端看到简短文案，后端收到完整 prompt，且不在前端展示后端文案。
 *
 * 配置方法：在 PROMPT_MAPPINGS 中增加 { name, display, backend }，
 * - name：提示词引导按钮上显示的功能名称（短标签）
 * - display：用户/对话中看到的前端文案（点击发送时作为“用户输入”展示）
 * - backend：实际发给后端的 prompt（不展示给用户）
 * - hint（可选）：当该条 display 在输入框中时，在对话框下方显示的小字提示（如引导上传头像）
 * - fillOnly（可选）：为 true 时点击仅填入 display 不自动发送，否则无 hint 时可点击即发送
 * - homepageOnly（可选）：为 true 时仅在首页展示该标签，Create 页不展示
 */

export const PROMPT_MAPPINGS: {
  name: string
  display: string
  backend: string
  hint?: string
  fillOnly?: boolean
  homepageOnly?: boolean
}[] = [
  // Create 页「对嘴型MV」：仅 Create 页标签使用；首页 demo 不经过 promptMapping，直接发中文/英文
  {
    name: '对嘴型MV',
    display: 'Hi Cuti，帮我做一个对嘴型MV',
    backend:
      'Make a lip-sync music video. Every clip must have lip-sync. The same character appears in many different scenes, always holding a microphone and singing.',
    fillOnly: true,
  },
  {
    name: '新年头像',
    display: 'Hi Cuti，帮我把我的头像变成过年版',
    backend:
      '给我15个这个角色过年的头像 ，过马年。要求：图片风格，角色/人物姿势，图片构图，角色/人脸ID都和输入图完全保持一致。',
    hint: '请给我你的头像（拖动到这个对话框，或者点击上传按钮上传头像）。',
  },
  {
    name: '一键高清',
    display: 'Hi Cuti，帮我把这个图转成高清',
    backend:
      '把这个图转成高清版本。要求：图片视觉风格，图片背景，图片构图，角色/人物的姿势，角色/人物的视觉风格，角色/人脸ID，文字（如有）都和输入图完全保持一致。',
    fillOnly: true,
  },
  // 在此追加更多映射，例如：
  // { name: "功能名", display: "用户看到的短文案", backend: "发给后端的完整 prompt", hint: "可选小字提示", fillOnly?: true },
]

/** Create 页输入框上方暂不展示的 name（映射仍保留，供首页入口与后端转换） */
const PROMPT_NAMES_HIDDEN_FROM_CREATE_INPUT_CHIPS: readonly string[] = ['新年头像', '一键高清']

/** Create 页使用的标签列表：排除 homepageOnly 的项，不在 create 页展示「首页 demo」等 */
export const PROMPT_MAPPINGS_FOR_CREATE_PAGE = PROMPT_MAPPINGS.filter(
  m => !m.homepageOnly && !PROMPT_NAMES_HIDDEN_FROM_CREATE_INPUT_CHIPS.includes(m.name),
)

/**
 * Note:
 * 在入口（如 SelectionHub 的 setExternalPrompt(...)）里填的文案要和该条的 display 完全一致（包括标点、空格），这样发送时才会被替换成对应的 backend。
 */
/** 用户在前端看到的文案（如新年头像入口）- 兼容旧引用 */
export const NEW_YEAR_AVATAR_DISPLAY_PROMPT = PROMPT_MAPPINGS.find(m => m.name === '新年头像')?.display ?? ''
/** 提交给后端的实际 prompt - 兼容旧引用 */
export const NEW_YEAR_AVATAR_BACKEND_PROMPT = PROMPT_MAPPINGS.find(m => m.name === '新年头像')?.backend ?? ''

/**
 * 将用户输入（展示用）转为发给后端的文案。若命中映射则返回后端文案，否则返回原样。
 */
export function getBackendPromptForUserMessage(userMessage: string): string {
  const trimmed = (userMessage || '').trim()
  const found = PROMPT_MAPPINGS.find(m => m.display.trim() === trimmed)
  return found ? found.backend : userMessage
}

/**
 * 将后端返回的 user_input 文案转为前端展示文案。若为已知的后端 prompt 则显示对应简短文案，否则原样展示。
 */
export function getDisplayPromptForUserMessage(content: string): string {
  if (!content) return content
  const trimmed = content.trim()
  const found = PROMPT_MAPPINGS.find(m => m.backend.trim() === trimmed)
  return found ? found.display : content
}
