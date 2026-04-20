import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = () => {
  const candidates = [
    path.join(process.cwd(), 'frontend/components/review-window-view.tsx'),
    path.join(process.cwd(), 'components/review-window-view.tsx'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find review-window-view.tsx in: ${candidates.join(', ')}`)
}

test('review window toolbar stays bottom aligned without manual top padding', () => {
  const source = readSource()

  assert.match(source, /sm:grid-cols-\[240px_auto\]/)
  assert.match(source, /sm:items-end/)
  assert.doesNotMatch(source, /pt-5 sm:pt-0/)
})
