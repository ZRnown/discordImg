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

test('production warms fast vector contexts while scoped catalog cache stays disabled', () => {
  const source = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.match(source, /LIVE_IMAGE_SEARCH_STRATEGY: "siglip2_rerank"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_STARTUP_LOAD_SCOPED_CATALOGS: "1"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_ENABLED: "0"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_CACHE_SCOPES: "4"/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_PREPARE_MAX_WORKERS: "1"/)
  assert.match(source, /SIGLIP2_RERANK_FAST_RANK_CACHE_SCOPES: "4"/)
})

test('low cost production strategy reuses persisted SigLIP2 cache', () => {
  const configSource = readFileSync(new URL('./config.py', import.meta.url), 'utf8')
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const strategySource = readFileSync(new URL('./benchmarks/strategies.py', import.meta.url), 'utf8')

  assert.match(configSource, /LIVE_IMAGE_SEARCH_STRATEGY = os\.getenv\('LIVE_IMAGE_SEARCH_STRATEGY', 'siglip2_rerank'\)/)
  assert.match(strategySource, /name = "siglip2_rerank"/)
  assert.match(retrievalSource, /return str\(strategy_name or ""\)\.strip\(\) == "siglip2_rerank"/)
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

test('scoped catalog signatures ignore runtime-only concurrency settings', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(source, /_RUNTIME_SIGNATURE_EXCLUDED_ENV_KEYS/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_PREPARE_MAX_WORKERS/)
  assert.match(source, /LIVE_IMAGE_SEARCH_MAX_INFLIGHT/)
  assert.match(source, /if key in _RUNTIME_SIGNATURE_EXCLUDED_ENV_KEYS:/)
})

test('scoped catalog cache can be disabled so scoped searches stream through cached rows', () => {
  const source = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const start = source.indexOf('def search(')
  const end = source.indexOf('    def warm(', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const searchSource = source.slice(start, end)
  const streamingScopedBranchStart = searchSource.indexOf('            if shop_scope and self._supports_streaming_search(strategy)')
  const scopedBranchStart = searchSource.indexOf('            if shop_scope:', streamingScopedBranchStart)
  const scopedBranchEnd = searchSource.indexOf('            elif self._supports_streaming_search(strategy):', scopedBranchStart)
  assert.notEqual(streamingScopedBranchStart, -1)
  assert.notEqual(scopedBranchStart, -1)
  assert.notEqual(scopedBranchEnd, -1)
  const streamingScopedBranchSource = searchSource.slice(streamingScopedBranchStart, scopedBranchStart)
  const scopedBranchSource = searchSource.slice(scopedBranchStart, scopedBranchEnd)

  assert.match(source, /def _start_scoped_catalog_prepare_in_background/)
  assert.match(source, /def scoped_catalog_cache_enabled/)
  assert.match(source, /not scoped_catalog_cache_enabled\(\)/)
  assert.match(streamingScopedBranchSource, /return self\._search_streaming\(/)
  assert.match(source, /BoundedSemaphore/)
  assert.match(source, /LIVE_IMAGE_SEARCH_SCOPED_CATALOG_PREPARE_MAX_WORKERS/)
  assert.match(source, /raise LiveCatalogPreparingError\(\s*f"Scoped live retrieval catalog is preparing/)
  assert.match(source, /raise LiveCatalogPreparingError\(\s*f"Scoped live retrieval catalog is already preparing/)
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

test('production uses smaller SigLIP2 query images to reduce CPU encoding time', () => {
  const strategySource = readFileSync(new URL('./benchmarks/strategies.py', import.meta.url), 'utf8')
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.match(strategySource, /model_id = "google\/siglip2-base-patch16-224"/)
  assert.match(strategySource, /query_max_side = int\(os\.getenv\("SIGLIP2_RERANK_QUERY_MAX_SIDE", "192"\) or 192\)/)
  assert.match(ecosystemSource, /SIGLIP2_RERANK_QUERY_MAX_SIDE: "192"/)
})

test('startup strategy warmup runs a query encoder forward pass', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const strategySource = readFileSync(new URL('./benchmarks/strategies.py', import.meta.url), 'utf8')

  assert.match(strategySource, /def warm_query_encoder\(self\) -> bool:/)
  assert.match(strategySource, /__siglip_query_warmup__/)
  assert.match(retrievalSource, /warm_query_encoder = getattr\(strategy, "warm_query_encoder", None\)/)
  assert.match(retrievalSource, /"query_encoder_ready": query_encoder_ready/)
  assert.match(retrievalSource, /limit=1,/)
  assert.match(retrievalSource, /"sample_query_ready": sample_query_ready/)
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

test('image-only streaming search scans cached vectors in batches', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const databaseSource = readFileSync(new URL('./database.py', import.meta.url), 'utf8')

  assert.match(databaseSource, /def iter_searchable_product_image_vector_batches/)
  assert.match(retrievalSource, /def _supports_fast_cached_vector_streaming/)
  assert.match(retrievalSource, /def _search_cached_vector_streaming/)
  assert.match(retrievalSource, /iter_searchable_product_image_vector_batches/)
  assert.match(retrievalSource, /LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_CACHE_SCOPES/)
  assert.match(retrievalSource, /LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_SIGNATURE_TTL_SECONDS/)
  assert.match(retrievalSource, /fast_vector_cache/)
  assert.match(retrievalSource, /matrix = np\.vstack\(vectors\)/)
  assert.match(retrievalSource, /fast_cached_vectors/)
})

test('shop-scoped searchable signatures start from the shop index', () => {
  const databaseSource = readFileSync(new URL('./database.py', import.meta.url), 'utf8')

  assert.match(databaseSource, /FROM products p INDEXED BY idx_products_shop_name/)
  assert.match(databaseSource, /JOIN product_images pi INDEXED BY idx_product_images_product_id/)
  assert.match(databaseSource, /JOIN product_image_retrieval_cache rc INDEXED BY sqlite_autoindex_product_image_retrieval_cache_1/)
})

test('shop-scoped vector batches start from the shop index', () => {
  const databaseSource = readFileSync(new URL('./database.py', import.meta.url), 'utf8')
  const start = databaseSource.indexOf('def iter_searchable_product_image_vector_batches')
  const end = databaseSource.indexOf('    def count_searchable_product_image_records', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const body = databaseSource.slice(start, end)

  assert.match(body, /if normalized_shop_names:[\s\S]+FROM products p INDEXED BY idx_products_shop_name/)
  assert.match(body, /JOIN product_images pi INDEXED BY idx_product_images_product_id/)
  assert.match(body, /JOIN product_image_retrieval_cache rc INDEXED BY sqlite_autoindex_product_image_retrieval_cache_1/)
})

test('empty fast vector signatures do not scan vector batches', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const start = retrievalSource.indexOf('def _load_or_build_fast_vector_contexts')
  const end = retrievalSource.indexOf('    def prepare_fast_vector_context_for_warmup', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const body = retrievalSource.slice(start, end)

  assert.match(body, /signature_count = int\(\(signature\[2\] if len\(signature\) > 2 else 0\) or 0\)/)
  assert.match(body, /if shop_scope and signature_count <= 0:/)
  assert.match(body, /"empty_fast_vector_scope": True/)
  assert.equal(
    body.indexOf('if shop_scope and signature_count <= 0:') < body.indexOf('for rows in self.db.iter_searchable_product_image_vector_batches'),
    true,
  )
})

test('image-only streaming returns immediately for cached empty shop scopes', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(retrievalSource, /matrix\.shape\[0\] == 0/)
  assert.match(retrievalSource, /"empty_fast_vector_scope": True/)
})

test('image-only fast vector context persists to disk for large shops', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const ecosystemSource = readFileSync(new URL('../ecosystem.config.js', import.meta.url), 'utf8')

  assert.match(retrievalSource, /_FAST_VECTOR_CONTEXT_DISK_CACHE_VERSION/)
  assert.match(retrievalSource, /def _get_fast_vector_context_disk_cache_dir/)
  assert.match(retrievalSource, /def _load_fast_vector_contexts_from_disk/)
  assert.match(retrievalSource, /def _save_fast_vector_contexts_to_disk/)
  assert.match(retrievalSource, /np\.load\(matrix_path, mmap_mode=/)
  assert.match(retrievalSource, /LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_DISK_CACHE_DIR/)
  assert.match(ecosystemSource, /LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_CACHE_SCOPES: "64"/)
  assert.match(ecosystemSource, /LIVE_IMAGE_SEARCH_VECTOR_CONTEXT_SIGNATURE_TTL_SECONDS: "3600\.0"/)
})

test('fast vector context cache can be built offline before traffic', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')
  const scriptSource = readFileSync(new URL('./scripts/build_fast_vector_context_cache.py', import.meta.url), 'utf8')

  assert.match(retrievalSource, /def prepare_fast_vector_context_for_warmup/)
  assert.match(scriptSource, /build_user_shop_scope/)
  assert.match(scriptSource, /prepare_fast_vector_context_for_warmup/)
  assert.match(scriptSource, /--autostart-scopes/)
})

test('fast vector context loads are coalesced per shop scope', () => {
  const retrievalSource = readFileSync(new URL('./live_retrieval.py', import.meta.url), 'utf8')

  assert.match(retrievalSource, /class _FastVectorContextBuildState:/)
  assert.match(retrievalSource, /self\._fast_vector_context_inflight/)
  assert.match(retrievalSource, /existing_build = self\._fast_vector_context_inflight\.get\(cache_key\)/)
  assert.match(retrievalSource, /build_state\.finished\.wait/)
  assert.match(retrievalSource, /self\._fast_vector_context_inflight\.pop\(cache_key, None\)/)
})
