import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

test('binary retrieval cache migration script is explicit and opt-in', () => {
  const scriptPath = path.join(process.cwd(), 'backend/scripts/build_binary_retrieval_cache.py')
  assert.equal(existsSync(scriptPath), true)

  const source = readFileSync(scriptPath, 'utf8')
  assert.match(source, /RETRIEVAL_CACHE_BINARY_STORAGE_ENABLED/)
  assert.match(source, /--clear-legacy-json/)
  assert.match(source, /--vacuum/)
  assert.match(source, /count_missing_product_image_retrieval_cache/)
  assert.match(source, /backfill_product_image_retrieval_cache/)
})
