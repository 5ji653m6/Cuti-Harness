/** Package-owned invariant companion for `@cuti-ai/video-runtime-http`. @module @cuti-ai/video-runtime-http/invariant */
import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'
const PACKAGE_NAME = '@cuti-ai/video-runtime-http'
export const name = 'cuti-video-runtime-http-invariant'
export const inject = ['invariants']
/** No runtime invariant: HTTP response validation is enforced at the transport boundary. */
const install: InvariantInstaller = () => {}
export const apply = (ctx: Context): Promise<() => void> => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
