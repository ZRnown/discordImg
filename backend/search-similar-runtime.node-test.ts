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

test('production image search fails fast under load with one low-memory streaming worker', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('LIVE_IMAGE_SEARCH_MAX_INFLIGHT: "1"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE: "128"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS: "10.0"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS: "90.0"'), true)
  assert.equal(source.includes('DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS: "120.0"'), true)
  assert.equal(source.includes('DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS: "140"'), true)
})

test('production image reply does not skip top1 matches only because top1-top2 margin is close', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN: "0.00"'), true)
})

test('production query fusion is disabled on CPU to reduce per-image encoding time', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('SIGLIP2_RERANK_QUERY_FUSION: "0"'), true)
  assert.equal(source.includes('SIGLIP2_RERANK_QUERY_RAW_WEIGHT: "1.00"'), true)
  assert.equal(source.includes('SIGLIP2_RERANK_QUERY_CENTER_WEIGHT: "0.00"'), true)
})

test('production slow message warning threshold matches queued image search latency', () => {
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')
  const configSource = readFileSync(new URL('./config.py', import.meta.url), 'utf8')
  const botSource = readFileSync(new URL('./bot.py', import.meta.url), 'utf8')

  assert.equal(ecosystemSource.includes('DISCORD_MESSAGE_STAGE_SLOW_SECONDS: "45.0"'), true)
  assert.equal(configSource.includes("DISCORD_MESSAGE_STAGE_SLOW_SECONDS = _env_float('DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0)"), true)
  assert.equal(botSource.includes("MESSAGE_STAGE_SLOW_SECONDS = max(float(getattr(config, 'DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0) or 5.0), 1.0)"), true)
})

test('image search skips product retrieval when the resolved shop scope is empty', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.equal(source.includes('empty_shop_scope = user_shops is not None and not user_shops'), true)
  assert.match(source, /if empty_shop_scope:[\s\S]+?return jsonify\(response_data\)/)
  assert.equal(source.indexOf('if empty_shop_scope:'), source.lastIndexOf('if empty_shop_scope:'))
  assert.equal(source.indexOf('if empty_shop_scope:' ) < source.indexOf('retriever = live_retrieval_module.get_live_image_retriever'), true)
})

test('slow image search logs include image preparation and retrieval queue timing', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.equal(source.includes('image_stage_elapsed'), true)
  assert.equal(source.includes("'queue_wait_elapsed'"), true)
  assert.equal(source.includes("'execution_elapsed'"), true)
  assert.match(source, /"search_similar slow request: total=%\.2fs image_stage=%\.2fs filter_stage=%\.2fs retrieval=%\.2fs queue_wait=%\.2fs execution=%\.2fs/)
})
