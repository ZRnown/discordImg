import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('search timeout releases the live search slot and propagates cancellation', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.equal(source.includes('search_cancel_event = threading.Event()'), true)
  assert.equal(source.includes('cancel_event=search_cancel_event'), true)
  assert.equal(source.includes('_submit_live_search_task('), true)
  assert.equal(source.includes('except SearchExecutionTimeoutError:'), true)
  assert.equal(source.includes('cancel_event.set()'), true)
})

test('production image search queues under load with two CPU-heavy workers', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('LIVE_IMAGE_SEARCH_MAX_INFLIGHT: "2"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE: "32"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS: "60.0"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS: "30.0"'), true)
  assert.equal(source.includes('DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS: "110.0"'), true)
})

test('production image reply does not skip top1 matches only because top1-top2 margin is close', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN: "0.00"'), true)
})

test('production slow message warning threshold matches queued image search latency', () => {
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')
  const configSource = readFileSync(new URL('./config.py', import.meta.url), 'utf8')
  const botSource = readFileSync(new URL('./bot.py', import.meta.url), 'utf8')

  assert.equal(ecosystemSource.includes('DISCORD_MESSAGE_STAGE_SLOW_SECONDS: "45.0"'), true)
  assert.equal(configSource.includes("DISCORD_MESSAGE_STAGE_SLOW_SECONDS = _env_float('DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0)"), true)
  assert.equal(botSource.includes("MESSAGE_STAGE_SLOW_SECONDS = max(float(getattr(config, 'DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0) or 5.0), 1.0)"), true)
})
