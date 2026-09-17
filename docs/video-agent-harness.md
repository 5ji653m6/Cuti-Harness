# Cuti Video Harness Reference

English | [中文](video-agent-harness.zh.md)

This reference defines the ownership, persistence, extension, and execution rules for the video-specific layer built on DeepSeek Harness.

## Component ownership

| Component | Owner | Responsibility |
|---|---|---|
| Session, prompt, model calls, agent loop, tool choice | Cuti Harness | Understand intent and choose one of the model-facing video tools. |
| `@cuti-ai/tool-video` | Cuti Harness plugin | Expose eleven project-level operations without exposing provider or workflow internals to the model. |
| Video Runtime HTTP provider | Cuti Harness plugin | Forward cancellation and trusted Session/user identity to the Python process. |
| Video Runtime | Cuti Python runtime | Own projects, versions, artifacts, dependencies, rebuilds, validation, timelines, exports, and ordered events. |
| Video Studio | Cuti React application | Present chat, verifiable agent and Build progress, artifacts, playback, timeline editing, rebuild impact, cost, validation, and version history. |

The Video Runtime is the sole authority for video project state. A Harness Session can bind to several projects, and one project can bind to several Sessions. Deleting or compacting a Session does not delete project artifacts.

## Incremental build model

`ProjectVersion` is an immutable selection of one `ArtifactVersion` per logical artifact plus an optional timeline artifact. `ArtifactEdge` points from an input version to a dependent output version and assigns `hard`, `validate`, `soft`, or `none` invalidation behavior.

`video_change_preview` records a `ChangeRequest` against one base project version and deterministically partitions the current graph into rebuild, validate, and reuse sets. It topologically orders rebuild work and estimates its cost. `video_rebuild_apply` requires the preview's base version and an idempotency key. Concurrent work based on a stale version receives HTTP 409.

`VideoBuildRuntime.execute_build` invokes a provider/workflow adapter with a stable per-artifact idempotency key, validates planned and newly generated artifacts, and commits all replacements in one database transaction. A failure leaves the old project version selected; retrying a completed Build returns the committed version.

## Initial video build

`video_project_create`, `video_project_plan`, and `video_project_build` add the first-build path without adding another agent loop. Cuti Harness produces a provider-neutral `VideoSpec`; a Workflow Plugin compiles it into the same persisted `BuildPlan` vocabulary used by incremental and export work. A plan contains stable step identities, capabilities, dependencies, idempotency keys, output artifact identities, and estimated costs.

Selectable Workflow Skills (`seedance2`, `mv`, `short-drama-workflow`, `cuti-product-workflow`, `cuti-scenario-product-workflow`) compile a `VideoSpec` into that `BuildPlan`. Each successful step is saved as a draft and can be reused after restart. The active project version changes only after all media and validation steps pass.

`cuti.atomic-providers` reuses Cuti image, music, and Seedance providers. `cuti.media-core` reuses Cuti's TTS, Media Service, and FFmpeg-facing operations. `cuti.continuity-validator` always checks timeline and media structure, probes the final output for decodability, duration and audio, and can opt into Cuti's existing VLM video-consistency check. MP4 export of an already assembled immutable version is a durable zero-copy export; format conversion remains an export build.

## Plugin model

A plugin directory contains `video-plugin.yaml` and a Python entry point. The manifest declares its API and data versions, capabilities, workflows, styles, validators, media operators, Skill dependencies, plugin dependencies, network and credential requirements, sandbox requirement, cost ceiling, and optional Cordis or frontend contribution.

The runtime calls `on_load`, planning hooks, execution hooks, artifact validation and commit hooks, `migrate`, and `on_unload`. `VIDEO_PLUGIN_PATHS` limits discovery to configured roots. Trusted built-ins may run in-process. An untrusted plugin declares a sandbox image, entrypoint, and timeout; its module is never imported into the Runtime process and its bundle is forwarded to the imported Cuti Sandbox Worker.

Instruction-only Skills remain independently installable. A Skill becomes a plugin bundle only when it contributes executable code, a provider, validation, migration, or another runtime lifecycle behavior.

The process owns one `VideoSkillRuntime` for all instruction, Director, executable Capability, and Workflow Skills. It discovers `skills/system`, `skills/builtin`, `skills/external`, and `kit/skills/stages`, eagerly validates metadata, and lazily reads bodies and executable contracts through one `SkillCatalog`. The Workflow Registry validates pipeline permissions, Capability names, and Skill dependencies, then `cuti.skill-workflows` exposes those declarations as Workflow Plugin contributions. The BFF serves this catalog to the existing Cuti Skill UI, accepts `workflow_id` and `activated_skill_ids`, persists long-lived `ProjectSkillLock` records in the Video Runtime, and reloads the unified Runtime after safe ZIP installation. The selected Workflow, its dependencies, explicitly activated Skills, per-step Director Skills, project locks, and Capability-bound Skill are resolved before a Build is saved. Each `BuildStep` freezes Skill identity, version, full-file hash, roles, hooks, and applied instructions and exposes the resolved Skill names in production progress; Provider prompts consume that frozen context and artifacts record its provenance. Missing or disabled required Skills fail instead of falling back to direct path reads. `/api/video/workflows` exposes the effective Workflow catalog.

