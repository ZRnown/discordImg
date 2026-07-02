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

test('Discord worker fast mode and image timeout are environment driven', () => {
  const botSource = readSource('backend/bot.py')
  const configSource = readSource('backend/config.py')
  const ecosystemSource = readSource('ecosystem.config.js')

  assert.match(configSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS = _env_float/)
  assert.match(configSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS = _env_float/)
  assert.match(configSource, /DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE = _env_int/)
  assert.match(botSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS/)
  assert.match(botSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS/)
  assert.match(ecosystemSource, /DISCORD_SEND_INTERVAL_SECONDS: "0\.35"/)
  assert.match(ecosystemSource, /DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS: "5"/)
  assert.match(ecosystemSource, /DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS: "240"/)
  assert.match(ecosystemSource, /DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE: "8"/)
})
