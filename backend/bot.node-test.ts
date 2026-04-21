import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = () => {
  const candidates = [
    path.join(process.cwd(), 'backend/bot.py'),
    path.join(process.cwd(), 'bot.py'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find bot.py in: ${candidates.join(', ')}`)
}

test('reaction bark notification ignores missing messages instead of logging them as Bark failures', () => {
  const source = readSource()

  assert.match(source, /async def on_raw_reaction_add/)
  assert.match(source, /except discord\.NotFound/)
  assert.match(source, /return/)
})

test('approved review dispatch does not force plain sends', () => {
  const source = readSource()

  assert.match(source, /async def dispatch_keyword_review_item/)
  assert.doesNotMatch(source, /force_plain_send=True/)
})

test('low similarity image matches can fall back to link-only replies', () => {
  const source = readSource()

  assert.match(source, /allow_below_threshold_link_only/)
  assert.match(source, /form\.add_field\('threshold', '0'\)/)
  assert.match(source, /仅发送链接/)
})

test('thread reply mode resolves existing threads without creating new ones', () => {
  const source = readSource()

  assert.match(source, /disable_thread_creation=True/)
  assert.match(source, /thread_reply_enabled=thread_reply_enabled,\n\s+\)/)
  assert.match(source, /if thread_reply_enabled and not used_thread_reply:/)
  assert.match(source, /子区回复跳过/)
  assert.doesNotMatch(source, /create_thread = getattr\(target_channel, 'create_thread'/)
  assert.doesNotMatch(source, /await create_thread\(/)
})
