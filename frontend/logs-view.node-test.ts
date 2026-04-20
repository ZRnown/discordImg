import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = () => {
  const candidates = [
    path.join(process.cwd(), 'frontend/components/logs-view.tsx'),
    path.join(process.cwd(), 'components/logs-view.tsx'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find logs-view.tsx in: ${candidates.join(', ')}`)
}

test('logs view keeps streaming live without pause or manual refresh controls', () => {
  const source = readSource()

  assert.match(source, /new EventSource\('/)
  assert.doesNotMatch(source, /\bPause\b/)
  assert.doesNotMatch(source, /\bPlay\b/)
  assert.doesNotMatch(source, /handleTogglePause/)
  assert.doesNotMatch(source, /handleRefresh/)
  assert.doesNotMatch(source, /isPaused/)
})
