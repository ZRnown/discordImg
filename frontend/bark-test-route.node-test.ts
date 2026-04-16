import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('accounts bark test button uses backend proxy route', () => {
  const source = readSource('components/accounts-view.tsx')

  assert.match(source, /fetch\('\/api\/user\/bark-test'/)
})
