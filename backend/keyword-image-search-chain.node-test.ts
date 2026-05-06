import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('keyword image search jobs API is enabled', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.equal(source.includes('关键词搜图功能已在当前分支移除'), false)
  assert.equal(source.includes("return jsonify({'jobs': [], 'disabled': True"), false)
})

test('bot creates keyword image search jobs from keyword matches', () => {
  const source = readFileSync(new URL('./bot.py', import.meta.url), 'utf8')

  assert.match(source, /keyword_image_search_service\.search_candidates/)
  assert.match(source, /db\.create_keyword_image_search_job/)
  assert.match(source, /keyword_image_job_created = True/)
})

test('keyword image search sends query text into internal image retrieval', () => {
  const source = readFileSync(new URL('./keyword_image_search.py', import.meta.url), 'utf8')

  assert.match(source, /searchapi_google_maps/)
  assert.match(source, /engine": "google_maps"/)
  assert.match(source, /query_text=query_text/)
  assert.match(source, /payload\["query_text"\] = query_text/)
})

test('live retrieval preserves optional keyword context for category reranking', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(source, /normalized_query_text = " "\.join/)
  assert.match(source, /query=normalized_query_text/)
  assert.match(source, /product_queries=\(\[normalized_query_text\] if normalized_query_text else \[\]\)/)
})
