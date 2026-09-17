# Video Studio

[English](README.md) | 中文

Video Studio 是 Cuti Video Harness 的视频原生前端。迁移期间，导入的 Cuti 聊天、产物浏览器、播放器、时间线、SSE 处理和旧 API 客户端继续可用。

`/create/:threadId` 是主工作区：左侧保留 DeepSeek 对话，右侧投影 Runtime 工作区，展示角色、镜头、产物版本与 Build 进度，并提供音乐替换、逐镜头 Lipsync、时间线顺序／时长／旁白编辑、费用确认和 MP4 导出。迁移期间，`/video` 路由只保留为高级诊断入口。

右侧工作区将模型与 Runtime 的实时输出动态分到四个 Tab。制作过程展示 Build 和任务状态；最终视频优先展示当前选中的交付成片，否则使用明确合成的视频；素材展示输入及生成的媒体，并提供全部、图片、视频、音频、文字和其他筛选；脚本展示剧本、策划文档与研究。每个图片、视频、音频和脚本卡片都提供默认收起的生成 Prompt；旧产物或上传素材未持久化 Prompt 时会明确说明。数量和可用状态直接随持久化 Artifact 更新，不需要 Workflow 专用的前端字段。

## 开发

选中对话的 SSE 订阅在单轮完成、失败和取消后继续保持。用户后续消息和 Runtime 自动检查点沿用同一 `thread_id`。快照排序使用 Harness 事件序号，而不是项目修改时间；请求取消由当前发送操作或显式停止操作负责。

开源 Studio 无需账号或登录配置。Create 直接打开，不依赖认证请求或登录跳转；本地项目身份由 Video Runtime 提供。后端配置的服务令牌与能力授权仍然生效。单用户界面不提供公网多用户访问控制，对外部署需要通过认证网关保护。

Markdown 文档支持 GFM 表格、可键盘访问的横向滚动以及章节导航。Runtime 执行名称保留在进度视图，不作为重复的剧本结果展示。

Create 将生成的文本和剧本渲染为可读的 Markdown，将完整 JSON 文档呈现为带标签的字段和编号内容卡片。长列表按需展开，原始 JSON 保留在折叠详情中。模型提供的 HTML 不会执行。通用 `ArtifactDocument` 渲染器保留未知字段并支持嵌套结构，无需为每个 Workflow 定制视图。

前端类型检查覆盖可空值和未经检查的数组索引。置顶对话记录在展示前进行校验，忽略格式错误的记录。异步界面操作会报告未捕获的失败；Canvas 上下文不可用或 PNG 编码失败时，图片导出会拒绝完成。请求头支持对象、元组数组和 `Headers` 实例，并允许单次请求覆盖默认值。

```sh
pnpm --filter @cuti-ai/video-studio run dev
```

开发服务器使用 `VITE_VIDEO_RUNTIME_URL` 转发 `/api/video`；为了兼容组合式 Cuti 后端，默认值是 `http://127.0.0.1:8000`。使用独立运行时时，将它设置为 `http://127.0.0.1:8001`。

## 生产构建

构建后，`node apps/video-studio/tests/browser-session.snapshot.mjs` 使用脚本化 API 响应，对构建产物运行无需密钥的浏览器对话快照。需要 Playwright 和 Chromium。共享安装可将 `VIDEO_STUDIO_PLAYWRIGHT_MODULE` 设置为模块 URL，将 `VIDEO_STUDIO_BROWSER` 设置为浏览器可执行文件。场景验证完成后的用户续聊、Runtime 自动轮次、Provider 失败提示和动态 Artifact Tab 分类，不创建项目或访问提供方。

```sh
pnpm --filter @cuti-ai/video-studio run build
```

`deploy/compose.video.yml` 会构建应用并在 `http://127.0.0.1:3000` 提供服务。本地镜像把 `/api/video` 代理到独立运行时。生产环境的身份与聊天路由仍由部署方集成。
