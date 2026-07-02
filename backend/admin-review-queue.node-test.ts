import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('admin review queue lists pending items across all users', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(appSource, /review_user_id = None if current_user\.get\('role'\) == 'admin' else current_user\['id'\]/)
  assert.match(appSource, /db\.get_keyword_reply_review_items\(\s*review_user_id,/)
  assert.match(databaseSource, /def get_keyword_reply_review_items\(\s*self,\s*user_id: int = None,/)
  assert.match(databaseSource, /if user_id is not None:[\s\S]*query \+= ' AND user_id = \?'/)
})

test('admin can approve or reject review items owned by ordinary users', () => {
  const appSource = readSource('backend/app.py')

  assert.match(appSource, /review_user_id = None if current_user\.get\('role'\) == 'admin' else current_user\['id'\]/)
  assert.match(appSource, /item = db\.get_keyword_reply_review_item\(item_id, review_user_id\)/)
  assert.match(appSource, /affected_user_ids\.add\(int\(item\.get\('user_id'\) or 0\)\)/)
})
