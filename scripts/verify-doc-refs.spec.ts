import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { findViolations } from './verify-doc-refs.ts'

it('checks local paths while preserving pinned external historical references', () => {
  const root = mkdtempSync(join(tmpdir(), 'dsh-doc-refs-'))
  try {
    mkdirSync(join(root, 'docs'))
    writeFileSync(join(root, 'docs/present.md'), '# Present\n')
    const file = join(root, 'source.ts')
    writeFileSync(file, [
      '// docs/present.md',
      '// https://github.com/example/repo/blob/commit/.agents/notes/old.md',
      '// [external](https://example.com/docs/remote.md) docs/missing.md',
      '// .agents/notes/missing.md',
    ].join('\n'))
    expect(findViolations(root, file)).toEqual([
      { file: 'source.ts', line: 3, ref: 'docs/missing.md' },
      { file: 'source.ts', line: 4, ref: '.agents/notes/missing.md' },
    ])
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
