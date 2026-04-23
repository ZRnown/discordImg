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

test('low similarity image matches are skipped before reply dispatch', () => {
  const source = readSource()

  assert.match(source, /async def recognize_image\(self, image_data, user_shops=None, threshold=None\):/)
  assert.match(source, /form\.add_field\('threshold', str\(api_threshold\)\)/)
  assert.match(source, /below_reply_threshold = similarity < skip_threshold/)
  assert.match(source, /跳过回复/)
})

test('image reply flow still respects channel review switches', () => {
  const source = readSource()

  assert.match(source, /async def handle_image/)
  assert.doesNotMatch(source, /website_configs_override=website_configs,\n\s+skip_review_check=True,/)
})

test('thread reply mode resolves existing threads without creating new ones', () => {
  const source = readSource()

  assert.match(source, /disable_thread_creation=True/)
  assert.match(source, /thread_reply_enabled=thread_reply_enabled,/)
  assert.match(source, /if thread_reply_enabled and not used_thread_reply:/)
  assert.doesNotMatch(source, /create_thread = getattr\(target_channel, 'create_thread'/)
  assert.doesNotMatch(source, /await create_thread\(/)
})
