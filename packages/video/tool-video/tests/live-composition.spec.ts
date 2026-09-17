import { afterEach, expect, it, vi } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import Include from '@deepseek-ai/cordis-plugin-include'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import { CallId } from '@deepseek-ai/dsh-llm'
import HttpVideoRuntime from '@cuti-ai/video-runtime-http'
import * as videoTools from '../src/index.ts'

let ctx: Context | undefined
afterEach(async () => {
  await ctx?.fiber.dispose()
  vi.unstubAllGlobals()
})

it('loads video tools through YAML and transports a live edit with pending cancellation', async () => {
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (options.body != null && typeof options.body !== 'string') throw new Error('Expected JSON request text')
    calls.push({
      path: new URL(url).pathname, method: options.method ?? 'GET',
      body: options.body ? JSON.parse(options.body) as Record<string, unknown> : {},
    })
    return Response.json({ data: url.endsWith('/live')
      ? { id: 'checkpoint-2', phase: 'live:2', next_phase: 'agent_execution', artifact_summaries: [], base_plan_revision: 2, base_spec_revision: 2 }
      : { planId: 'plan-1', planRevision: 3, currentPhase: 'agent_execution' } })
  }))
  ctx = new Context()
  await ctx.plugin(Loader)
  ctx.loader.builtins.include = Include
  const modules = new Map<string, unknown>([
    ['@deepseek-ai/dsh-system-prompt', SystemPrompt],
    ['@deepseek-ai/dsh-tools', ToolRuntime],
    ['@cuti-ai/video-runtime-http', HttpVideoRuntime],
    ['@cuti-ai/tool-video', videoTools],
  ])
  ctx.loader.internal = {
    version: 'v2',
    async import(specifier: string) {
      if (!modules.has(specifier)) throw new Error(`Unknown test plugin: ${specifier}`)
      return modules.get(specifier)
    },
  } as unknown as NonNullable<typeof ctx.loader.internal>
  await ctx.loader.create({
    name: 'cordis:include', config: { path: new URL('./fixtures/live.cordis.yml', import.meta.url).href },
  })
  await ctx.loader.await()
  const inspect = await ctx.tools.execute({
    callId: CallId('live-inspect'), name: 'video_checkpoint_inspect',
    arguments: { project_id: 'project-1', build_id: 'build-1', checkpoint_id: 'live' },
    signal: new AbortController().signal,
  })
  expect(inspect.isError).toBe(false)
  expect(inspect.content).toMatchInlineSnapshot(`
    [
      {
        "text": "Use base_plan_revision as base_revision and base_spec_revision unchanged in video_plan_patch_submit.
    {\"id\":\"checkpoint-2\",\"phase\":\"live:2\",\"next_phase\":\"agent_execution\",\"artifact_summaries\":[],\"base_plan_revision\":2,\"base_spec_revision\":2}",
        "type": "text",
      },
    ]
  `)
  const patch = await ctx.tools.execute({
    callId: CallId('live-patch'), name: 'video_plan_patch_submit',
    arguments: {
      project_id: 'project-1', build_id: 'build-1', checkpoint_id: 'checkpoint-2',
      base_revision: 2, base_spec_revision: 2, idempotency_key: 'edit-1',
      cancel_task_ids: ['queued-shot'],
      replace_failed_task_ids: { 'failed-shot': 'replacement' },
      add_tasks: [{ client_key: 'replacement', capability_id: 'atomic.video.generate', objective: 'Replace shot', depends_on: ['running-reference'], parameters: { prompt: 'new shot' } }],
    },
    signal: new AbortController().signal,
  })
  expect(patch.isError).toBe(false)
  expect(calls.map(call => [call.method, call.path])).toMatchInlineSnapshot(`
    [
      [
        "POST",
        "/api/video/projects/project-1/builds/build-1/checkpoints/live",
      ],
      [
        "POST",
        "/api/video/projects/project-1/builds/build-1/checkpoints/checkpoint-2/resolve",
      ],
    ]
  `)
  expect(calls[1]?.body).toMatchObject({
    cancelStepIds: ['queued-shot'], basePlanRevision: 2, baseSpecRevision: 2,
    replaceFailedStepIds: { 'failed-shot': 'replacement' },
    proposedSteps: [{ step_id: 'replacement', depends_on: ['running-reference'] }],
  })
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: [
    { loc: ['body', 'basePlanRevision'], msg: 'Input should be greater than or equal to 1', input: 0 },
  ] }, { status: 422 })))
  const invalid = await ctx.tools.execute({
    callId: CallId('invalid-patch'), name: 'video_plan_patch_submit',
    arguments: { project_id: 'project-1', build_id: 'build-1', checkpoint_id: 'checkpoint-2',
      base_revision: 0, base_spec_revision: 0, idempotency_key: 'invalid', add_tasks: [] },
    signal: new AbortController().signal,
  })
  expect(invalid.isError).toBe(true)
  expect(JSON.stringify(invalid.content)).toContain('basePlanRevision')
  expect(JSON.stringify(invalid.content)).toContain('HTTP 422')
  expect(JSON.stringify(invalid.content)).not.toContain('[object Object]')
})
