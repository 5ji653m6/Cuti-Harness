/** Render scalar wire values verbatim and preserve fields in structured values. */
export function displayValue(value: unknown): string {
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
