# @cuti-ai/video-agent-bundle

English | [中文](README.zh.md)

Cordis bundle that connects a DeepSeek Harness profile to the Python Cuti Video Runtime and exposes the stable high-level video tool set.

## Model Experience

### Video Agent composition

#### What the model sees

The bundle contributes nothing by itself. Its Cordis patch mounts `@cuti-ai/tool-video`, whose twelve high-level video tools own the complete model-visible surface. The local OpenAI route uses five-minute request and stream-idle limits so long-context VideoSpec planning is not cut off by the provider transport.

#### Token effect

Tool schemas and results contribute tokens. The video patch enables the upstream conversation compactor, `/compact` command and tool-result pruner, including when the Web profile disables them. Automatic pressure handling and bounded context-overflow recovery keep long video planning sessions usable; summaries replace older model context while the Session log retains the original events.

#### KV Cache effect

The bundle adds no prompt text; the mounted tool catalog remains prefix-stable while the composition is unchanged.

## Known Limitations and Deferred Work

- The Python runtime must be deployed separately and reachable through `VIDEO_RUNTIME_URL`.
