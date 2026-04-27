import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('live retrieval prepares cold catalog in background instead of blocking request', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(source, /started = self\._start_background_refresh_locked\(\)/)
  assert.match(source, /raise LiveCatalogPreparingError/)
  assert.doesNotMatch(source, /return self\._prepare_catalog_now\(\)/)
})

test('startup catalog preparation is disabled by default', () => {
  const source = readFileSync(new URL('./config.py', import.meta.url), 'utf8')

  assert.match(source, /LIVE_IMAGE_SEARCH_STARTUP_PREPARE_CATALOG.*False/)
})
