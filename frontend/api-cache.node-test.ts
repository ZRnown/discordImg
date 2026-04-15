import test from 'node:test'
import assert from 'node:assert/strict'

test('forced fetch bypasses stale cache and replaces the cached value', async () => {
  const cacheDuration = 30000
  const cacheRef: Record<string, { data: any; timestamp: number }> = {}
  let sequence = 0

  const cachedFetch = async (url: string, options?: { method?: string; force?: boolean }) => {
    const cacheKey = `${options?.method || 'GET'}:${url}`
    const now = Date.now()
    const shouldBypassCache = options?.force === true
    const cached = cacheRef[cacheKey]

    if (!shouldBypassCache && cached && (now - cached.timestamp) < cacheDuration) {
      return cached.data
    }

    sequence += 1
    const data = { sequence }
    cacheRef[cacheKey] = { data, timestamp: now }
    return data
  }

  const first = await cachedFetch('/api/accounts')
  const second = await cachedFetch('/api/accounts')
  assert.deepEqual(second, first)

  const forced = await cachedFetch('/api/accounts', { force: true })
  assert.notDeepEqual(forced, first)

  const third = await cachedFetch('/api/accounts')
  assert.deepEqual(third, forced)
})
