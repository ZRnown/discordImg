import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

test('accounts personal settings expose the best-match-image toggle', () => {
  const source = readFileSync(new URL('./components/accounts-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('keyword_reply_send_best_match_image'), true)
  assert.equal(source.includes('发送最相似商品图'), true)
})

test('image search view exposes skipped image history section and endpoint', () => {
  const source = readFileSync(new URL('./components/image-search-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('/api/skipped_image_history'), true)
  assert.equal(source.includes('被略过的商品'), true)
})

test('next api routes proxy skipped image history requests', () => {
  assert.equal(existsSync(new URL('./app/api/skipped_image_history/route.ts', import.meta.url)), true)
  assert.equal(existsSync(new URL('./app/api/skipped_image_history/[id]/route.ts', import.meta.url)), true)
})
