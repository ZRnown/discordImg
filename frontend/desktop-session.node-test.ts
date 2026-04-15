import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  DESKTOP_FALLBACK_USER,
  resolveDesktopUser,
  waitForDesktopUser,
} from './lib/desktop-session.ts'

test('desktop mode falls back to the built-in admin user when auth payload is missing', () => {
  assert.deepEqual(
    resolveDesktopUser({
      desktopMode: true,
      currentUser: null,
    }),
    DESKTOP_FALLBACK_USER,
  )
})

test('non-desktop mode does not synthesize a fallback user', () => {
  assert.equal(
    resolveDesktopUser({
      desktopMode: false,
      currentUser: null,
    }),
    null,
  )
})

test('waitForDesktopUser retries until auth endpoint returns a user', async () => {
  let attempts = 0
  const delays: number[] = []

  const user = await waitForDesktopUser({
    fetchImpl: async () => {
      attempts += 1
      if (attempts < 3) {
        throw new Error('backend not ready')
      }
      return {
        ok: true,
        async json() {
          return {
            user: {
              id: 7,
              username: 'desktop-admin',
              role: 'admin',
              shops: ['TIP'],
            },
          }
        },
      }
    },
    maxAttempts: 4,
    delayMs: 25,
    sleep: async (ms) => {
      delays.push(ms)
    },
  })

  assert.equal(attempts, 3)
  assert.deepEqual(delays, [25, 25])
  assert.deepEqual(user, {
    id: 7,
    username: 'desktop-admin',
    role: 'admin',
    shops: ['TIP'],
  })
})

test('waitForDesktopUser returns null after exhausting retries', async () => {
  let attempts = 0

  const user = await waitForDesktopUser({
    fetchImpl: async () => {
      attempts += 1
      return {
        ok: false,
        async json() {
          return { error: '未登录' }
        },
      }
    },
    maxAttempts: 3,
    delayMs: 10,
    sleep: async () => {},
  })

  assert.equal(attempts, 3)
  assert.equal(user, null)
})

test('desktop app source waits for a real backend user instead of rendering with the fallback user', () => {
  const source = readFileSync(new URL('./components/app-page-client.tsx', import.meta.url), 'utf8')

  assert.match(source, /const effectiveUser = desktopMode\s*\?\s*currentUser\s*:\s*resolveDesktopUser\(\{ desktopMode, currentUser \}\)/)
  assert.match(source, /if \(!effectiveUser\) \{\s*return null\s*\}/)
})
