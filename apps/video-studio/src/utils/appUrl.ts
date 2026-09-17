/** Build an in-app URL that follows the current Vite base path. */
export function buildAppUrl(pathFromRoot: string): string {
  const origin = window.location.origin
  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  const path = pathFromRoot.startsWith('/') ? pathFromRoot : `/${pathFromRoot}`
  return `${origin}${base}${path}`
}
