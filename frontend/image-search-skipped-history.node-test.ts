import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('accounts personal settings expose the best-match-image toggle', () => {
  const source = readFileSync(new URL('./components/accounts-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('keyword_reply_send_best_match_image'), true)
  assert.equal(source.includes('图片过阈值时发送图和链接'), true)
  assert.equal(source.includes('未达到阈值时不发送'), true)
})

test('image search view folds skipped images into search history with a filter', () => {
  const source = readFileSync(new URL('./components/image-search-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('historyFilter'), true)
  assert.equal(source.includes('是否略过'), true)
  assert.equal(source.includes('已略过'), true)
  assert.equal(source.includes('/api/skipped_image_history'), false)
})

test('search history api route forwards skipped filter requests', () => {
  const source = readFileSync(new URL('./app/api/search_history/route.ts', import.meta.url), 'utf8')

  assert.equal(source.includes("url.searchParams.get('skipped')"), true)
  assert.equal(source.includes('skipped=${encodeURIComponent(skipped)}'), true)
})
