/** Package-owned invariant companion for `@cuti-ai/tool-video`. @module @cuti-ai/tool-video/invariant */
import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'
const PACKAGE_NAME = '@cuti-ai/tool-video'
export const name = 'cuti-tool-video-invariant'
export const inject = ['invariants']
/** No runtime invariant: the tools retain no state and the runtime owns version consistency. */
const install: InvariantInstaller = () => {}
export const apply = (ctx: Context): Promise<() => void> => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
