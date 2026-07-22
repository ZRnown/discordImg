import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('live search runtime can wait without dropping queued image searches', () => {
  const appSource = readFileSync(new URL('./app.py', import.meta.url), 'utf8')
  const runtimeSource = readFileSync(new URL('./live_search_runtime.py', import.meta.url), 'utf8')

  assert.equal(appSource.includes('search_cancel_event = threading.Event()'), true)
  assert.equal(appSource.includes('cancel_event=search_cancel_event'), true)
  assert.equal(appSource.includes('_submit_live_search_task('), true)
  assert.match(runtimeSource, /if queue_timeout > 0:[\s\S]+?else:\s+self\.started\.wait\(\)/)
  assert.match(runtimeSource, /if execution_timeout > 0:[\s\S]+?else:\s+self\.finished\.wait\(\)/)
})

test('production image search fails stuck work quickly enough to keep workers free', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.equal(source.includes('LIVE_IMAGE_SEARCH_MAX_INFLIGHT: "2"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE: "0"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS: "30"'), true)
  assert.equal(source.includes('LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS: "45"'), true)
  assert.equal(source.includes('DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS: "60.0"'), true)
  assert.equal(source.includes('DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS: "90"'), true)
  assert.equal(source.includes('DISCORD_SEND_TIMEOUT_SECONDS: "20"'), true)
})

test('production image encoding uses multiple CPU threads per cold query', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')
  const pythonApiStart = source.indexOf('name: "python-api"')
  assert.notEqual(pythonApiStart, -1)
  const pythonApiSource = source.slice(pythonApiStart)

  assert.match(pythonApiSource, /AI_INTRA_THREADS: "4"/)
  assert.match(pythonApiSource, /LIVE_IMAGE_SEARCH_MAX_INFLIGHT: "2"/)
})

test('live search runtime treats zero queue size as unbounded', () => {
  const source = readFileSync(new URL('./live_search_runtime.py', import.meta.url), 'utf8')

  assert.match(source, /queue_capacity = 0 if self\.max_queue_size <= 0 else self\.max_queue_size/)
  assert.match(source, /queue\.Queue\(maxsize=queue_capacity\)/)
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

test('startup warmup prepares fast vector contexts for autostart shop scopes', () => {
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.equal(ecosystemSource.includes('LIVE_IMAGE_SEARCH_STARTUP_LOAD_SCOPED_CATALOGS: "1"'), true)
  assert.equal(ecosystemSource.includes('LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_CACHE_SCOPES: "64"'), true)
  assert.match(retrievalSource, /prepare_fast_vector_context_for_warmup\(scope\)/)
  assert.match(retrievalSource, /fast_vector_prepared/)
})

test('bot does not retry image recognition long enough to block Discord workers', () => {
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')
  const configSource = readFileSync(new URL('./config.py', import.meta.url), 'utf8')
  const botSource = readFileSync(new URL('./bot.py', import.meta.url), 'utf8')

  assert.equal(ecosystemSource.includes('DISCORD_IMAGE_RECOGNITION_MAX_INFLIGHT: "4"'), true)
  assert.equal(ecosystemSource.includes('DISCORD_IMAGE_RECOGNITION_MAX_ATTEMPTS: "1"'), true)
  assert.equal(ecosystemSource.includes('DISCORD_IMAGE_RECOGNITION_RETRY_DELAY_SECONDS: "1.0"'), true)
  assert.match(configSource, /DISCORD_IMAGE_RECOGNITION_MAX_INFLIGHT = _env_int/)
  assert.match(configSource, /DISCORD_IMAGE_RECOGNITION_MAX_ATTEMPTS = _env_int/)
  assert.match(configSource, /DISCORD_IMAGE_RECOGNITION_RETRY_DELAY_SECONDS = _env_float/)
  assert.match(configSource, /DISCORD_SEND_TIMEOUT_SECONDS = _env_float/)
  assert.match(botSource, /IMAGE_RECOGNITION_MAX_INFLIGHT/)
  assert.match(botSource, /IMAGE_RECOGNITION_MAX_ATTEMPTS/)
  assert.match(botSource, /DISCORD_SEND_TIMEOUT_SECONDS/)
  assert.match(botSource, /resp\.status in \{429, 503\}/)
})
