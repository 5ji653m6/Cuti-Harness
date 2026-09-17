import { describe, expect, it } from 'vitest'
import { resolveOxlintInvocation } from './run-oxlint.ts'

describe('Oxlint invocation', () => {
  it('preserves the ordinary default invocation', () => {
    expect(resolveOxlintInvocation(['.'], { PATH: '/bin' })).toEqual({
      args: ['--config', '.oxlintrc.json', '.'],
      env: { PATH: '/bin' },
    })
  })

  it('preserves an explicitly selected configuration', () => {
    expect(resolveOxlintInvocation(['--config', '.oxlintrc.staged.json', '.'], { PATH: '/bin' }).args)
      .toEqual(['--config', '.oxlintrc.staged.json', '.'])
  })

  it('bounds both worker pools from one setting', () => {
    expect(resolveOxlintInvocation(['.', '--fix'], { DSH_OXLINT_THREADS: '4', GOMAXPROCS: '12' })).toEqual({
      args: ['--config', '.oxlintrc.json', '.', '--fix', '--threads=4'],
      env: { DSH_OXLINT_THREADS: '4', GOMAXPROCS: '4' },
    })
  })

  it('uses location-preserving diagnostics in CI', () => {
    expect(resolveOxlintInvocation(['.'], { CI: 'true', DSH_OXLINT_THREADS: '4' })).toEqual({
      args: ['--config', '.oxlintrc.json', '.', '--format=unix', '--threads=4'],
      env: { CI: 'true', DSH_OXLINT_THREADS: '4', GOMAXPROCS: '4' },
    })
  })

  it('preserves an explicitly selected CI formatter', () => {
    expect(resolveOxlintInvocation(['.', '--format', 'github'], { CI: 'true' }).args)
      .toEqual(['--config', '.oxlintrc.json', '.', '--format', 'github'])
  })

  it.each(['0', '-1', '1.5', 'auto'])('rejects invalid worker bound %s', (value) => {
    expect(() => resolveOxlintInvocation(['.'], { DSH_OXLINT_THREADS: value }))
      .toThrow('DSH_OXLINT_THREADS must be a positive integer')
  })

  it('rejects a competing direct worker bound', () => {
    expect(() => resolveOxlintInvocation(['.', '--threads=2'], { DSH_OXLINT_THREADS: '4' }))
      .toThrow('use DSH_OXLINT_THREADS instead')
  })
})
