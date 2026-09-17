import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { dirname, extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

// Runs the built Studio with only its network boundary scripted. No model or
// media provider is contacted. The module override supports shared test runtimes.
const { chromium } = await import(process.env.VIDEO_STUDIO_PLAYWRIGHT_MODULE || 'playwright')
const directory = dirname(fileURLToPath(import.meta.url))
const dist = resolve(directory, '../dist')
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname
  const path = resolve(dist, `.${pathname}`)
  if (!path.startsWith(dist + sep)) { response.writeHead(403).end(); return }
  try {
    const asset = extname(path) ? path : resolve(dist, 'index.html')
    const body = await readFile(asset)
    const type = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' }[extname(asset)]
    response.writeHead(200, { 'Content-Type': type || 'application/octet-stream' }).end(body)
  } catch { response.writeHead(404).end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
let browser
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.VIDEO_STUDIO_BROWSER ? { executablePath: process.env.VIDEO_STUDIO_BROWSER } : {}) })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const run = { id: 'snapshot-project', project_id: 'snapshot-project', thread_id: 'snapshot-thread',
    title: 'Conversation', objective: 'Hello', status: 'completed', current_revision: 0,
    code_video_mode: true,
    created_at: '2026-09-12T00:00:00Z', updated_at: '2026-09-12T00:00:00Z', last_response: 'Hello there.' }
  const message = (id, content) => ({ id: String(id), run_id: run.id, role: 'assistant', content,
    created_at: `2026-09-12T00:00:0${id}Z` })
  const initial = message(1, 'Hello there.')
  const staleCheckpoint = message(2, 'HTTP 422: cannot modify a terminal build')
  const artifact = (id, type, title, uri = null, metadata = {}) => ({
    id, artifact_id: `${run.id}:${id}`, project_id: run.id, type, version: 1,
    status: 'completed', produced_by_task_id: `task-${id}`, title, summary: '', uri,
    metadata, created_at: `2026-09-12T00:01:0${id.length}Z`,
  })
  const artifacts = [
    artifact('script', 'script', 'Dynamic screenplay', null, {
      content: 'A blue fox crosses the moonlit clearing.',
      final_prompt: 'Write a concise screenplay about a blue fox.',
    }),
    artifact('brief', 'document', 'Campaign copy reference', null, {
      content: 'Campaign language and product facts.',
      final_prompt: 'Prepare campaign copy reference notes.',
    }),
    artifact('image', 'image', 'Character reference', 'https://assets.test/character.png', {
      final_prompt: 'Blue fox character reference, clean studio lighting.',
    }),
    artifact('audio', 'music', 'Forest score', 'https://assets.test/score.mp3', {
      final_prompt: 'Gentle nocturnal forest score without vocals.',
    }),
    artifact('clip', 'video', 'Generated clip', 'https://assets.test/clip.mp4', {
      plan_step_id: 'segment_01',
      final_prompt: 'Blue fox walking through a moonlit forest.',
    }),
    { ...artifact('final-v1', 'final_video', 'First delivery', 'https://assets.test/final-v1.mp4', {
      plan_step_id: 'deliver_result', logical_id: 'final-video',
      final_prompt: 'Assemble the first blue fox sequence.',
    }), artifact_id: `${run.id}:final-video`, version: 1 },
    { ...artifact('final', 'final_video', 'Completed delivery', 'https://assets.test/final.mp4', {
      plan_step_id: 'deliver_result', logical_id: 'final-video',
      final_prompt: 'Assemble the selected blue fox sequence.',
    }), artifact_id: `${run.id}:final-video`, version: 2 },
  ]
  const events = []
  let sequence = 1
  let subscriptions = 0
  let homeCreateChecked = false
  const emit = (type, payload = {}) => {
    sequence += 1
    events.push({ id: `e-${sequence}`, run_id: run.id, sequence, type, payload,
      created_at: `2026-09-12T00:00:0${sequence}Z` })
  }
  await page.route('**/chat-v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/events')) {
      subscriptions += 1
      const after = Number(url.searchParams.get('after') || 0)
      await route.fulfill({ contentType: 'text/event-stream', body:
        events.filter(event => event.sequence > after).map(event => `data: ${JSON.stringify(event)}\n\n`).join('') || ': heartbeat\n\n' })
      return
    }
    let data = []
    if (url.pathname.endsWith('/messages') && route.request().method() === 'POST') {
      assert.equal(route.request().postDataJSON().thread_id, run.thread_id)
      assert.equal(route.request().postDataJSON().code_video_mode, true)
      run.status = 'running'
      emit('agent.started')
      data = run
    } else if (url.pathname.endsWith('/runs') && route.request().method() === 'POST') {
      assert.equal(route.request().postDataJSON().automatic_video, false)
      homeCreateChecked = true
      data = run
    } else if (url.pathname.endsWith('/runtime-options')) {
      data = { wavespeed_configured: false, default_code_video_mode: true }
    } else if (url.pathname.endsWith('/runs')) data = [run]
    else if (url.pathname.endsWith(`/runs/${run.id}`)) data = {
      run, messages: [initial, staleCheckpoint], tasks: [], artifacts,
      selections: [{ project_id: run.id, type: 'video', artifact_version_id: 'final', updated_at: '2026-09-12T00:02:00Z' }],
      events: [...events], last_event_sequence: sequence,
    }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.route('**/api/video/**', route => route.fulfill({ json: { data: {
    project: { id: run.id, title: run.title }, currentProjectVersion: null,
    videoSpec: null, artifacts: [], artifactGroups: {}, artifactEdges: [], builds: [],
    projectVersions: [], videoSpecRevisions: [], planRevisions: [],
    resolvedSections: [], unresolvedSections: [],
  } } }))
  await page.goto(`http://127.0.0.1:${server.address().port}/en/create/${run.thread_id}`)
  await page.getByText(initial.content, { exact: true }).waitFor()
  assert.equal(await page.getByText(/cannot modify a terminal build/).count(), 0)
  await page.getByRole('button', { name: 'Code Video' }).waitFor()
  await page.locator('textarea').fill('Continue with the blue fox')
  const accepted = page.waitForResponse(response => response.url().endsWith('/messages'))
  await page.locator('textarea').press('Enter')
  await accepted
  emit('chat.message.created', { message: message(3, 'Using the blue fox reference.') })
  emit('run.completed')
  await page.getByText('Using the blue fox reference.', { exact: true }).waitFor()
  // The third turn is initiated by Runtime, not by the browser composer.
  emit('agent.started')
  emit('chat.message.created', { message: message(6, 'The next clip reuses that reference.') })
  emit('run.completed')
  await page.getByText('The next clip reuses that reference.', { exact: true }).waitFor()
  emit('agent.started')
  const providerError = 'You have no credits remaining. Add credits to continue using the API.'
  emit('run.failed', { error: providerError, error_code: 'PI_AI_ERROR' })
  await page.getByText(providerError, { exact: true }).waitFor()
  await page.getByRole('tab', { name: /Assets/ }).click()
  await page.getByText('Character reference', { exact: true }).waitFor()
  await page.getByText('Generated clip', { exact: true }).waitFor()
  assert.equal(await page.getByText('Completed delivery', { exact: true }).count(), 0)
  await page.getByRole('button', { name: /^Text 1$/ }).click()
  await page.getByText('Campaign copy reference', { exact: true }).waitFor()
  assert.equal(await page.getByText('Character reference', { exact: true }).count(), 0)
  await page.getByText('Generation prompt', { exact: true }).click()
  await page.getByText('Prepare campaign copy reference notes.', { exact: true }).waitFor()
  await page.getByRole('button', { name: /^Images 1$/ }).click()
  await page.getByText('Generation prompt', { exact: true }).click()
  await page.getByText('Blue fox character reference, clean studio lighting.', { exact: true }).waitFor()
  await page.getByRole('button', { name: /^Videos 1$/ }).click()
  await page.getByText('Generation prompt', { exact: true }).click()
  await page.getByText('Blue fox walking through a moonlit forest.', { exact: true }).waitFor()
  await page.getByRole('button', { name: /^Audio 1$/ }).click()
  await page.getByText('Generation prompt', { exact: true }).click()
  await page.getByText('Gentle nocturnal forest score without vocals.', { exact: true }).waitFor()
  await page.getByRole('tab', { name: /Script/ }).click()
  await page.getByText('Dynamic screenplay', { exact: true }).waitFor()
  await page.getByText('Dynamic screenplay', { exact: true })
    .locator('xpath=ancestor::*[descendant::summary][1]')
    .getByText('Generation prompt', { exact: true })
    .click()
  await page.getByText('Write a concise screenplay about a blue fox.', { exact: true }).waitFor()
  await page.getByRole('tab', { name: /Final video/ }).click()
  await page.getByRole('heading', { name: 'Completed delivery' }).waitFor()
  await page.getByRole('button', { name: 'Version 1: First delivery' }).waitFor()
  await page.getByRole('button', { name: 'Version 2: Completed delivery' }).waitFor()
  await page.getByText('Generation prompt', { exact: true }).click()
  await page.getByText('Assemble the selected blue fox sequence.', { exact: true }).waitFor()
  const expected = JSON.parse(await readFile(resolve(directory, 'browser-session.snapshot.json'), 'utf8'))
  const visible = []
  for (const text of expected) visible.push(await page.getByText(text, { exact: true }).innerText())
  assert.deepEqual(visible, expected)
  run.status = 'failed'
  await page.reload()
  await page.getByText(providerError, { exact: true }).waitFor({ timeout: 10000 }).catch(async error => {
    console.error(await page.locator('body').innerText())
    throw error
  })
  await page.goto(`http://127.0.0.1:${server.address().port}/en`)
  await page.locator('textarea[placeholder="Imaginary world starts here"]').fill('Hello')
  const created = page.waitForResponse(response => (
    response.url().endsWith('/runs') && response.request().method() === 'POST'
  ))
  await page.getByRole('button', { name: 'Generate' }).click()
  await created
  assert.equal(homeCreateChecked, true)
  assert.ok(subscriptions > 0)
  assert.deepEqual(errors, [])
  console.log('PASS built Studio conversation state, API error notice and dynamic artifact tabs')
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
