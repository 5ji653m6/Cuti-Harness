# @cuti-ai/video-runtime-http

[English](README.md) | 中文

Video Runtime 能力 seam 的 HTTP Provider。它传输首次构建与结构化编辑计划，并把取消信号、有界超时、服务认证以及 Session／用户身份转发到 Python 运行时。

失败响应保留 HTTP 状态码，并将结构化校验详情按 JSON 返回，使 Agent 能定位被拒绝的字段并修正下一次工具调用。

请配置 `baseUrl`，认证部署还需配置 `serviceToken`。调用工具只提供 DeepSeek Session id 时，`userId` 提供部署身份；多用户部署必须由认证 BFF 设置该值，不能共享本地默认值。

检查点 ID 为 `live` 时使用 POST，因为打开规划快照会修改状态；具体检查点 ID 使用 GET。两类请求均保留相同的 Session 和用户身份请求头。

## Model Experience

### HTTP Provider

#### 模型看到什么

模型不会直接看到本包。它把类型化请求从 `@cuti-ai/tool-video` 传输到 Python Video Runtime，并原样返回运行时响应。

#### Token 影响

没有直接影响；Consumer 工具负责有界的模型可见结果。

#### KV Cache 影响

没有直接影响，因为端点 URL、服务 Token 和身份 Header 不会进入模型上下文。

## Known Limitations and Deferred Work

- Provider 要求版本化 `/api/video` 响应 envelope，不直接支持旧 Cuti 端点。
