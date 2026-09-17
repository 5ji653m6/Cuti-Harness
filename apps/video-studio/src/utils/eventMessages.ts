/**
 * 根据事件类型生成显示文本
 * 前端根据 event_type 自己生成文本，不依赖后端返回的 message
 * 方便实现国际化
 */

// 事件类型到显示文本的映射
export const getEventDisplayMessage = (eventType: string, _eventData?: unknown): string => {
  const eventMessages: Record<string, string> = {
    // 用户输入和系统事件
    'user_input': 'User Input',
    'session_created': 'Session Created',

    // 视频生成流程
    'video_analysis': 'Video Analysis',
    'story_outline_generated': 'Story Outline Generated',
    'characters_designed': 'Characters Designed',
    'scenes_generated': 'Scenes Generated',
    'storyboard_detail_generated': 'Storyboard Detail Generated',
    'keyframes_generated': 'Keyframes Generated',
    'keyframes_reflection_completed': 'Keyframes Reflection Completed',
    'narrations_generated': 'Narrations Generated',
    'audio_effects_generated': 'Audio Effects Generated',
    'video_segments_generated': 'Video Segments Generated',
    'music_generated': 'Music Generated',
    'video_completed': 'Video Assembled',  // 视频拼接完成

    // 绘本生成流程
    'storybook_story_generated': 'Storybook Story Generated',
    'storybook_completed': 'Storybook Completed',

    // 故事代理相关事件
    'story_agent_generated': 'Story Generated',

    // 音乐代理相关事件
    'music_agent_generated': 'Music Generated',

    // 图像代理相关事件
    'image_agent_generated': 'Image Generated',

    // 视频直生代理相关事件
    'video_agent_generated': 'Video Generated',

    // 澄清请求
    'clarification_request': 'Clarification Request',

    // 编辑和评估
    'quality_evaluation': 'Quality Evaluation',
    'keyframe_regenerated': 'Keyframe Regenerated',
    'video_regenerated': 'Video Regenerated',
    'storyboard_regenerated': 'Storyboard Regenerated',
    'version_selected': 'Version Selected',
    'auto_retry_triggered': 'Auto Retry Triggered',
    'video_reassembled': 'Video Reassembled',

    // 系统事件
    'generation_failed': 'Generation Failed',
    'error': 'Error',
    'success': 'Success',
    'warning': 'Warning',
    'info': 'Info',
  }

  // 如果 eventType 为空或 undefined，返回空字符串
  if (!eventType) {
    return ''
  }

  // 如果有映射，返回映射的文本
  if (eventMessages[eventType]) {
    return eventMessages[eventType]
  }

  // 如果没有映射，返回格式化的事件类型
  return eventType
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/**
 * 检查消息是否应该在对话框中隐藏
 * hidden=true 的消息仍然会被前端接收（用于逻辑判断），但不显示在对话框中
 */
export const shouldHideMessage = (eventData?: unknown): boolean => {
  return typeof eventData === 'object' && eventData !== null && 'hidden' in eventData && eventData.hidden === true
}

