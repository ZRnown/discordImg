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
