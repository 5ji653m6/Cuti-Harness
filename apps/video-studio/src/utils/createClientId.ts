/** Create browser request IDs, including environments without secure-context randomUUID. */
export function createClientId(): string {
  if (typeof globalThis.crypto === 'object' && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}
