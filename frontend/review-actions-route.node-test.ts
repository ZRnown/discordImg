import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readRouteSource = () => {
  const candidates = [
    path.join(process.cwd(), 'frontend/app/review-actions/[token]/route.ts'),
    path.join(process.cwd(), 'app/review-actions/[token]/route.ts'),
  ]
  const routePath = candidates.find(candidate => existsSync(candidate))
  assert.ok(routePath, `review action mobile route should exist in: ${candidates.join(', ')}`)
  return readFileSync(routePath, 'utf8')
}

test('review action mobile route proxies html GET and POST to the Flask backend', () => {
  const source = readRouteSource()

  assert.match(source, /export const dynamic = ['"]force-dynamic['"]/)
  assert.match(source, /export async function GET/)
  assert.match(source, /export async function POST/)
  assert.match(source, /\/review-actions\/\$\{encodeURIComponent\(token\)\}/)
  assert.match(source, /content-type/i)
  assert.match(source, /text\/html/)
})
