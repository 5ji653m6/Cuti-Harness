import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { basename, resolve } from 'node:path'

const packageRoot = resolve(import.meta.dirname, '..')
const repositoryRoot = resolve(packageRoot, '..', '..')
const runtimeRoot = resolve(packageRoot, 'runtime')

mkdirSync(runtimeRoot, { recursive: true })
for (const name of ['video-runtime', 'media-service', 'sandbox-worker', 'studio']) {
  rmSync(resolve(runtimeRoot, name), { recursive: true, force: true })
}

const withoutDevelopmentFiles = source =>
  !/[\\/](?:\.runtime-deps|\.venv|\.pytest_cache|__pycache__|tests|logs|data)(?:[\\/]|$)/.test(source)

function copyRuntimeParts(service, parts) {
  const sourceRoot = resolve(repositoryRoot, 'services', service)
  const destinationRoot = resolve(runtimeRoot, service)
  mkdirSync(destinationRoot, { recursive: true })
  for (const part of parts) {
    const source = resolve(sourceRoot, part)
    if (!existsSync(source)) continue
    cpSync(source, resolve(destinationRoot, basename(part)), {
      recursive: true,
      filter: withoutDevelopmentFiles,
    })
  }
}

// Ship only runtime inputs. Deployment charts, migrations, tests, caches, and
// locally installed Python wheels are repository concerns, not npm payloads.
copyRuntimeParts('video-runtime', ['app', 'plugins', 'skills', 'prompts'])
copyRuntimeParts('media-service', ['app', 'assets'])
copyRuntimeParts('sandbox-worker', ['app'])
cpSync(resolve(repositoryRoot, 'apps', 'video-studio', 'dist'), resolve(runtimeRoot, 'studio'), {
  recursive: true,
})

console.log('video-agent-harness: prepared Python services and Video Studio assets')
