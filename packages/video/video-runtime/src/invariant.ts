/** Package-owned invariant companion for `@cuti-ai/video-runtime`. @module @cuti-ai/video-runtime/invariant */

import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'

const PACKAGE_NAME = '@cuti-ai/video-runtime'
export const name = 'cuti-video-runtime-invariant'
export const inject = ['invariants']

/** No runtime invariant: concrete providers enforce project and version consistency. */
const install: InvariantInstaller = () => {}

export const apply = (ctx: Context): Promise<() => void> =>
  Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
