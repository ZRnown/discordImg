import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readBackendSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('review queue sends a per-item Bark notification with a signed action URL', () => {
  const source = readBackendSource('backend/bot.py')

  assert.match(source, /def _create_keyword_review_action_token/)
  assert.match(source, /KEYWORD_REVIEW_ACTION_TOKEN_SALT = ["']keyword-review-action["']/)
  assert.match(source, /\/review-actions\/\{quote\(token, safe=["']["']\)\}/)
  assert.match(source, /async def _send_keyword_review_item_bark_notification/)
  assert.match(source, /jump_url=action_url or None/)
  assert.match(source, /review-bark-item user=\{self\.user_id\} item=\{queued_review_id\}/)
})
