import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('admin channel add uses the same global scope as admin channel delete', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(appSource, /current_user\.get\('role'\) == 'admin'[\s\S]*add_website_channel_binding_admin/)
  assert.match(databaseSource, /def add_website_channel_binding_admin\(/)
  assert.match(databaseSource, /SELECT DISTINCT user_id[\s\S]*FROM user_website_settings/)
})

test('accounts list stays scoped to the logged in user by default', () => {
  const appSource = readSource('backend/app.py')

  assert.match(appSource, /account_owner_id = current_user\['id'\]/)
  assert.doesNotMatch(appSource, /account_owner_id = None if current_user\.get\('role'\) == 'admin'/)
})

test('Discord worker fast mode and image timeout are environment driven', () => {
  const appSource = readSource('backend/app.py')
  const botSource = readSource('backend/bot.py')
  const configSource = readSource('backend/config.py')
  const ecosystemSource = readSource('ecosystem.config.js')

  assert.match(configSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS = _env_float/)
  assert.match(configSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS = _env_float/)
  assert.match(configSource, /DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE = _env_int/)
  assert.match(configSource, /DISCORD_SEND_TYPING_ENABLED = _env_bool/)
  assert.match(configSource, /KEYWORD_TEXT_SEARCH_API_MAX_INFLIGHT = _env_int/)
  assert.match(configSource, /KEYWORD_TEXT_SEARCH_API_QUEUE_TIMEOUT_SECONDS = _env_float/)
  assert.match(appSource, /raw_text_search_queue_timeout = getattr\([\s\S]*?config, 'KEYWORD_TEXT_SEARCH_API_QUEUE_TIMEOUT_SECONDS', 2\.0[\s\S]*?\)/)
  assert.doesNotMatch(appSource, /KEYWORD_TEXT_SEARCH_API_QUEUE_TIMEOUT_SECONDS = max\([\s\S]*?or 2\.0/)
  assert.match(botSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS/)
  assert.match(botSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS/)
  assert.match(botSource, /DISCORD_SEND_TYPING_ENABLED/)
  assert.match(ecosystemSource, /DISCORD_SEND_INTERVAL_SECONDS: "0\.35"/)
  assert.match(ecosystemSource, /DISCORD_SEND_TYPING_ENABLED: "0"/)
  assert.match(ecosystemSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS: "5"/)
  assert.match(ecosystemSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS: "900"/)
  assert.match(ecosystemSource, /DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE: "8"/)
  assert.match(ecosystemSource, /LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE: "0"/)
  assert.match(ecosystemSource, /KEYWORD_TEXT_SEARCH_API_QUEUE_TIMEOUT_SECONDS: "0"/)
  assert.match(ecosystemSource, /DISCORD_BOT_EMBEDDED_ENABLED: "0"/)
  assert.match(ecosystemSource, /BOT_DISABLE_EMBEDDED: "1"/)
  assert.match(appSource, /def is_embedded_discord_runtime_enabled\(\):/)
  assert.match(appSource, /if is_embedded_discord_runtime_enabled\(\):[\s\S]*?schedule_discord_bot_restore\(\)[\s\S]*?schedule_discord_bot_watchdog\(\)[\s\S]*?else:[\s\S]*?Discord embedded bot runtime disabled/)
  assert.match(appSource, /if TEXT_SEARCH_QUEUE_TIMEOUT_SECONDS > 0:[\s\S]*?TEXT_SEARCH_SEMAPHORE\.acquire\([\s\S]*?timeout=TEXT_SEARCH_QUEUE_TIMEOUT_SECONDS[\s\S]*?else:[\s\S]*?TEXT_SEARCH_SEMAPHORE\.acquire\(\)/)
})

test('Discord worker disables autostart for invalid account tokens', () => {
  const workerSource = readSource('backend/bot_worker.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(databaseSource, /def disable_discord_account_autostart\(/)
  assert.match(workerSource, /LoginFailure/)
  assert.match(workerSource, /disable_discord_account_autostart\(account_id\)/)
})

test('Discord worker persists runtime account profile for API account list', () => {
  const appSource = readSource('backend/app.py')
  const botSource = readSource('backend/bot.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(databaseSource, /discord_user_id TEXT/)
  assert.match(databaseSource, /runtime_guild_count INTEGER DEFAULT 0/)
  assert.match(databaseSource, /def update_discord_account_profile\(/)
  assert.match(databaseSource, /discord_user_id, discord_username, discord_handle/)
  assert.match(botSource, /update_discord_account_profile\(/)
  assert.match(appSource, /runtime_details = _build_runtime_account_details\(\)/)
  assert.match(appSource, /if runtime:[\s\S]*?item\.update\(runtime\)/)
})

test('Discord workers spread gateway sessions across more shards with startup offsets', () => {
  const workerSource = readSource('backend/bot_worker.py')
  const ecosystemSource = readSource('ecosystem.config.js')

  assert.match(ecosystemSource, /process\.env\.BOT_WORKER_COUNT \|\| process\.env\.BOT_SHARD_COUNT \|\| 8/)
  assert.match(ecosystemSource, /BOT_SHARD_START_OFFSET_SECONDS: "2\.5"/)
  assert.match(workerSource, /BOT_SHARD_START_OFFSET_SECONDS = max\(/)
  assert.match(workerSource, /shard_start_offset_seconds = BOT_SHARD_START_OFFSET_SECONDS \* shard_index/)
  assert.match(workerSource, /await asyncio\.sleep\(shard_start_offset_seconds\)/)
})
