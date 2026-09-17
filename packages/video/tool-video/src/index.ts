/** Model-facing tools for project-oriented incremental video construction. @module @cuti-ai/tool-video */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { RequestIdentity, VideoSpec } from '@cuti-ai/video-runtime'

export const name = 'cuti-tool-video'
export const inject = ['tools', 'videoRuntime']

/** Preserve scalar display and serialize structured Runtime values without losing their fields. */
function displayValue(value: unknown): string {
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const projectOutput = {
  type: 'object' as const,
  additionalProperties: false,
  properties: {
    projectId: { type: 'string' as const, required: true },
    title: { type: 'string' as const, required: true },
    status: { type: 'string' as const, required: true },
    currentVersionId: { type: 'string' as const, required: true },
    artifactCount: { type: 'integer' as const, required: true },
    activeBuildIds: { type: 'array' as const, required: true, items: { type: 'string' as const } },
    summary: { type: 'string' as const, required: true },
  },
} as const

const buildOutput = {
  type: 'object' as const,
  additionalProperties: false,
  properties: {
    buildId: { type: 'string' as const, required: true },
    projectId: { type: 'string' as const, required: true },
    status: {
      type: 'string' as const,
      required: true,
      enum: ['queued', 'running', 'waiting_external', 'waiting_agent', 'completed', 'failed', 'cancelled'],
    },
    progress: { type: 'number' as const, required: true },
    message: { type: 'string' as const, required: true },
    projectVersionId: { type: 'string' as const },
    kind: { type: 'string' as const, enum: ['initial', 'incremental', 'export'] },
    estimatedCost: { type: 'number' as const },
    actualCost: { type: 'number' as const },
    error: { type: 'string' as const },
  },
} as const

const languageContractParameters = {
  type: 'object' as const,
  required: true,
  additionalProperties: false,
  description: 'Persisted language choices. UI/content/speech/subtitles are independent; preserve this object in every PlanPatch.',
  properties: {
    ui_locale: { type: 'string' as const, required: true, enum: ['zh-CN', 'en-US'] },
    content_language: { type: 'string' as const, required: true, enum: ['zh-CN', 'en-US'] },
    spoken_language: { type: 'string' as const, required: true, enum: ['zh-CN', 'en-US'] },
    subtitle_language: { type: 'string' as const, required: true, enum: ['zh-CN', 'en-US'] },
    provider_prompt_language: {
      type: 'string' as const,
      required: true,
      enum: ['auto', 'zh-CN', 'en-US'],
    },
  },
} as const

const projectIntentParameters = {
  type: 'object' as const,
  additionalProperties: false,
  properties: {
    title: { type: 'string' as const, required: true },
    brief: { type: 'string' as const, required: true },
    language: { type: 'string' as const, required: true },
    language_contract: languageContractParameters,
    target_duration_seconds: { type: 'number' as const, required: true },
    aspect_ratio: { type: 'string' as const, required: true, enum: ['16:9', '9:16', '1:1'] },
    resolution: { type: 'string' as const, required: true },
    workflow_id: { type: 'string' as const, required: true },
    style_id: { type: 'string' as const, required: true },
    activated_skill_ids: { type: 'array' as const, items: { type: 'string' as const } },
    source_asset_ids: { type: 'array' as const, items: { type: 'string' as const } },
    workflow_parameters: { type: 'object' as const, additionalProperties: true },
    providers: {
      type: 'object' as const, required: true, additionalProperties: false, properties: {
        video: { type: 'string' as const, required: true },
        image: { type: 'string' as const, required: true },
        music: { type: 'string' as const, required: true },
      },
    },
    automation: {
      type: 'object' as const, required: true, additionalProperties: false, properties: {
        mode: { type: 'string' as const, required: true, enum: ['automatic'] },
        max_artifact_retries: { type: 'integer' as const, required: true },
      },
    },
    constraints: { type: 'object' as const, additionalProperties: true },
  },
} as const

const videoSpecParameters = {
  type: 'object' as const,
  additionalProperties: false,
  properties: {
    title: { type: 'string' as const, required: true },
    language: { type: 'string' as const, required: true },
    language_contract: languageContractParameters,
    target_duration_seconds: { type: 'number' as const, required: true },
    aspect_ratio: { type: 'string' as const, required: true, enum: ['16:9', '9:16', '1:1'] },
    resolution: { type: 'string' as const, required: true },
    workflow_id: {
      type: 'string' as const,
      required: true,
      description: 'Installed Video Runtime workflow id. Legacy Cuti workflow SKILL.md names are valid when installed.',
    },
    style_id: { type: 'string' as const, required: true },
    activated_skill_ids: {
      type: 'array' as const,
      items: { type: 'string' as const },
      description: 'Optional helper Skills the user or a project lock explicitly pinned. Do not list helpers that a workflow named via video_skill_load.',
    },
    source_asset_ids: {
      type: 'array' as const,
      items: { type: 'string' as const },
      description: 'Project-owned uploaded source artifact ids. Never invent ids or pass arbitrary URLs.',
    },
    workflow_parameters: {
      type: 'object' as const,
      additionalProperties: true,
      description: 'Workflow-specific structured parameters returned by video_workflow_load.',
    },
    characters: {
      type: 'array' as const, required: true, items: {
        type: 'object' as const, additionalProperties: false, properties: {
          id: { type: 'string' as const, required: true },
          name: { type: 'string' as const, required: true },
          appearance: { type: 'string' as const, required: true },
          clothing: { type: 'string' as const },
          personality: { type: 'string' as const },
          voice: { type: 'string' as const },
        },
      },
    },
    shots: {
      type: 'array' as const, required: true, items: {
        type: 'object' as const, additionalProperties: false, properties: {
          id: { type: 'string' as const, required: true },
          order: { type: 'integer' as const, required: true },
          duration_seconds: { type: 'number' as const, required: true },
          beat: { type: 'string' as const, required: true },
          visual_prompt: { type: 'string' as const, required: true },
          // Models commonly use JSON null for an intentionally absent
          // voice-over. Accept that harmless representation at the tool
          // boundary and remove it before calling the strict Runtime model.
          narration: {
            oneOf: [
              { type: 'string' as const },
              { type: 'null' as const },
            ],
          },
          character_ids: { type: 'array' as const, items: { type: 'string' as const } },
          reference_asset_ids: { type: 'array' as const, items: { type: 'string' as const } },
          transition: { type: 'string' as const },
        },
      },
    },
    audio: {
      type: 'object' as const, required: true, additionalProperties: false, properties: {
        narration_voice: { type: 'string' as const, required: true },
        bgm_prompt: { type: 'string' as const, required: true },
        subtitles: { type: 'boolean' as const, required: true },
      },
    },
    providers: {
      type: 'object' as const, required: true, additionalProperties: false, properties: {
        video: { type: 'string' as const, required: true },
        image: { type: 'string' as const, required: true },
        music: { type: 'string' as const, required: true },
      },
    },
    automation: {
      type: 'object' as const, required: true, additionalProperties: false, properties: {
        mode: { type: 'string' as const, required: true, enum: ['automatic'] },
        max_artifact_retries: { type: 'integer' as const, required: true },
      },
    },
  },
} as const

function normalizeVideoSpec(value: unknown): VideoSpec {
  const spec = value as Omit<VideoSpec, 'shots'> & {
    shots: Array<Omit<VideoSpec['shots'][number], 'narration'> & { narration?: string | null }>
  }
  return {
    ...spec,
    shots: spec.shots.map((shot) => {
      if (shot.narration !== null) return shot
      const { narration: _omitted, ...withoutNullNarration } = shot
      return withoutNullNarration
    }),
  }
}

function identityOf(agent: { session: { header: { id: unknown } } } | undefined): RequestIdentity {
  return agent === undefined ? {} : { sessionId: displayValue(agent.session.header.id) }
}

function withoutInjectedResources(
  value: Record<string, import('@cuti-ai/video-runtime').JsonValue>,
): Record<string, import('@cuti-ai/video-runtime').JsonValue> {
  const { resourceContents: _ignored, ...rest } = value
  return rest
}

function bundledResourceHeader(value: Record<string, import('@cuti-ai/video-runtime').JsonValue>): string {
  const resources = Array.isArray(value.resources) ? value.resources.map(item => displayValue(item)) : []
  if (resources.length === 0) return ''
  const owner = displayValue(value.resourceOwnerSkillId ?? value.id ?? '')
  return [
    `RESOURCE OWNER (mandatory): ${displayValue(owner)}`,
    `Every resource path listed below belongs to ${displayValue(owner)}.`,
    `Read it only with video_skill_read_resource using skill_id=${displayValue(owner)}; never use a dependency Skill id.`,
    'Resources:',
    ...resources.map(path => `- ${displayValue(path)}`),
    '',
  ].join('\n')
}

function projectText(value: { projectId: string; currentVersionId: string; artifactCount: number; summary: string }): string {
  return `Video project ${displayValue(value.projectId)} at ${displayValue(value.currentVersionId)}: ${displayValue(value.artifactCount)} artifacts. ${displayValue(value.summary)}`
}

function buildText(value: { buildId: string; status: string; progress: number; message: string }): string {
  const next = ['queued', 'running', 'waiting_external'].includes(value.status)
    ? ' Work remains active. Continue with video_build_status; do not end the request with a promise to finish later.'
    : value.status === 'completed'
      ? ' Inspect the resulting artifacts. If this was an intermediate step (such as transcription), plan and apply the next step until the requested deliverable exists.'
      : ''
  return `Video build ${displayValue(value.buildId)}: ${displayValue(value.status)} (${Math.round(value.progress * 100)}%). ${displayValue(value.message)}${next}`
}

/** Register the stable high-level tool surface; provider-specific operations stay behind the runtime. */
export function apply(ctx: Context): void {
  ctx.tools.register(defineTool({
    name: 'video_workflow_list',
    description: 'List Video Runtime workflows before planning. In automatic mode choose only an available user-selectable workflow whose description matches the user request. Never use a hidden compatibility workflow or invent a compiler.',
    parameters: {},
    output: {
      schema: { type: 'array', items: { type: 'object', additionalProperties: true } },
      render: (_args, value) => [{
        type: 'text',
        text: value.map((item) => {
          const availability = item.available ? 'available' : `unavailable (${displayValue(item.unavailableReason)})`
          const compiler = item.compiler == null ? 'none' : displayValue(item.compiler)
          return `${displayValue(item.id)}: ${displayValue(availability)}; selectable=${displayValue(item.userSelectable)}; mode=${displayValue(item.mode)}; execution=${displayValue(item.executionKind)}; compiler=${displayValue(compiler)} — ${displayValue(item.description)}`
        }).join('\n'),
      }],
    },
    execute: (_args, exec) => ctx.videoRuntime.listWorkflows(identityOf(exec.agent), exec.signal)
      .then(value => value as unknown as Array<Record<string, import('@cuti-ai/video-runtime').JsonValue>>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_workflow_load',
    description: 'Load the authoritative instructions and execution contract for one selected available video workflow. Call this before constructing VideoSpec. Then call video_skill_load for every returned skillDependencies entry and for any additional Skill named by the instructions. Any returned resource path belongs to resourceOwnerSkillId (normally the workflow id), not to the most recently loaded dependency.',
    parameters: { workflow_id: { type: 'string', required: true } },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `${displayValue(value.title)}\nMode: ${displayValue(value.mode)}\nExecution: ${displayValue(value.executionKind)}\nCompiler: ${displayValue(value.compiler == null ? 'none' : displayValue(value.compiler))}\nPipeline: ${displayValue(Array.isArray(value.pipeline) ? value.pipeline.map(displayValue).join(' -> ') : '')}\n${bundledResourceHeader(value)}Required Skill dependencies (load each with video_skill_load): ${displayValue(Array.isArray(value.skillDependencies) && value.skillDependencies.length > 0 ? value.skillDependencies.map(displayValue).join(', ') : 'none')}\n\nRUNTIME VIDEO MODEL CAPABILITIES (authoritative execution facts; narrative shots are not provider calls):\n${JSON.stringify(value.videoModelCapabilities ?? [], null, 2)}\n\nAUTHORITATIVE WORKFLOW INSTRUCTIONS:\n${displayValue(value.instructions ?? '')}`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.loadWorkflow(args.workflow_id, identityOf(exec.agent), exec.signal)
      .then(value => withoutInjectedResources(value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>)),
  }))

  ctx.tools.register(defineTool({
    name: 'video_skill_load',
    description: "Load one installed Skill's full Markdown instructions after it is selected, named by another Skill, or explicitly requested. Returns resourceOwnerSkillId and bundled paths; read each path with video_skill_read_resource using that exact owner id.",
    parameters: { skill_id: { type: 'string', required: true } },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `${displayValue(value.id)}\n${bundledResourceHeader(value)}AUTHORITATIVE SKILL INSTRUCTIONS:\n${displayValue(value.instructions ?? '')}`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.loadSkill(args.skill_id, identityOf(exec.agent), exec.signal)
      .then(value => withoutInjectedResources(value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>)),
  }))

  ctx.tools.register(defineTool({
    name: 'video_skill_read_resource',
    description: 'Read one bundled text file from an installed Skill when its instructions require that file. Pass the resourceOwnerSkillId returned alongside the path; never substitute a dependency or the most recently loaded Skill id.',
    parameters: {
      skill_id: { type: 'string', required: true },
      path: { type: 'string', required: true },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: `${displayValue(value.path)}\n\n${displayValue(value.content)}` }],
    },
    execute: (args, exec) => ctx.videoRuntime.loadSkillResource(
      args.skill_id, args.path, identityOf(exec.agent), exec.signal,
    ).then(value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_project_create',
    description: 'Create a durable empty video project and bind it to the current session.',
    parameters: {
      title: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
    },
    output: { schema: projectOutput, render: (_args, value) => [{ type: 'text', text: projectText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.createProject({
      title: args.title, idempotencyKey: args.idempotency_key,
    }, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_project_plan',
    description: 'Create the first durable phase of a video BuildPlan. Prefer project_intent when later creative decisions depend on generated media; provide exactly one of project_intent or video_spec.',
    parameters: {
      project_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
      project_intent: projectIntentParameters,
      video_spec: videoSpecParameters,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Initial video plan ${displayValue(value.planId)}: ${displayValue(value.shotCount)} shots, estimated cost $${displayValue(value.estimatedCost)}.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.planProject({
      projectId: args.project_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
      ...(args.video_spec === undefined ? {} : { videoSpec: normalizeVideoSpec(args.video_spec) }),
      ...(args.project_intent === undefined ? {} : { projectIntent: args.project_intent }),
    }, identityOf(exec.agent), exec.signal).then(
      value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>,
    ),
  }))

  ctx.tools.register(defineTool({
    name: 'video_project_build',
    description: 'Start a persisted initial video BuildPlan immediately in fully automatic mode.',
    parameters: {
      project_id: { type: 'string', required: true },
      plan_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
    },
    output: { schema: buildOutput, render: (_args, value) => [{ type: 'text', text: buildText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.startBuild({
      projectId: args.project_id,
      planId: args.plan_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
    }, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_project_open',
    description: 'Open an existing video project and return its current immutable version summary.',
    parameters: { project_id: { type: 'string', required: true, description: 'Opaque video project id.' } },
    output: { schema: projectOutput, render: (_args, value) => [{ type: 'text', text: projectText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.openProject(args.project_id, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_project_inspect',
    description: 'Inspect the current video project version, artifact count, active builds, and concise status.',
    parameters: { project_id: { type: 'string', required: true } },
    output: { schema: projectOutput, render: (_args, value) => [{ type: 'text', text: projectText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.inspectProject(args.project_id, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_artifact_list',
    description: 'List the currently selected, project-owned Artifacts that may be used as inputs to a dynamic edit. Call this before proposing any edit to an existing video; use only returned artifactVersionId values.',
    parameters: { project_id: { type: 'string', required: true } },
    output: {
      schema: { type: 'array', items: { type: 'object', additionalProperties: true } },
      render: (_args, value) => [{
        type: 'text',
        text: value.length === 0
          ? 'This video project has no selected Artifacts.'
          : value.map(item => `${displayValue(item.artifactVersionId)}: ${displayValue(item.logicalId)} (${displayValue(item.type)}) — ${displayValue(item.title || item.summary || '')}`).join('\n'),
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.listArtifacts(
      args.project_id, identityOf(exec.agent), exec.signal,
    ).then(value => value as unknown as Array<Record<string, import('@cuti-ai/video-runtime').JsonValue>>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_plan_patch_capability_list',
    description: 'List enabled capabilities with parameters_schema. Call this after loading the Workflow and before proposing PlanPatch tasks. Copy each capability\'s parameters_schema; do not invent keys. add_tasks must still be allowed on the current Workflow.',
    parameters: {},
    output: {
      schema: { type: 'array', items: { type: 'object', additionalProperties: true } },
      render: (_args, value) => [{
        type: 'text',
        text: JSON.stringify(value, null, 2),
      }],
    },
    execute: (_args, exec) => ctx.videoRuntime.listPlanPatchCapabilities(
      identityOf(exec.agent), exec.signal,
    ).then(value => value as unknown as Array<Record<string, import('@cuti-ai/video-runtime').JsonValue>>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_change_preview',
    description: 'Preview the deterministic impact of a requested project change without modifying the project.',
    parameters: {
      project_id: { type: 'string', required: true },
      change: { type: 'string', required: true, description: 'Concrete requested change.' },
      target_artifact_version_ids: { type: 'array', items: { type: 'string' } },
      idempotency_key: { type: 'string', required: true },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false, properties: {
          planId: { type: 'string', required: true },
          projectId: { type: 'string', required: true },
          baseProjectVersionId: { type: 'string', required: true },
          staleArtifactIds: { type: 'array', required: true, items: { type: 'string' } },
          validationArtifactIds: { type: 'array', required: true, items: { type: 'string' } },
          reusedArtifactIds: { type: 'array', required: true, items: { type: 'string' } },
          rebuildOrder: { type: 'array', required: true, items: { type: 'string' } },
          estimatedCost: { type: 'number', required: true },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: `Rebuild plan ${displayValue(value.planId)}: ${displayValue(value.staleArtifactIds.length)} stale, ${displayValue(value.validationArtifactIds.length)} validate, ${displayValue(value.reusedArtifactIds.length)} reusable; estimated cost ${displayValue(value.estimatedCost)}.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.previewChange({
      projectId: args.project_id,
      change: args.change,
      targetArtifactVersionIds: args.target_artifact_version_ids ?? [],
      idempotencyKey: args.idempotency_key,
    }, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_edit_preview',
    description: 'Resolve creative VideoSpec edits (character, scene, shot, music intent, timeline, or regeneration) into an executable incremental plan while preserving the selected generation Workflow. When changing total duration, first inspect the project, then send patch_timeline.patch.target_duration_seconds together with patch.shots: partial records for every resized existing shot and complete id/order/duration_seconds/beat/visual_prompt records for every new shot. The Runtime will not stretch clips or invent missing creative content. For post-production such as subtitles, captions, audio mixing, extraction, concatenation, or lipsync use video_plan_patch_preview instead. After preview, execute the requested edit without a second confirmation.',
    parameters: {
      project_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
      description: { type: 'string', required: true },
      edits: {
        type: 'array', required: true, items: {
          type: 'object', additionalProperties: true, properties: {
            type: {
              type: 'string', required: true,
              enum: ['patch_character', 'patch_scene', 'patch_shot', 'regenerate_artifact', 'replace_music', 'patch_timeline'],
            },
            id: { type: 'string' },
            artifactVersionId: { type: 'string' },
            prompt: { type: 'string' },
            patch: { type: 'object', additionalProperties: true, properties: {} },
          },
        },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Edit plan ${displayValue(value.planId)}: ${displayValue(Array.isArray(value.steps) ? value.steps.filter(step => typeof step === 'object' && step !== null && !Array.isArray(step) && step.action === 'rebuild').length : 0)} rebuild steps, estimated cost $${displayValue(value.estimatedCost)}. Apply this requested plan immediately with video_rebuild_apply; no second confirmation is needed.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.previewEdits({
      projectId: args.project_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
      description: args.description,
      edits: args.edits,
    }, identityOf(exec.agent), exec.signal).then(
      value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>,
    ),
  }))

  ctx.tools.register(defineTool({
    name: 'video_plan_patch_preview',
    description: 'Preview a Harness-wide dynamic PlanPatch against currently selected project Artifacts. First call video_artifact_list and video_plan_patch_capability_list, then load any recommended Skill. Chain steps by operation_step_id. After preview, call video_rebuild_apply immediately for the requested operation. No second confirmation is needed. Never switch or recompile the generation Workflow for subtitles, captions, trimming, mixing, concatenation, frame extraction, or lipsync.',
    parameters: {
      project_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
      description: { type: 'string', required: true },
      operations: {
        type: 'array', required: true, items: {
          type: 'object', additionalProperties: false, properties: {
            step_id: { type: 'string', required: true },
            capability: { type: 'string', required: true },
            inputs: {
              type: 'array', required: true, items: {
                type: 'object', additionalProperties: false, properties: {
                  role: { type: 'string', required: true },
                  artifact_version_id: { type: 'string' },
                  operation_step_id: { type: 'string' },
                },
              },
            },
            parameters: { type: 'object', additionalProperties: true, properties: {} },
            title: { type: 'string' },
          },
        },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Dynamic media plan ${displayValue(value.planId)}: ${displayValue(Array.isArray(value.steps) ? value.steps.length : 0)} steps, estimated cost $${displayValue(value.estimatedCost)}. Apply this requested plan immediately with video_rebuild_apply; no second confirmation is needed.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.previewPlanPatch({
      projectId: args.project_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
      description: args.description,
      operations: args.operations,
    }, identityOf(exec.agent), exec.signal).then(
      value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>,
    ),
  }))

  ctx.tools.register(defineTool({
    name: 'video_rebuild_apply',
    description: 'Apply the user-requested rebuild plan against its exact base project version without a second confirmation. Continue tracking the build and completing dependent steps.',
    parameters: {
      project_id: { type: 'string', required: true },
      plan_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
    },
    output: { schema: buildOutput, render: (_args, value) => [{ type: 'text', text: buildText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.applyRebuild({
      projectId: args.project_id,
      planId: args.plan_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
    }, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_build_status',
    description: 'Read the authoritative status of a durable video build.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
    },
    output: { schema: buildOutput, render: (_args, value) => [{ type: 'text', text: buildText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.getBuild(args.project_id, args.build_id, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_checkpoint_inspect',
    description: 'Inspect a durable planning checkpoint. For a user edit during an active continuous build, use checkpoint_id="live" to open or reuse a planning snapshot without waiting for task completion. Submit the returned checkpoint id and revisions in video_plan_patch_submit.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
      checkpoint_id: { type: 'string', required: true },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Use base_plan_revision as base_revision and base_spec_revision unchanged in video_plan_patch_submit.\n${JSON.stringify(value)}`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.inspectCheckpoint(
      args.project_id, args.build_id, args.checkpoint_id, identityOf(exec.agent), exec.signal,
    ).then(value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_checkpoint_resolve',
    description: 'Resolve a planning checkpoint with creative fields and tasks. Continuous builds accept additions and pending-task cancellations while unrelated work is running; staged builds use their Workflow compiler.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
      checkpoint_id: { type: 'string', required: true },
      base_plan_revision: { type: 'integer', required: true },
      base_spec_revision: { type: 'integer', required: true },
      idempotency_key: { type: 'string', required: true },
      video_spec: videoSpecParameters,
      video_spec_patch: {
        type: 'object', additionalProperties: true,
        description: 'Partial VideoSpec fields resolved at this checkpoint. Use instead of video_spec.',
      },
      phase_inputs: { type: 'object', additionalProperties: true },
      proposed_steps: {
        type: 'array', items: {
          type: 'object', additionalProperties: false, properties: {
            step_id: { type: 'string', required: true },
            action: { type: 'string', required: true, enum: ['create', 'validate'] },
            capability: { type: 'string', required: true },
            objective: { type: 'string' },
            input_artifact_version_ids: { type: 'array', items: { type: 'string' } },
            output_artifact_id: { type: 'string' },
            output_artifact_type: { type: 'string' },
            parameters: { type: 'object', additionalProperties: true },
            depends_on: { type: 'array', items: { type: 'string' } },
            idempotency_key: { type: 'string' },
            estimated_cost: { type: 'number' },
            reason: { type: 'string' },
            skill_ids: { type: 'array', items: { type: 'string' } },
          },
        },
        description: 'Tasks may depend on existing tasks or tasks added in this patch. Only ready tasks execute. Use an empty list to acknowledge an update while other tasks continue.',
      },
      cancel_step_ids: { type: 'array', items: { type: 'string' } },
      goal_satisfied: { type: 'boolean' },
      waiting_for_input: { type: 'boolean' },
      response: { type: 'string' },
      reason: { type: 'string' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Resolved checkpoint; plan ${displayValue(value.planId)} revision ${displayValue(value.planRevision)} now runs phase ${displayValue(value.currentPhase)}.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.resolveCheckpoint({
      projectId: args.project_id,
      buildId: args.build_id,
      checkpointId: args.checkpoint_id,
      basePlanRevision: args.base_plan_revision,
      baseSpecRevision: args.base_spec_revision,
      idempotencyKey: args.idempotency_key,
      ...(args.video_spec === undefined ? {} : { videoSpec: normalizeVideoSpec(args.video_spec) }),
      ...(args.video_spec_patch === undefined ? {} : { videoSpecPatch: args.video_spec_patch }),
      ...(args.phase_inputs === undefined ? {} : { phaseInputs: args.phase_inputs }),
      ...(args.proposed_steps === undefined ? {} : { proposedSteps: args.proposed_steps }),
      ...(args.cancel_step_ids === undefined ? {} : { cancelStepIds: args.cancel_step_ids }),
      ...(args.goal_satisfied === undefined ? {} : { goalSatisfied: args.goal_satisfied }),
      ...(args.waiting_for_input === undefined ? {} : { waitingForInput: args.waiting_for_input }),
      ...(args.response === undefined ? {} : { response: args.response }),
      ...(args.reason === undefined ? {} : { reason: args.reason }),
    }, identityOf(exec.agent), exec.signal).then(
      value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>,
    ),
  }))

  ctx.tools.register(defineTool({
    name: 'video_plan_patch_submit',
    description: 'Submit a Cuti PlanPatch after a task completion, failure, or user edit. Add tasks and dependencies or cancel pending tasks while other work runs. For every video-generation task, parameters.prompt must be the duration-aware final provider prompt, not a synopsis; later and repaired clips must preserve the relevant specificity of prior comparable clips visible in task parameters and Artifact generation_context. Persist planning documents whose final content is already known with runtime.artifact.persist; do not call atomic.text.generate just to repeat the Agent planning already done. Reserve atomic.text.generate for genuinely independent text generation or transformation. For user edits, first call video_checkpoint_inspect with checkpoint_id="live", then submit its returned id and revisions. goal_satisfied requires a playable result and no active tasks.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
      checkpoint_id: { type: 'string', required: true },
      base_revision: { type: 'integer', required: true },
      base_spec_revision: { type: 'integer', required: true },
      idempotency_key: { type: 'string', required: true },
      video_spec_patch: { type: 'object', additionalProperties: true },
      add_tasks: {
        type: 'array',
        items: {
          type: 'object', additionalProperties: false, properties: {
            client_key: { type: 'string', required: true },
            capability_id: { type: 'string', required: true },
            objective: { type: 'string', required: true },
            output_artifact_type: { type: 'string' },
            output_artifact_id: { type: 'string' },
            input_artifact_version_ids: { type: 'array', items: { type: 'string' } },
            parameters: { type: 'object', additionalProperties: true },
            depends_on: { type: 'array', items: { type: 'string' } },
            estimated_cost: { type: 'number' },
            skill_ids: { type: 'array', items: { type: 'string' } },
          },
        },
      },
      cancel_task_ids: { type: 'array', items: { type: 'string' } },
      replace_failed_task_ids: { type: 'object', additionalProperties: true, description: 'Map failed task IDs to new client_keys (string values) in add_tasks with corrected parameters. Runtime clones and rewires pending descendants atomically. For a failed Build, inspect checkpoint_id=live first; old work does not restart before this patch commits.' },
      goal_satisfied: { type: 'boolean' },
      waiting_for_input: { type: 'boolean' },
      response: { type: 'string' },
      reason: { type: 'string' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{
        type: 'text',
        text: `Accepted PlanPatch; plan ${displayValue(value.planId)} is now revision ${displayValue(value.planRevision)}.`,
      }],
    },
    execute: (args, exec) => ctx.videoRuntime.resolveCheckpoint({
      projectId: args.project_id,
      buildId: args.build_id,
      checkpointId: args.checkpoint_id,
      basePlanRevision: args.base_revision,
      baseSpecRevision: args.base_spec_revision,
      idempotencyKey: args.idempotency_key,
      videoSpecPatch: args.video_spec_patch ?? {},
      proposedSteps: (args.add_tasks ?? []).map(task => ({
        step_id: task.client_key,
        action: 'create',
        capability: task.capability_id,
        objective: task.objective,
        input_artifact_version_ids: task.input_artifact_version_ids ?? [],
        output_artifact_id: task.output_artifact_id ?? '',
        output_artifact_type: task.output_artifact_type ?? '',
        parameters: task.parameters ?? {},
        depends_on: task.depends_on ?? [],
        estimated_cost: task.estimated_cost ?? 0,
        reason: task.objective,
        skill_ids: task.skill_ids ?? [],
      })),
      cancelStepIds: args.cancel_task_ids ?? [],
      ...(args.replace_failed_task_ids === undefined ? {} : {
        replaceFailedStepIds: Object.fromEntries(Object.entries(args.replace_failed_task_ids).map(([key, value]) => {
          if (typeof value !== 'string') throw new Error('Replacement task IDs must be strings')
          return [key, value]
        })),
      }),
      goalSatisfied: args.goal_satisfied ?? false,
      waitingForInput: args.waiting_for_input ?? false,
      response: args.response ?? '',
      reason: args.reason ?? '',
    }, identityOf(exec.agent), exec.signal).then(
      value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>,
    ),
  }))

  ctx.tools.register(defineTool({
    name: 'video_build_retry_checkpoint',
    description: 'Retry automatic delivery of a failed semantic checkpoint. This does not regenerate media or create a new build.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
      checkpoint_id: { type: 'string', required: true },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: `Checkpoint ${displayValue(value.id)} is ${displayValue(value.status)}.` }],
    },
    execute: (args, exec) => ctx.videoRuntime.retryCheckpoint(
      args.project_id, args.build_id, args.checkpoint_id, identityOf(exec.agent), exec.signal,
    ).then(value => value as unknown as Record<string, import('@cuti-ai/video-runtime').JsonValue>),
  }))

  ctx.tools.register(defineTool({
    name: 'video_build_cancel',
    description: 'Request cancellation of a durable video build.',
    parameters: {
      project_id: { type: 'string', required: true },
      build_id: { type: 'string', required: true },
    },
    output: { schema: buildOutput, render: (_args, value) => [{ type: 'text', text: buildText(value) }] },
    execute: (args, exec) => ctx.videoRuntime.cancelBuild(args.project_id, args.build_id, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_artifact_select',
    description: 'Select one artifact version and atomically create a new immutable project version.',
    parameters: {
      project_id: { type: 'string', required: true },
      version_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false, properties: {
          projectId: { type: 'string', required: true },
          artifactId: { type: 'string', required: true },
          versionId: { type: 'string', required: true },
          projectVersionId: { type: 'string', required: true },
        },
      },
      render: (_args, value) => [{ type: 'text', text: `Selected artifact ${displayValue(value.artifactId)} version ${displayValue(value.versionId)}; project is now ${displayValue(value.projectVersionId)}.` }],
    },
    execute: (args, exec) => ctx.videoRuntime.selectArtifact({
      projectId: args.project_id,
      versionId: args.version_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
    }, identityOf(exec.agent), exec.signal),
  }))

  ctx.tools.register(defineTool({
    name: 'video_export',
    description: 'Export one exact immutable project version in the requested format.',
    parameters: {
      project_id: { type: 'string', required: true },
      base_project_version_id: { type: 'string', required: true },
      idempotency_key: { type: 'string', required: true },
      format: { type: 'string', required: true, enum: ['mp4', 'mov', 'webm', 'project'] },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false, properties: {
          exportId: { type: 'string', required: true },
          projectId: { type: 'string', required: true },
          status: { type: 'string', required: true, enum: ['queued', 'running', 'completed', 'failed', 'cancelled'] },
          uri: { type: 'string' },
        },
      },
      render: (_args, value) => [{ type: 'text', text: `Export ${displayValue(value.exportId)}: ${displayValue(value.status)}${displayValue(value.uri === undefined ? '' : ` at ${displayValue(value.uri)}`)}.` }],
    },
    execute: (args, exec) => ctx.videoRuntime.exportProject({
      projectId: args.project_id,
      baseProjectVersionId: args.base_project_version_id,
      idempotencyKey: args.idempotency_key,
      format: args.format,
    }, identityOf(exec.agent), exec.signal),
  }))
}
