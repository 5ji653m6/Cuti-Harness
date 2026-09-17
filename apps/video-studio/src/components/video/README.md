# Video Components

这个目录包含了从 `CreateVideoPage` 拆分出来的所有子组件。拆分的目的是：
- **降低单个文件的复杂度**：原来的 CreateVideoPage 超过 1200 行，现在只有约 500 行
- **提高代码可维护性**：每个组件职责单一，易于理解和修改
- **增强可重用性**：子组件可以在其他地方复用

## 组件结构

```
CreateVideoPage.tsx (约 500 行)
├── ChatSidebar.tsx (约 300 行)
│   ├── 新建任务按钮
│   ├── Chatbots 列表
│   ├── Chats 对话列表
│   └── 用户信息 & 登出
│
├── MessageArea.tsx (约 150 行)
│   ├── 对话标题
│   ├── 消息列表显示
│   │   ├── 用户消息
│   │   ├── 助手消息
│   │   └── 用户上传的图片/音频
│   └── 消息输入框
│
└── VideoResultsPanel.tsx (约 50 行)
    ├── StorySection.tsx (约 35 行) - 故事大纲章节信息
    ├── StyleSection.tsx (约 35 行) - 视频风格和氛围
    ├── CharactersSection.tsx (约 40 行) - 角色设计图片和名字
    ├── ScenesSection.tsx (约 40 行) - 场景详情
    ├── StoryboardsSection.tsx (约 40 行) - 关键帧图片
    └── ShotsSection.tsx (约 50 行) - 视频片段
```

## 各组件详细说明

### 1. CreateVideoPage.tsx
**职责**：主页面容器，负责状态管理和API调用

**核心功能**：
- 管理所有状态（对话、消息、视频分析数据等）
- 处理API调用（发送消息、加载对话、加载视频分析数据）
- 流式事件处理
- 协调子组件之间的交互

**主要状态**：
```typescript
// UI State
sidebarCollapsed, message, isGenerating

// Conversation State
threadId, conversationId, chats, conversationMessagesMap

// User State
userInfo, userCredits

// Video Analysis State
videoState, analysisData, storyOutlineData, 
charactersData, scenesData, keyframesData, videosData
```

### 2. ChatSidebar.tsx
**职责**：左侧边栏，管理对话列表和用户信息

**Props**：
```typescript
{
  collapsed: boolean;
  selectedChat: string | null;
  chats: Chat[];
  userInfo: UserInfo | null;
  userCredits: UserCredits | null;
  onToggleCollapse: () => void;
  onNewTask: () => void;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string, e: React.MouseEvent) => void;
}
```

**功能**：
- 新建对话
- 切换对话
- 删除对话
- 显示用户信息和积分
- 语言切换
- 登出

### 3. MessageArea.tsx
**职责**：中间消息区域，显示对话内容和输入框

**Props**：
```typescript
{
  chatTitle: string;
  messages: Message[];
  message: string;
  isGenerating: boolean;
  onMessageChange: (value: string) => void;
  onSendMessage: () => void;
}
```

**功能**：
- 显示对话消息列表
- 区分用户消息和AI消息
- 显示用户上传的图片和音频（user_input 事件）
- 消息输入和发送
- 支持 Enter 发送，Shift+Enter 换行

**特殊处理**：
- `user_input` 类型的消息会显示 `event_data.image_url` 和 `event_data.audio_url`
- 消息按照时间戳排序显示

### 4. VideoResultsPanel.tsx
**职责**：右侧结果面板的容器

**Props**：
```typescript
{
  storyOutlineData: any;
  analysisData: any;
  charactersData: any[];
  scenesData: any[];
  keyframesData: any[];
  videosData: any[];
}
```

**功能**：
- 整合所有右侧展示子组件
- 统一滚动容器

### 5. 右侧展示子组件

#### StorySection.tsx
**显示**：故事大纲 (Story Outline)
- 标题：`storyOutlineData.title`
- 章节列表：`storyOutlineData.chapters[]`
  - `chapter.order` - 章节序号
  - `chapter.title` - 章节标题

#### StyleSection.tsx
**显示**：视频风格偏好 (Video Analysis Style)
- 风格：`analysisData.style`
- 氛围：`analysisData.mood`

#### CharactersSection.tsx
**显示**：角色设计 (Character Designs)
- 角色图片：`character.character_image_url`
- 角色名字：`character.name`
- 使用 4 列网格布局

#### ScenesSection.tsx
**显示**：场景详情 (Scene Details)
- 场景名称：`scene.scene_name`
- 场景描述：`scene.description`

#### StoryboardsSection.tsx
**显示**：关键帧 (Keyframes/Storyboards)
- 关键帧图片：`keyframe.image_url`
- 镜头编号：`keyframe.shot_number`
- 使用 4 列网格布局

#### ShotsSection.tsx
**显示**：视频片段 (Video Generations)
- 视频播放器：`video.video_url`（如果有）
- 镜头编号：`video.shot_number`
- 横向滚动布局

## 数据流向

```
1. 用户在 MessageArea 输入消息
   ↓
2. CreateVideoPage.handleSendMessage() 调用 API
   ↓
3. 流式事件返回，更新 conversationMessagesMap
   ↓
4. stream_end 事件触发 getConversationState
   ↓
5. 根据 video_agent_state 中的 UUIDs 并行加载详细数据
   ↓
6. 更新各个 *Data 状态
   ↓
7. VideoResultsPanel 的子组件自动更新显示
```

## 优化效果

- **原CreateVideoPage**: 1153 行
- **新CreateVideoPage**: 约 500 行 (减少 **56%**)
- **子组件总计**: 约 650 行
- **总代码量**: 约 1150 行 (基本持平)

但是：
- ✅ **可读性提升**：每个文件职责单一，易于理解
- ✅ **可维护性提升**：修改某个部分不影响其他部分
- ✅ **可重用性提升**：子组件可以独立使用
- ✅ **测试性提升**：可以对每个组件单独测试

## 后续可优化方向

1. **类型定义**：为所有 Props 和 State 创建详细的 TypeScript 接口
2. **错误边界**：为每个组件添加 Error Boundary
3. **加载状态**：为每个数据加载添加 loading 状态显示
4. **空状态**：优化各组件的空数据显示
5. **性能优化**：使用 React.memo 避免不必要的重渲染
6. **国际化**：将所有硬编码的文本提取为 i18n 键

