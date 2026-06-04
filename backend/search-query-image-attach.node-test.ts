import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('search query images can be attached to matched product gallery with metadata', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(databaseSource, /source_type TEXT DEFAULT 'scraped'/)
  assert.match(databaseSource, /source_search_history_id INTEGER/)
  assert.match(databaseSource, /def attach_search_history_query_image_to_product/)
  assert.match(databaseSource, /source_search_history_id/)
  assert.match(appSource, /@app\.route\('\/api\/search_history\/<int:history_id>\/attach-query-image'/)
  assert.match(appSource, /attach_search_history_query_image_to_product/)
  assert.match(appSource, /process_and_save_image_core/)
  assert.match(appSource, /source_type='search_query'/)
})

test('image search ui exposes attach actions for current results and each history record', () => {
  const source = readSource('frontend/components/image-search-view.tsx')

  assert.match(source, /handleAttachSearchImage/)
  assert.match(source, /\/api\/search_history\/\$\{historyId\}\/attach-query-image/)
  assert.match(source, /加入图库/)
  assert.match(source, /人工加入/)
  assert.match(source, /source_type/)
})
