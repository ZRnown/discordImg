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

test('approved review dispatch preserves saved sender ids and thread targets', () => {
  const source = readSource()
  const start = source.indexOf('async def dispatch_keyword_review_item')
  const end = source.indexOf('def _build_multi_reply_content', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const dispatchSource = source.slice(start, end)
  assert.match(dispatchSource, /sender_ids_override=payload\.get\('selected_sender_ids'\) or review_item\.get\('account_ids'\)/)
  assert.match(dispatchSource, /saved_reply_target_payload=saved_reply_target_payload/)
  assert.match(dispatchSource, /strict_saved_reply_target=bool\(saved_reply_target_payload\.get\('used_thread_reply'\)\)/)
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

test('image recognition retrieves the best candidate before applying reply threshold', () => {
  const source = readSource()
  const start = source.indexOf('result = await self.recognize_image(')
  const end = source.indexOf('logger.debug(f"🔓 释放AI并发锁")', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const recognizeCallSource = source.slice(start, end)

  assert.match(recognizeCallSource, /threshold=0\.0/)
  assert.doesNotMatch(recognizeCallSource, /threshold=skip_threshold/)
  assert.match(source, /form\.add_field\('threshold', str\(api_threshold\)\)/)
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
  assert.match(handleImageSource, /图片命中未过阈值，记录略过历史并跳过回复/)
  assert.match(handleImageSource, /return False/)
})

test('image replies use a dedicated higher threshold before attaching product images', () => {
  const source = readSource()

  assert.match(source, /def _resolve_best_match_image_threshold/)
  assert.match(source, /def _should_send_best_match_reply_image/)
  assert.match(source, /best_match_image_base_threshold/)
  assert.match(source, /best_match_image_similarity_threshold/)
})

test('keyword replies from messages with attachments still respect keyword review', () => {
  const source = readSource()

  assert.match(source, /skip_keyword_review_check = False/)
  assert.doesNotMatch(source, /skip_keyword_review_check = bool\(getattr\(message, 'attachments', None\)\)/)
})

test('skipped image matches are also saved into search history', () => {
  const source = readSource()
  const start = source.indexOf('async def _record_skipped_image_history')
  const end = source.indexOf('    async def schedule_reply', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const skippedSource = source.slice(start, end)
  assert.match(skippedSource, /db\.add_search_history/)
  assert.match(skippedSource, /is_skipped=True/)
})

test('text messages with image attachments skip image recognition after keyword search', () => {
  const source = readSource()
  const start = source.indexOf('# 处理关键词搜索')
  const end = source.indexOf('    async def on_raw_reaction_add', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const onMessageTailSource = source.slice(start, end)
  assert.match(onMessageTailSource, /message_has_text_content = bool\(\(getattr\(message, 'content', ''\) or ''\)\.strip\(\)\)/)
  assert.match(onMessageTailSource, /if image_reply_enabled and message\.attachments and not keyword_search_hit:/)
  assert.match(onMessageTailSource, /if message_has_text_content and keyword_reply_enabled:/)
  assert.match(onMessageTailSource, /图文消息已处理文字关键词路径，跳过图片识别/)
})

test('thread reply mode falls back to the source channel without creating new threads', () => {
  const source = readSource()

  assert.match(source, /disable_thread_creation=True/)
  assert.match(source, /thread_reply_enabled=thread_reply_enabled or saved_reply_target_requested,\n\s+\)/)
  assert.match(source, /if thread_reply_enabled and not used_thread_reply:/)
  assert.match(source, /子区回复回退/)
  assert.match(source, /_resolve_archived_reply_thread/)
  assert.match(source, /archived_threads\(private=private, limit=100\)/)
  assert.doesNotMatch(source, /子区回复跳过/)
  assert.doesNotMatch(source, /create_thread = getattr\(target_channel, 'create_thread'/)
  assert.doesNotMatch(source, /await create_thread\(/)
})

test('messages that already indicate an existing thread do not fall back to the parent channel', () => {
  const source = readSource()

  assert.match(source, /def _message_has_existing_thread_hint\(message\):/)
  assert.match(source, /getattr\(flags, 'has_thread', False\)/)
  assert.match(source, /源消息声明存在子区，但当前发送账号无法进入，拒绝回退到原频道/)
})
