# SigLIP2 Cache Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate product image retrieval to persisted `siglip2_rerank` catalog cache so product scraping writes retrieval-ready cache, startup backfills missing cache in the background, `/search_similar` reads only the new cache, and old product-search FAISS/DINO indexing code is removed.

**Architecture:** Add a dedicated retrieval cache table keyed by `image_db_id + strategy_name`, store serialized catalog context needed by `siglip2_rerank`, and teach live retrieval to hydrate catalog rows from that table. Replace product-image save and backfill flows so they compute SigLIP2 cache once and persist it, while query-time retrieval only computes the query image context and scores against cached catalog context.

**Tech Stack:** Flask, SQLite, existing `backend/benchmarks/strategies.py` SigLIP2 code, Python tests with `pytest`

---

### Task 1: Add failing tests for the new cache-backed retrieval behavior

**Files:**
- Modify: `backend/tests/test_live_retrieval.py`
- Create: `backend/tests/test_retrieval_cache_database.py`

**Step 1: Write a failing test for cache-aware live catalog rows**

Add a test that builds catalog rows with serialized SigLIP2 cache payload and asserts `build_catalog_records()` deserializes them onto the record.

**Step 2: Run the targeted test to verify it fails**

Run: `python3 -m pytest -p no:cacheprovider backend/tests/test_live_retrieval.py -k cache`

Expected: FAIL because cached retrieval fields do not exist yet.

**Step 3: Write a failing database test for the new cache table**

Add a temp-DB-backed test that inserts a product image, upserts retrieval cache, and expects `get_searchable_product_image_records(strategy_name=...)` to expose cache fields.

**Step 4: Run the new database test to verify it fails**

Run: `python3 -m pytest -p no:cacheprovider backend/tests/test_retrieval_cache_database.py`

Expected: FAIL because the table and DAO methods do not exist yet.

### Task 2: Add database schema and DAO methods for SigLIP2 retrieval cache

**Files:**
- Modify: `backend/database.py`

**Step 1: Add the new cache table and indexes**

Create `product_image_retrieval_cache` with unique `(image_db_id, strategy_name)` and fields for serialized embedding, color histogram, tokens, cache version, created/updated timestamps.

**Step 2: Add DAO helpers**

Implement:
- `upsert_product_image_retrieval_cache(...)`
- `delete_product_image_retrieval_cache(...)`
- `get_missing_product_image_retrieval_cache_rows(...)`
- `count_product_image_retrieval_cache(...)`
- extend `get_searchable_product_image_records(strategy_name=...)`

**Step 3: Run targeted tests**

Run: `python3 -m pytest -p no:cacheprovider backend/tests/test_retrieval_cache_database.py`

Expected: PASS

### Task 3: Teach SigLIP2 rerank to read and write cache payloads

**Files:**
- Modify: `backend/benchmarks/strategies.py`
- Modify: `backend/live_retrieval.py`

**Step 1: Add cache serialization helpers to `Siglip2RerankStrategy`**

Implement methods to:
- build catalog cache payload
- hydrate catalog context from cached payload
- fall back to live computation only if cache is missing

**Step 2: Extend live retrieval records to carry cached payload**

Update `LiveCatalogImageRecord` and `build_catalog_records()` so joined cache columns are deserialized and passed through to the strategy.

**Step 3: Add a backfill helper**

Implement an incremental backfill function that loads rows missing cache, computes cache payload, and persists it.

**Step 4: Run targeted tests**

Run: `python3 -m pytest -p no:cacheprovider backend/tests/test_live_retrieval.py backend/tests/test_benchmark_strategies.py`

Expected: PASS

### Task 4: Switch product image ingestion to write SigLIP2 cache directly

**Files:**
- Modify: `backend/app.py`

**Step 1: Replace old product-image DINO/FAISS indexing in upload helpers**

Update `process_and_save_image_core()` and `save_product_images_unified()` so product images:
- compute SigLIP2 cache payload
- use cached embedding for duplicate detection
- persist image rows without old product-search `features`
- persist new retrieval cache rows

**Step 2: Update legacy `/scrape` route to use the same unified flow**

Remove direct FAISS indexing logic and route it through the shared cache-producing save path.

**Step 3: Run targeted tests**

Run: `python3 -m pytest -p no:cacheprovider backend/tests/test_live_retrieval.py backend/tests/test_bot_image_query_text.py backend/tests/test_benchmark_strategies.py`

Expected: PASS

### Task 5: Warm cache at startup and switch runtime metrics to the new cache

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/database.py`

**Step 1: Start background cache warmup on app startup**

After AI warmup, launch a daemon thread that backfills missing cache for `LIVE_IMAGE_SEARCH_STRATEGY` without blocking Flask startup.

**Step 2: Point runtime counts to the new cache**

Update indexed-image and indexed-product helpers to reflect cache-backed retrieval readiness instead of FAISS.

**Step 3: Run targeted tests and smoke checks**

Run:
- `python3 -m py_compile backend/app.py backend/database.py backend/live_retrieval.py backend/benchmarks/strategies.py`
- `python3 -m pytest -p no:cacheprovider backend/tests/test_retrieval_cache_database.py backend/tests/test_live_retrieval.py backend/tests/test_benchmark_strategies.py backend/tests/test_bot_image_query_text.py`

Expected: PASS

### Task 6: Delete old product-search FAISS/DINO code after cache path is verified

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/database.py`
- Delete or stop referencing: `backend/vector_engine.py`, `backend/fix_index.py` if no remaining callers

**Step 1: Remove old product-search-only FAISS endpoints and helpers**

Delete or stop exposing:
- FAISS rebuild/debug endpoints
- product-search FAISS writes/deletes/counts
- old “index” wording tied to FAISS for product retrieval

Keep image-filter feature extraction paths intact.

**Step 2: Run full targeted verification**

Run:
- `python3 -m py_compile backend/app.py backend/database.py backend/live_retrieval.py backend/benchmarks/strategies.py`
- `python3 -m pytest -p no:cacheprovider backend/tests/test_retrieval_cache_database.py backend/tests/test_live_retrieval.py backend/tests/test_benchmark_fetch_dataset.py backend/tests/test_benchmark_item_sets.py backend/tests/test_benchmark_reporting.py backend/tests/test_benchmark_runner.py backend/tests/test_benchmark_strategies.py backend/tests/test_retrieval_benchmark_common.py backend/tests/test_bot_image_query_text.py`

Expected: PASS
