# @cuti-ai/video-runtime

English | [中文](README.zh.md)

Service definition for the project-oriented video runtime. DeepSeek owns dialogue and tool selection; this service owns projects, immutable versions, artifact dependencies, structured edit previews, incremental rebuilds, validation, and exports.

Schema-version-2 builds are append-only staged plans. The Runtime persists `ProjectIntent`, `VideoSpecRevision`, `BuildPlanRevision`, and semantic checkpoints; it never plans with an LLM. A BFF delivery worker wakes the bound DeepSeek Session when real media changes the next creative decision.

`ProjectIntent` and `VideoSpec` carry a durable `language_contract`: `ui_locale`, `content_language`, `spoken_language`, `subtitle_language`, and `provider_prompt_language`. Consumers must preserve it across plan revisions so provider-specific prompt language never changes the language of user-visible artifacts.

Independent provider steps may declare a durable `execution_group` and `max_parallelism` in the BuildPlan. The Runtime schedules that group concurrently while applying the deployment-wide `DEEP_AGENT_V2_MAX_PARALLEL_GENERATION_TASKS` cap (default `2`). Dependencies, retries, remote operation IDs, cancellation, and staged Artifact commits remain identical to sequential steps.

## Model Experience

### Runtime service

#### What the model sees

Nothing directly. The service owns typed project operations consumed by `@cuti-ai/tool-video`; the tool package owns all model-visible schemas and result text.

#### Token effect

None directly; only the consuming tool's request and bounded result contribute tokens.

#### KV Cache effect

None directly because this package registers no prompt text or tool schema.

## Known Limitations and Deferred Work

- The first provider uses HTTP and delegates durable task and checkpoint recovery to the Python Video Runtime.
