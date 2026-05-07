import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('search timeout releases the live search slot and propagates cancellation', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.equal(source.includes('search_cancel_event = threading.Event()'), true)
  assert.equal(source.includes('cancel_event=search_cancel_event'), true)
  assert.equal(source.includes('except SearchExecutionTimeoutError:'), true)
  assert.equal(source.includes('release_live_search_slot()'), true)
})

test('production queue timeout lets cached image searches wait without reaching Discord handler timeout', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('LIVE_IMAGE_SEARCH_MAX_INFLIGHT: "1"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS: "20.0"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS: "30.0"'), true)
})