## Execution authorization

Cuti Harness's tool pipeline authorizes the eleven model-facing operations. Every nested provider, Skill script, sandbox operation, and media operator registered with the Video Runtime executes through `RuntimeCapabilityRegistry` and `CapabilityExecutionGateway`.

The gateway verifies an HMAC-signed, short-lived grant whose identity includes project, Session, user, plugin, and capability. The grant also limits network domains, cost, timeout, concurrency, retries, idempotency, audit identity, and cancellation identity. A plugin cannot expand the grant beyond its own manifest, and an operation must explicitly assert the domain before network access.

## HTTP API

The API is rooted at `/api/video`. It creates and inspects projects, lists installed plugins and effective workflows, persists and reads initial plans, starts, reads, cancels, or resumes builds, exposes per-step and validation state, previews changes, applies rebuilds, selects artifact versions, exports fixed project versions, lists or restores project versions, and streams project events. Modifying calls are idempotent. Events use a per-project monotonically increasing sequence and accept `after` for reconnect.

The imported `/chat-v1/service/v2` and `/chat-v1/service/studio` APIs remain available in the combined Cuti application during migration. When `VIDEO_AGENT_BACKEND=deepseek`, the compatibility BFF keeps the core `/chat-v1/service/v2` run, message, event, cancel, artifact-selection, and usage paths while translating them to native Harness Session RPC and Video Runtime state. It projects answer text, model identity and token usage, decision-step boundaries, named tool inputs and results, terminal state, and Runtime Build steps for the Video Studio progress view; private reasoning and system instructions are not projected. A message sent to a project with no artifacts or Builds receives the automatic `video_project_plan` then `video_project_build` instruction, while established projects retain conversational edit behavior. A project whose historical Harness Session was removed remains in the run list with empty conversation history, so one orphaned binding cannot hide other projects. The standalone Video Runtime mounts the same compatibility routes for local deployment.

## Runtime selection

`VIDEO_AGENT_BACKEND` accepts only `deepseek`. Product startup mounts the Harness compatibility BFF, loads the configured Video Plugins and Skill Workflows, and submits structured Workflow or Rebuild plans to `VideoBuildRuntime`. Cuti Harness is the only planning loop; provider tools do not start a second planner. `VIDEO_INCREMENTAL_ENGINE_ENABLED` remains a compatibility deployment control for the normalized project repository and defaults to enabled; plugin dispatch is not optional on the new path.

Imported Cuti media services still provide Provider and media implementation code. Their Skill-backed prompts resolve through the same process-owned catalog rather than reading stage directories directly.

## Integration status

The repository includes the Cuti Harness tool composition, project runtime, real Postgres migration, incremental executor, plugin lifecycle, authorization gateway, compatibility BFF, Cuti atomic Provider adapter, isolated Sandbox Worker, and Video Studio project UI. The Create workspace uses one generic Artifact renderer for both direct Provider results and complete video workflows. Runtime drafts and selected versions are classified as documents, stories, images, videos, audio, or other artifacts; the newest image or video is promoted as the latest result, and video cards support frame extraction. This workspace does not include the specialized `VideoResultsPanel` or legacy thread aggregation requests. The standalone service supports a bearer-token identity adapter, and local self-host uses `local-user`. Production deployments provide actual provider credentials and deployment-specific secrets rather than committing them.

For local self-hosting, `ACCOUNT_BACKEND=env` reads provider accounts directly from `OPENAI_API_KEY`, `WAVESPEED_API_KEY`, `SUNO_API_KEY`, and the other optional provider variables. `deploy/compose.video.yml` enables the bundled plugin directory, the imported Media Service, and a shared local-media volume served by Video Runtime at `/files`; S3 credentials are not required for the local profile. The compose profile uses a local-only capability-grant secret, which production must replace. Existing private environment files can be supplied without copying them into the repository, for example with `docker compose --env-file ../cuti-video-agent/.env -f deploy/compose.video.yml up`. When Windows uses a local HTTP proxy, the Node-based Cuti Harness process must also receive `HTTP_PROXY`, `HTTPS_PROXY`, and `NODE_USE_ENV_PROXY=1`; otherwise Python provider calls may work while Harness model calls time out.

The migration and repository-restart path has been exercised against local PostgreSQL. A real low-cost GPT Image + Seedance build continued through tail-frame extraction, timeline assembly, FFprobe validation, atomic `ProjectVersion` commit, zero-copy MP4 export, Cuti Harness tool inspection, and playable Video Studio preview. The imported Video Studio still carries its pre-existing lint debt; migration-owned frontend files lint cleanly and the production build succeeds. Skill listing, project enablement, structured selection, and ZIP installation now use the Video Runtime BFF; unrelated legacy administrative routes remain only in the imported compatibility application.
