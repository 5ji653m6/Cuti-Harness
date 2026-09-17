import { readFileSync, existsSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

describe('account-free open-source Studio', () => {
  it('mounts Create without an authentication provider or login route', () => {
    expect(read('src/App.tsx')).toContain('path="/create"')
    expect(read('src/App.tsx')).not.toMatch(/AuthProvider|AuthPage|\/auth/)
    expect(existsSync(new URL('../src/contexts/AuthContext.tsx', import.meta.url))).toBe(false)
  })

  it('does not gate workspace or generation on account state', () => {
    for (const path of ['src/pages/DeepAgentWorkspacePage.tsx', 'src/components/GenerationBox.tsx']) {
      expect(read(path)).not.toMatch(/useAuth|isLoggedIn|authLoading|onLogout|\/auth/)
    }
  })

  it('does not ship login API methods or a build-time login switch', () => {
    expect(read('src/services/api.ts')).not.toMatch(/authApi|users\/(?:login|logout|register|send-otp|verify-otp)|admin\/(?:login|logout)/)
    for (const path of ['Dockerfile', '.env.example', 'src/vite-env.d.ts']) {
      expect(read(path)).not.toContain('VITE_LOCAL_SINGLE_USER_MODE')
    }
  })
})
