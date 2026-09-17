import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

test('a clean checkout gets root-relative config entrypoints and refreshes changed sources', () => {
  const root = mkdtempSync(join(tmpdir(), 'harness-root-config-'))
  const repository = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  try {
    mkdirSync(join(root, 'scripts'))
    cpSync(join(repository, 'config', 'root'), join(root, 'config', 'root'), { recursive: true })
    cpSync(join(repository, 'scripts', 'materialize-root-configs.mjs'), join(root, 'scripts', 'materialize-root-configs.mjs'))
    const invoke = () => execFileSync(process.execPath, ['scripts/materialize-root-configs.mjs'], { cwd: root })
    invoke()
    for (const name of ['tsconfig.json', 'tsconfig.base.json', 'tsdown.config.ts', 'vitest.config.ts', '.oxlintrc.json', 'lefthook.yml']) {
      assert.deepEqual(readFileSync(join(root, name)), readFileSync(join(root, 'config', 'root', name)))
    }
    const updated = '{"testpaths":"python/sdk/tests"}\n'
    writeFileSync(join(root, 'config', 'root', 'pytest.ini'), updated)
    invoke()
    assert.equal(readFileSync(join(root, 'pytest.ini'), 'utf8'), updated)
    invoke()
    assert.equal(readFileSync(join(root, 'pytest.ini'), 'utf8'), updated)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
