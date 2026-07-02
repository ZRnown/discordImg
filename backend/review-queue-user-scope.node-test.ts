import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('review queue stays scoped to the current login user including admins', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(appSource, /db\.get_keyword_reply_review_items\(\s*current_user\['id'\],/)
  assert.match(appSource, /db\.get_keyword_reply_review_item\(item_id, current_user\['id'\]\)/)
  assert.doesNotMatch(appSource, /review_user_id = None if current_user\.get\('role'\) == 'admin'/)
  assert.match(databaseSource, /def get_keyword_reply_review_items\(\s*self,\s*user_id: int,/)
  assert.match(databaseSource, /FROM keyword_reply_review_items\s+WHERE user_id = \?/)
})
