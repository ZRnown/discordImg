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

test('image attachment replies do not bypass channel review', () => {
  const source = readSource()
  const start = source.indexOf('async def handle_image')
  const end = source.indexOf('    async def recognize_image', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const handleImageSource = source.slice(start, end)
  assert.match(handleImageSource, /await self\.schedule_reply\(/)
  assert.doesNotMatch(handleImageSource, /skip_review_check=True/)
})

test('keyword image search runtime is disabled on main', () => {
  const source = readSource()

  assert.doesNotMatch(source, /keyword_image_search_service/)
  assert.doesNotMatch(source, /_run_keyword_image_search_for_website/)
  assert.doesNotMatch(source, /allow_keyword_image_search=not bool/)
})

test('image recognition uses the resolved reply threshold', () => {
  const source = readSource()

  assert.match(source, /threshold=skip_threshold/)
  assert.match(source, /form\.add_field\('threshold', str\(api_threshold\)\)/)
  assert.doesNotMatch(source, /form\.add_field\('threshold', '0'\)/)
  assert.doesNotMatch(source, /allow_below_threshold_link_only/)
  assert.doesNotMatch(source, /仅发送链接/)
})

test('low similarity image matches are skipped instead of sent', () => {
  const source = readSource()
  const start = source.indexOf('async def handle_image')
  const end = source.indexOf('    async def handle_keyword_forward', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const handleImageSource = source.slice(start, end)
  assert.match(handleImageSource, /图片命中未过阈值，跳过回复/)
  assert.match(handleImageSource, /return/)
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
