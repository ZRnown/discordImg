import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('accounts personal settings expose the best-match-image toggle', () => {
  const source = readFileSync(new URL('./components/accounts-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('keyword_reply_send_best_match_image'), true)
  assert.equal(source.includes('图片过阈值时发送图和链接'), true)
  assert.equal(source.includes('未达到阈值时发送链接，并记录到被略过的商品'), true)
})

test('image search view defaults to all history while keeping skipped filter', () => {
  const source = readFileSync(new URL('./components/image-search-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('useState<"all" | "normal" | "skipped">("all")'), true)
  assert.equal(source.includes('被略过的商品'), true)
  assert.equal(source.includes('搜索记录'), true)
  assert.equal(source.includes('已略过'), true)
  assert.equal(source.includes('/api/skipped_image_history'), false)
})

test('image search history preview and pagination expose far pages', () => {
  const source = readFileSync(new URL('./components/image-search-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('previewImage'), true)
  assert.equal(source.includes('setPreviewImage'), true)
  assert.equal(source.includes('firstWindowEnd'), true)
  assert.equal(source.includes('lastWindowStart'), true)
})

test('image search history pages are cached for faster pagination', () => {
  const source = readFileSync(new URL('./components/image-search-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('historyPageCacheRef'), true)
  assert.equal(source.includes('prefetchSearchHistory'), true)
  assert.equal(source.includes('forceRefresh'), true)
})

test('search history api route forwards skipped filter requests', () => {
  const source = readFileSync(new URL('./app/api/search_history/route.ts', import.meta.url), 'utf8')

  assert.equal(source.includes("url.searchParams.get('skipped')"), true)
  assert.equal(source.includes('skipped=${encodeURIComponent(skipped)}'), true)
})

test('accounts view scopes cached settings by current logged-in user', () => {
  const source = readFileSync(new URL('./components/accounts-view.tsx', import.meta.url), 'utf8')

  assert.equal(source.includes('discord_marketing_bark_settings_v1:'), true)
  assert.equal(source.includes('preload_settings:'), true)
  assert.equal(source.includes('currentUser?.id'), true)
})

test('production image search weights emphasize appearance plus color and apply a margin gate', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('SIGLIP2_RERANK_IMAGE_WEIGHT: "0.82"'), true)
  assert.equal(source.includes('SIGLIP2_RERANK_COLOR_WEIGHT: "0.18"'), true)
  assert.equal(source.includes('SIGLIP2_RERANK_QUERY_RAW_WEIGHT: "0.25"'), true)
  assert.equal(source.includes('SIGLIP2_RERANK_QUERY_CENTER_WEIGHT: "0.75"'), true)
  assert.equal(source.includes('DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN: "0.03"'), true)
})
