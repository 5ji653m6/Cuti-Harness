# @cuti-ai/video-runtime

[English](README.md) | 中文

面向项目的 Video Runtime Service Definition。DeepSeek 负责对话和工具选择；本服务负责项目、不可变版本、产物依赖、结构化编辑预览、增量重建、校验和导出。

Schema version 2 Build 使用只追加的分阶段计划。Runtime 持久化 `ProjectIntent`、`VideoSpecRevision`、`BuildPlanRevision` 和语义检查点，但绝不使用 LLM 进行规划；真实媒体影响下一步创作时，由 BFF 投递器唤醒绑定的 DeepSeek Session。

`ProjectIntent` 和 `VideoSpec` 携带持久化的 `language_contract`，分别包含 `ui_locale`、`content_language`、`spoken_language`、`subtitle_language` 和 `provider_prompt_language`。消费者必须在计划修订间保留它，避免 Provider 专用提示词语言改变用户可见产物的语言。

彼此独立的 Provider Step 可以在 BuildPlan 中声明持久化的 `execution_group` 与 `max_parallelism`。Runtime 会并发调度该组，同时服从部署级 `DEEP_AGENT_V2_MAX_PARALLEL_GENERATION_TASKS` 上限（默认 `2`）；依赖、重试、远程任务 ID、取消和草稿 Artifact 提交语义与串行 Step 保持一致。

## Model Experience

### Runtime 服务

#### 模型看到什么

模型不会直接看到本包。服务提供由 `@cuti-ai/tool-video` 使用的类型化项目操作；工具包负责所有面向模型的 schema 和结果文本。

#### Token 影响

没有直接影响；只有 Consumer 工具的请求与有界结果会占用 Token。

#### KV Cache 影响

没有直接影响，因为本包不注册提示词文本或工具 schema。

## Known Limitations and Deferred Work

- 首个 Provider 使用 HTTP，并把持久任务和检查点恢复交给 Python Video Runtime。
