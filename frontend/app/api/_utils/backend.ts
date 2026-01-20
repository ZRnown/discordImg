const DEFAULT_BACKEND_CANDIDATES = [
  process.env.NEXT_PUBLIC_BACKEND_URL,
  process.env.NEXT_PUBLIC_API_URL ? process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, '') : undefined,
  'http://127.0.0.1:5001',
  'http://localhost:5001',
  'http://host.docker.internal:5001'
].filter(Boolean) as string[]

const UNIQUE_CANDIDATES = Array.from(new Set(DEFAULT_BACKEND_CANDIDATES))

const ensureNoProxyForLocal = () => {
  const localHosts = ['localhost', '127.0.0.1', 'host.docker.internal', '0.0.0.0']
  const current = process.env.NO_PROXY || process.env.no_proxy || ''
  const entries = current.split(',').map(item => item.trim()).filter(Boolean)
  let changed = false

  for (const host of localHosts) {
    if (!entries.includes(host)) {
      entries.push(host)
      changed = true
    }
  }

  if (changed) {
    const updated = entries.join(',')
    process.env.NO_PROXY = updated
    process.env.no_proxy = updated
  }

  process.env.HTTP_PROXY = ''
  process.env.HTTPS_PROXY = ''
  process.env.ALL_PROXY = ''
  process.env.http_proxy = ''
  process.env.https_proxy = ''
  process.env.all_proxy = ''
  process.env.GLOBAL_AGENT_HTTP_PROXY = ''
  process.env.GLOBAL_AGENT_HTTPS_PROXY = ''
  process.env.GLOBAL_AGENT_NO_PROXY = '*'
}

const buildHostCandidate = (hostHeader?: string | null) => {
  if (!hostHeader) return null
  const hostname = hostHeader.split(':')[0]
  if (!hostname) return null
  return `http://${hostname}:5001`
}

type BackendFetchResult = {
  response: Response
  rawText: string
  baseUrl: string
}

export async function fetchFromBackend(
  path: string,
  init?: RequestInit,
  hostHeader?: string | null,
  timeoutMs?: number
): Promise<BackendFetchResult> {
  let lastError: Error | null = null
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  ensureNoProxyForLocal()
  const hostCandidate = buildHostCandidate(hostHeader)
  const candidates = Array.from(new Set([hostCandidate, ...UNIQUE_CANDIDATES].filter(Boolean))) as string[]

  for (const baseUrl of candidates) {
    try {
      const controller = timeoutMs ? new AbortController() : null
      const timeoutId = timeoutMs
        ? setTimeout(() => controller?.abort(), timeoutMs)
        : null
      const response = await fetch(`${baseUrl}${normalizedPath}`, {
        ...(init || {}),
        signal: controller?.signal
      })
      if (timeoutId) clearTimeout(timeoutId)
      const rawText = await response.text()
      const trimmed = rawText.trim().toLowerCase()
      if (response.status === 404 && (trimmed.startsWith('<!doctype') || trimmed.startsWith('<html'))) {
        lastError = new Error(`Backend ${baseUrl} returned HTML 404`)
        continue
      }
      return { response, rawText, baseUrl }
    } catch (error) {
      lastError = error as Error
    }
  }

  throw lastError || new Error(`Backend unreachable. Tried: ${candidates.join(', ')}`)
}
