/** Merge all Fetch header representations, letting request-specific headers override defaults. */
export function requestHeaders(defaults: HeadersInit, overrides?: HeadersInit): Headers {
  const headers = new Headers(defaults)
  new Headers(overrides).forEach((value, name) => { headers.set(name, value) })
  return headers
}
