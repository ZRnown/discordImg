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

const readAppSource = () => {
  const candidates = [
    path.join(process.cwd(), 'backend/app.py'),
    path.join(process.cwd(), 'app.py'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find app.py in: ${candidates.join(', ')}`)
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

test('approved review action can be dispatched by workers without API bot loop', () => {
  const source = readAppSource()
  const start = source.indexOf('def _apply_keyword_review_action')
  const end = source.indexOf('def _format_keyword_review_item_summary', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const reviewActionSource = source.slice(start, end)
  assert.match(source, /def is_review_worker_dispatch_enabled\(\):/)
  assert.match(reviewActionSource, /if normalized_action == "approved" and not is_review_worker_dispatch_enabled\(\):/)
  assert.doesNotMatch(reviewActionSource, /if normalized_action == "approved":\s*scheduled, schedule_result = schedule_keyword_review_item_dispatch\(item\)/)
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

test('keyword image search runtime creates jobs from keyword matches', () => {
  const source = readSource()

  assert.match(source, /keyword_image_search_service\.search_candidates/)
  assert.match(source, /db\.create_keyword_image_search_job/)
  assert.match(source, /keyword_image_job_created = True/)
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
  assert.match(source, /form\.add_field\('suppress_search_history', '1'\)/)
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

test('keyword review queue deduplicates text and image hits from the same message', () => {
  const source = readSource()
  const start = source.indexOf('def _queue_keyword_review_item')
  const end = source.indexOf('    def _should_ignore_mass_or_activity_message', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const queueSource = source.slice(start, end)
  assert.match(queueSource, /get_active_keyword_reply_review_item_by_message/)
  assert.match(queueSource, /同一消息已存在待审项/)
  assert.match(queueSource, /return int\(existing_review_item\.get\('id'\) or 0\)/)
})

test('skipped image matches are also saved into search history', () => {
  const source = readSource()
  const start = source.indexOf('async def _record_image_search_history')
  const end = source.indexOf('    async def schedule_reply', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const skippedSource = source.slice(start, end)
  assert.match(skippedSource, /db\.add_search_history/)
  assert.match(skippedSource, /is_skipped=True/)
  assert.match(skippedSource, /add_skipped_image_history=True/)
})

test('successful discord image matches are saved into search history with channel metadata', () => {
  const source = readSource()
  const start = source.indexOf('reply_sent = await self.schedule_reply(')
  const end = source.indexOf("logger.debug(f'图片识别完成", start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const successSource = source.slice(start, end)
  assert.match(successSource, /if reply_sent:/)
  assert.match(successSource, /self\._record_image_search_history/)
  assert.match(successSource, /threshold=skip_threshold/)
  assert.match(successSource, /is_skipped=False/)
})

test('discord image searches without a candidate are not saved as zero-similarity skipped matches', () => {
  const source = readSource()
  const start = source.indexOf("elif result and result.get('success'):")
  const end = source.indexOf('        except Exception as e:', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const noCandidateSource = source.slice(start, end)
  assert.doesNotMatch(noCandidateSource, /_record_skipped_image_history/)
  assert.doesNotMatch(noCandidateSource, /similarity=0\\.0/)
  assert.match(noCandidateSource, /图片未命中任何商品，跳过历史记录/)
})

test('backend suppresses generic search history for internal bot image retrieval', () => {
  const source = readAppSource()
  assert.match(source, /suppress_search_history = /)
  assert.match(source, /if processed_results and not suppress_search_history:/)
})

test('text messages with image attachments still run image recognition after keyword search', () => {
  const source = readSource()
  const start = source.indexOf('# 处理关键词搜索')
  const end = source.indexOf('    async def on_raw_reaction_add', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const onMessageTailSource = source.slice(start, end)
  assert.match(onMessageTailSource, /if image_reply_enabled and message\.attachments:/)
  assert.doesNotMatch(onMessageTailSource, /if image_reply_enabled and message\.attachments and not keyword_search_hit:/)
  assert.doesNotMatch(onMessageTailSource, /图文消息已处理文字关键词路径，跳过图片识别/)
})

test('keyword search is scheduled in background so message handling is not blocked', () => {
  const source = readSource()
  const start = source.indexOf('# 处理关键词搜索')
  const end = source.indexOf('# 处理图片', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const keywordStageSource = source.slice(start, end)
  assert.match(source, /def _start_keyword_search_background_task/)
  assert.match(source, /关键词搜索后台超时/)
  assert.match(keywordStageSource, /self\._start_keyword_search_background_task\(\s*message,\s*website_configs_to_process,\s*\)/)
  assert.doesNotMatch(keywordStageSource, /await self\._run_message_stage_with_timeout/)
  assert.doesNotMatch(keywordStageSource, /'keyword_search'/)
})

test('background keyword search is deduplicated per channel message', () => {
  const source = readSource()
  const start = source.indexOf('def _start_keyword_search_background_task')
  const end = source.indexOf('    def _start_image_reply_background_task', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const keywordTaskSource = source.slice(start, end)
  assert.match(keywordTaskSource, /keyword_search_message_id = f"keyword_search:\{message\.channel\.id\}:\{message\.id\}"/)
  assert.match(keywordTaskSource, /mark_message_as_processed\(keyword_search_message_id\)/)
  assert.match(keywordTaskSource, /关键词搜索后台已由其他账号处理/)
})

test('discord message dedupe can use a remote processed-message lock', () => {
  const source = readSource()
  const appSource = readAppSource()

  assert.match(source, /def _claim_remote_processed_message/)
  assert.match(source, /PROCESSED_MESSAGE_LOCK_URL/)
  assert.match(source, /X-Processed-Message-Lock-Token/)
  assert.match(source, /remote_result = _claim_remote_processed_message\(scoped_message_id\)/)
  assert.match(appSource, /@app\.route\('\/api\/internal\/processed-message-lock', methods=\['POST'\]\)/)
  assert.match(appSource, /INSERT INTO processed_messages \(message_id\) VALUES \(\?\)/)
  assert.match(appSource, /except sqlite3\.IntegrityError:/)
  assert.match(appSource, /"claimed": False/)
})

test('managed account authors do not trigger product replies from other managed accounts', () => {
  const source = readSource()
  const start = source.indexOf('def _should_allow_managed_account_trigger')
  const end = source.indexOf('    def _log_message_skip', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const managedTriggerSource = source.slice(start, end)
  assert.match(managedTriggerSource, /return False/)
  assert.doesNotMatch(managedTriggerSource, /_is_plain_text_keyword_trigger_candidate/)
})

test('generated reply site links are skipped before product search', () => {
  const source = readSource()
  const start = source.indexOf('async def on_message')
  const end = source.indexOf('        # 3. 忽略 @别人的信息', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const onMessageSource = source.slice(start, end)
  assert.match(source, /_DEFAULT_GENERATED_REPLY_DOMAINS = \{[\s\S]*'hipobuy\.com'/)
  assert.match(source, /def _message_contains_generated_reply_url/)
  assert.match(onMessageSource, /_message_contains_generated_reply_url\(message, website_configs\)/)
  assert.match(onMessageSource, /已包含推广站链接/)
})

test('batched reply content removes duplicate links', () => {
  const source = readSource()
  const start = source.indexOf('def _build_multi_reply_content')
  const end = source.indexOf('def _should_mention_reply_author', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const multiReplySource = source.slice(start, end)
  assert.match(source, /def _dedupe_reply_content_urls/)
  assert.match(multiReplySource, /seen_contents = set\(\)/)
  assert.match(multiReplySource, /_dedupe_reply_content_urls\(content\)/)
  assert.match(multiReplySource, /if normalized in seen_contents:/)
})

test('message processing is deduplicated across users before keyword and image work', () => {
  const source = readSource()
  const start = source.indexOf('async def on_message')
  const end = source.indexOf('        website_configs_to_process = list(website_configs or [])', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const onMessageSource = source.slice(start, end)
  assert.match(onMessageSource, /mark_message_as_processed\(message\.id\)/)
  assert.doesNotMatch(onMessageSource, /mark_message_as_processed\(message\.id,\s*self\.user_id\)/)
})

test('background keyword search disables keyword image search work', () => {
  const source = readSource()
  const taskStart = source.indexOf('def _start_keyword_search_background_task')
  const taskEnd = source.indexOf('    def _start_image_reply_background_task', taskStart)
  const imageStart = source.indexOf('async def _run_keyword_image_search_for_context')
  const imageEnd = source.indexOf('            for website_context in website_match_contexts:', imageStart)
  assert.notEqual(taskStart, -1)
  assert.notEqual(taskEnd, -1)
  assert.notEqual(imageStart, -1)
  assert.notEqual(imageEnd, -1)

  const keywordTaskSource = source.slice(taskStart, taskEnd)
  const imageSearchSource = source.slice(imageStart, imageEnd)
  assert.match(keywordTaskSource, /allow_keyword_image_search=False/)
  assert.match(imageSearchSource, /if not allow_keyword_image_search:\s+return False, False/)
})

test('reply scheduling revalidates overridden website configs against current channel bindings', () => {
  const source = readSource()
  const start = source.indexOf('async def schedule_reply')
  const end = source.indexOf('    async def handle_image', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const scheduleReplySource = source.slice(start, end)
  assert.match(scheduleReplySource, /if website_configs_override is not None and website_configs:/)
  assert.match(scheduleReplySource, /current_configs = await self\.get_website_configs_by_channel_async\(message\.channel\)/)
  assert.match(scheduleReplySource, /current_config_by_id = \{/)
  assert.match(scheduleReplySource, /if not website_configs:\s+logger\.info\(\s+f"频道 \{message\.channel\.id\} 的网站配置已不再绑定当前用户，跳过回复"/)
  assert.match(scheduleReplySource, /return False/)
})

test('keyword search slow logs include stage timings', () => {
  const source = readSource()
  const start = source.indexOf('async def handle_keyword_search')
  const end = source.indexOf('    async def search_products_by_keyword', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const keywordSource = source.slice(start, end)
  assert.match(keywordSource, /keyword_stage_timings = \{\}/)
  assert.match(keywordSource, /_record_keyword_stage\('text_search'/)
  assert.match(keywordSource, /_record_keyword_stage\('keyword_image_search'/)
  assert.match(keywordSource, /_record_keyword_stage\('reply_loop'/)
  assert.match(keywordSource, /关键词搜索步骤耗时/)
})

test('image recognition is scheduled in the background so keyword replies are not blocked by live search', () => {
  const source = readSource()
  const start = source.indexOf('# 处理图片')
  const end = source.indexOf('    async def on_raw_reaction_add', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const imageStageSource = source.slice(start, end)
  assert.match(imageStageSource, /self\._start_image_reply_background_task\(/)
  assert.doesNotMatch(imageStageSource, /await self\._run_message_stage_with_timeout\(\s*message,\s*f'image_reply:/)
})

test('image reply limits per-message attachments to avoid flooding live search', () => {
  const source = readSource()
  const start = source.indexOf('# 处理图片')
  const end = source.indexOf('    async def on_raw_reaction_add', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const imageStageSource = source.slice(start, end)
  assert.match(source, /MESSAGE_IMAGE_REPLY_MAX_ATTACHMENTS = max\(/)
  assert.match(imageStageSource, /scheduled_image_replies = 0/)
  assert.match(imageStageSource, /if scheduled_image_replies >= MESSAGE_IMAGE_REPLY_MAX_ATTACHMENTS:/)
  assert.match(imageStageSource, /跳过多余图片附件/)
  assert.match(imageStageSource, /scheduled_image_replies \+= 1/)
})

test('keyword text search requests are concurrency limited before hitting the backend API', () => {
  const source = readSource()
  const start = source.indexOf('async def search_products_by_keyword')
  const end = source.indexOf('    async def recognize_image', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)

  const searchSource = source.slice(start, end)
  assert.match(source, /keyword_text_search_concurrency_limit = asyncio\.Semaphore/)
  assert.match(source, /KEYWORD_TEXT_SEARCH_MAX_INFLIGHT/)
  assert.match(searchSource, /async with keyword_text_search_concurrency_limit:/)
})

test('forum post starter uses title and content for keyword and image search', () => {
  const source = readSource()

  assert.match(source, /def _build_forum_post_search_text\(message\):/)
  assert.match(source, /getattr\(getattr\(message, 'channel', None\), 'name'/)
  assert.match(source, /search_query = _build_forum_post_search_text\(message\)/)
  assert.match(source, /image_query_text = _build_forum_post_search_text\(message\)/)
  assert.match(source, /query_text=image_query_text/)
  assert.match(source, /form\.add_field\('query_text', normalized_query_text\[:500\]\)/)
})

test('thread reply mode creates a message thread when no existing thread is available', () => {
  const source = readSource()

  assert.match(source, /disable_thread_creation=False/)
  assert.match(source, /thread_reply_enabled=thread_reply_enabled or saved_reply_target_requested,\n\s+\)/)
  assert.match(source, /if thread_reply_enabled and not used_thread_reply:/)
  assert.match(source, /_create_reply_thread_for_message/)
  assert.match(source, /_resolve_archived_reply_thread/)
  assert.match(source, /archived_threads\(private=private, limit=100\)/)
  assert.match(source, /create_thread = getattr\(target_channel, 'create_thread'/)
  assert.match(source, /await create_thread\(/)
  assert.doesNotMatch(source, /子区回复跳过/)
  assert.doesNotMatch(source, /子区回复回退/)
})

test('messages that already indicate an existing thread do not fall back to the parent channel', () => {
  const source = readSource()

  assert.match(source, /def _message_has_existing_thread_hint\(message\):/)
  assert.match(source, /getattr\(flags, 'has_thread', False\)/)
  assert.match(source, /源消息声明存在子区，但当前发送账号无法进入，拒绝回退到原频道/)
})
