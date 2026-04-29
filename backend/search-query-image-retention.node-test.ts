import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('search query images use a dedicated retention directory and config', () => {
  const configSource = readSource('backend/config.py')
  const botSource = readSource('backend/bot.py')

  assert.match(configSource, /SEARCH_QUERY_IMAGE_DIR/)
  assert.match(configSource, /SEARCH_QUERY_IMAGE_RETENTION_DAYS/)
  assert.match(botSource, /SEARCH_QUERY_IMAGE_DIR/)
})

test('search route persists query images before saving search history', () => {
  const appSource = readSource('backend/app.py')

  assert.match(appSource, /def _persist_search_history_query_image/)
  assert.match(appSource, /persisted_query_image_path = _persist_search_history_query_image/)
  assert.match(appSource, /query_image_path=persisted_query_image_path or ''/)
  assert.doesNotMatch(appSource, /query_image_path=image_path/)
})

test('cleanup task removes expired search query images', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(databaseSource, /def cleanup_search_query_images/)
  assert.match(databaseSource, /SET query_image_path = ''/)
  assert.match(appSource, /db\.cleanup_search_query_images/)
})
