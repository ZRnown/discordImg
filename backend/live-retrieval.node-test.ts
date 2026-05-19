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

test('production keeps scoped catalog caches within memory limits', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.match(source, /LIVE_IMAGE_SEARCH_STARTUP_LOAD_SCOPED_CATALOGS: "1"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_CACHE_SCOPES: "16"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_PREPARE_MAX_WORKERS: "1"/)
  assert.match(source, /SIGLIP2_RERANK_FAST_RANK_CACHE_SCOPES: "16"/)
})

test('startup scoped catalog cache loading runs in the background', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')

  assert.match(source, /def _schedule_scoped_live_image_catalog_warmup/)
  assert.match(source, /threading\.Thread\(/)
  assert.match(source, /name="live-scoped-catalog-startup-warmup"/)
  assert.match(source, /已启动店铺检索目录缓存后台加载/)
  assert.doesNotMatch(source, /正在加载已有店铺检索目录缓存/)
})

test('startup scoped catalog warmup builds missing disk caches', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(source, /def prepare_scoped_catalog_for_warmup/)
  assert.match(source, /self\._build_prepared_catalog_snapshot_for_shops\(shop_scope\)/)
  assert.match(source, /retriever\.prepare_scoped_catalog_for_warmup\(scope\)/)
  assert.match(source, /"prepared": prepared/)
})

test('scoped catalog cache misses prepare in background instead of streaming through requests', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const start = source.indexOf('def search(')
  const end = source.indexOf('    def warm(', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const searchSource = source.slice(start, end)
  const scopedBranchStart = searchSource.indexOf('            if shop_scope:')
  const scopedBranchEnd = searchSource.indexOf('            elif self._supports_streaming_search(strategy):', scopedBranchStart)
  assert.notEqual(scopedBranchStart, -1)
  assert.notEqual(scopedBranchEnd, -1)
  const scopedBranchSource = searchSource.slice(scopedBranchStart, scopedBranchEnd)

  assert.match(source, /def _start_scoped_catalog_prepare_in_background/)
  assert.match(source, /BoundedSemaphore/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_PREPARE_MAX_WORKERS/)
  assert.match(source, /raise LiveCatalogPreparingError\(\s*f"Scoped live retrieval catalog is preparing/)
  assert.match(source, /raise LiveCatalogPreparingError\(\s*f"Scoped live retrieval catalog is already preparing/)
  assert.doesNotMatch(scopedBranchSource, /self\._search_streaming\(/)
})

test('streaming search reuses cached query context for duplicate Discord images', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const start = source.indexOf('def _search_streaming')
  const end = source.indexOf('    def search(', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const streamingSource = source.slice(start, end)
  assert.match(streamingSource, /query_context = self\._get_cached_query_context\(image_path, query_text\)/)
  assert.match(streamingSource, /query_context_cache_hit = query_context is not None/)
  assert.match(streamingSource, /self\._store_cached_query_context\(image_path, query_text, query_context\)/)
  assert.match(streamingSource, /query_cache_hit=%s/)
})

test('production can use image-only SigLIP2 scoring to avoid rerank overhead', () => {
  const strategySource = readFileSync(new URL('./benchmarks/strategies.py', import.meta.url), 'utf8')
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.match(strategySource, /SIGLIP2_RERANK_IMAGE_ONLY/)
  assert.match(strategySource, /image_only_enabled/)
  assert.match(strategySource, /if self\.image_only_enabled:/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_IMAGE_ONLY: "1"/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_IMAGE_WEIGHT: "1\.00"/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_COLOR_WEIGHT: "0\.00"/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_TEXT_WEIGHT: "0\.00"/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_CATEGORY_WEIGHT: "0\.00"/)
})

test('prepared catalog strips duplicated cached vectors from records', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(source, /def _strip_catalog_record_cache_payload/)
  assert.match(source, /cache_embedding=None/)
  assert.match(source, /cache_color_hist=None/)
  assert.match(source, /cache_tokens=\[\]/)
  assert.match(source, /"record": _strip_catalog_record_cache_payload\(record\)/)
})

test('image-only fast rank aggregates only top candidate images', () => {
  const source = readFileSync(new URL('./benchmarks/strategies.py', import.meta.url), 'utf8')

  assert.match(source, /def _rank_selected_precomputed_product_scores/)
  assert.match(source, /candidate_indices = np\.argpartition\(image_scores, -candidate_k\)\[-candidate_k:\]/)
  assert.match(source, /return self\._rank_selected_precomputed_product_scores\(/)
})
