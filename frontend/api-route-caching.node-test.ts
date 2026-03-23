import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readRouteSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('websites proxy route is forced dynamic and bypasses backend cache', () => {
  const source = readRouteSource('app/api/websites/route.ts')

  assert.match(source, /export const dynamic = ['"]force-dynamic['"]/)
  assert.match(source, /cache:\s*['"]no-store['"]/)
})
