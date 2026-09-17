import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  createStudioGateway,
  hyperframesRuntimeState,
  loadDotEnv,
  loadLocalCredentialEnvironment,
  parseArguments,
  runLocalWeb,
} from '../src/local-runtime.mjs'

test('parses local web options with Conda Python as the default', () => {
  assert.deepEqual(parseArguments([
    'web', '--no-open', '--runtime-port', '8101',
  ]), {
    command: 'web', noOpen: true, portablePython: false, sourceRoot: undefined,
    dataDir: undefined, studioPort: 3000, harnessPort: 3080, runtimePort: 8101,
    mediaPort: 18080, sandboxPort: 8700,
  })
})

test('start requires the named Conda environment by default', async () => {
  const previousPrefix = process.env.CONDA_PREFIX
  const previousName = process.env.CONDA_DEFAULT_ENV
  delete process.env.CONDA_PREFIX
  delete process.env.CONDA_DEFAULT_ENV
  const dataDirectory = mkdtempSync(join(tmpdir(), 'video-agent-no-conda-'))
  const options = parseArguments([
    'web', '--source-root', fileURLToPath(new URL('../../..', import.meta.url)),
    '--data-dir', dataDirectory,
  ])
  try {
    await assert.rejects(
      runLocalWeb(options, fileURLToPath(new URL('..', import.meta.url))),
      /Conda environment 'cuti-video-agent'.*is not active/,
    )
  } finally {
    if (previousPrefix === undefined) delete process.env.CONDA_PREFIX
    else process.env.CONDA_PREFIX = previousPrefix
    if (previousName === undefined) delete process.env.CONDA_DEFAULT_ENV
    else process.env.CONDA_DEFAULT_ENV = previousName
  }
})

test('portable Python is an explicit setup option', () => {
  assert.equal(parseArguments(['setup', '--portable-python']).portablePython, true)
})

test('HyperFrames readiness is versioned inside the selected data directory', () => {
  const dataDirectory = mkdtempSync(join(tmpdir(), 'video-agent-hyperframes-'))
  const state = hyperframesRuntimeState(dataDirectory)
  assert.equal(state.ready, false)
  mkdirSync(join(state.root, 'node_modules', 'hyperframes', 'bin'), { recursive: true })
  mkdirSync(join(state.root, 'node_modules', 'gsap', 'dist'), { recursive: true })
  writeFileSync(state.cli, '')
  writeFileSync(state.gsap, '')
  writeFileSync(state.marker, 'hyperframes@0.8.16\ngsap@3.14.2\n')
  assert.equal(hyperframesRuntimeState(dataDirectory).ready, true)
})

test('accepts the installed executable version flag', () => {
  assert.equal(parseArguments(['--version']).command, 'version')
})

test('start rejects an unprepared portable environment without downloading it', async () => {
  const dataDirectory = mkdtempSync(join(tmpdir(), 'video-agent-unprepared-'))
  const options = parseArguments([
    'web', '--portable-python', '--source-root', fileURLToPath(new URL('../../..', import.meta.url)),
    '--data-dir', dataDirectory,
  ])

  await assert.rejects(
    runLocalWeb(options, fileURLToPath(new URL('..', import.meta.url))),
    /portable Python is not prepared; run the setup command/,
  )
  assert.deepEqual(readdirSync(dataDirectory), [])
})

test('rejects invalid ports', () => {
  assert.throws(() => parseArguments(['web', '--studio-port', '0']), /valid port/)
})

test('loads dotenv without overriding the caller environment', () => {
  const directory = mkdtempSync(join(tmpdir(), 'video-agent-cli-'))
  const path = join(directory, '.env')
  writeFileSync(path, 'OPENAI_API_KEY="from-file"\nWAVESPEED_API_KEY=media-key\n')
  const environment = { OPENAI_API_KEY: 'from-shell' }
  loadDotEnv(path, environment)
  assert.equal(environment.OPENAI_API_KEY, 'from-shell')
  assert.equal(environment.WAVESPEED_API_KEY, 'media-key')
})

test('repository dotenv template excludes process-launch settings', () => {
  const template = readFileSync(new URL('../../../config/.env.example', import.meta.url), 'utf8')
  for (const name of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'NODE_USE_ENV_PROXY']) {
    assert.doesNotMatch(template, new RegExp(`^${name}=`, 'm'))
  }
})

test('source launcher inherits missing credentials from the sibling Cuti checkout', () => {
  const workspace = mkdtempSync(join(tmpdir(), 'video-agent-workspace-'))
  const root = join(workspace, 'video-agent-harness')
  const legacy = join(workspace, 'cuti-video-agent')
  const agent = join(legacy, 'services', 'agent')
  mkdirSync(root, { recursive: true })
  mkdirSync(agent, { recursive: true })
  writeFileSync(join(root, '.env'), 'REPO_SETTING=repo-value\n')
  writeFileSync(join(legacy, '.env'), 'OPENAI_API_KEY=legacy-key\nWAVESPEED_API_KEY=wavespeed-key\n')
  writeFileSync(join(agent, '.env'), 'SUNO_API_KEY=music-key\n')

  const environment = {}
  loadLocalCredentialEnvironment({ root, source: true }, environment)

  assert.equal(environment.REPO_SETTING, 'repo-value')
  assert.equal(environment.OPENAI_API_KEY, 'legacy-key')
  assert.equal(environment.WAVESPEED_API_KEY, 'wavespeed-key')
  assert.equal(environment.SUNO_API_KEY, 'music-key')
})

test('studio gateway serves the single-page application', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'video-agent-studio-'))
  writeFileSync(join(directory, 'index.html'), '<main>video-studio</main>')
  const gateway = await createStudioGateway(directory, 65534, 0)
  try {
    const { port } = gateway.address()
    const response = await fetch(`http://127.0.0.1:${port}/create/thread-id`)
    assert.equal(response.status, 200)
    assert.equal(await response.text(), '<main>video-studio</main>')
  } finally {
    gateway.close()
  }
})
