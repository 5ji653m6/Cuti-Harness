# @cuti-ai/video-runtime-http

English | [中文](README.zh.md)

HTTP provider for the Video Runtime seam. It transports first-build and structured edit plans while forwarding cancellation, bounded timeouts, service authentication, and session/user identity to the Python runtime.

Failed responses retain the HTTP status and structured validation details as JSON so the Agent can identify rejected fields and correct its next tool call.

Configure `baseUrl` and, for authenticated deployments, `serviceToken`. `userId` supplies the deployment identity when the calling tool has only a DeepSeek Session id; multi-user deployments must set it from their authenticated BFF rather than share the local default.

Inspecting checkpoint id `live` sends a POST because opening a planning snapshot changes state. Concrete checkpoint ids use GET. Both requests retain the same Session and user identity headers.

## Model Experience

### HTTP provider

#### What the model sees

Nothing directly. It transports typed requests from `@cuti-ai/tool-video` to the Python Video Runtime and returns the runtime response unchanged.

#### Token effect

None directly; the consuming tool owns the bounded model-visible result.

#### KV Cache effect

None directly because endpoint URLs, service tokens, and identity headers never enter model context.

## Known Limitations and Deferred Work

- The provider expects the versioned `/api/video` response envelope and does not support legacy Cuti endpoints directly.
