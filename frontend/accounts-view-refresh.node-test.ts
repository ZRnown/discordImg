import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('accounts view invalidates cache and forces a fresh fetch after account mutations', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /invalidateCache\('\/api\/accounts'\)/)
  assert.match(source, /force:\s*forceRefresh/)
  assert.match(source, /await fetchAccounts\(true\)/)
})
