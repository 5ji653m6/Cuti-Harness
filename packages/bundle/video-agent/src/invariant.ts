/** Package-owned invariant companion for `@cuti-ai/video-agent-bundle`. @module @cuti-ai/video-agent-bundle/invariant */
import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'
const PACKAGE_NAME = '@cuti-ai/video-agent-bundle'
export const name = 'cuti-video-agent-bundle-invariant'
export const inject = ['invariants']
/** No runtime invariant: this package is a static Cordis patch carrier. */
const install: InvariantInstaller = () => {}
export const apply = (ctx: Context): Promise<() => void> => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
