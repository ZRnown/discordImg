import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('image replies prefer configured product custom images over best match images', () => {
  const source = readFileSync(new URL('./bot.py', import.meta.url), 'utf8')

  assert.match(source, /def _product_prefers_custom_reply_images\(/)
  assert.match(source, /custom_files = await self\._collect_custom_reply_files\(/)
  assert.match(source, /if _product_prefers_custom_reply_images\(/)

  const collectStart = source.indexOf('    async def _collect_reply_files(')
  const collectEnd = source.indexOf('    def _resolve_image_skip_threshold', collectStart)
  assert.notEqual(collectStart, -1)
  assert.notEqual(collectEnd, -1)

  const collectSource = source.slice(collectStart, collectEnd)
  const customPriorityIndex = collectSource.indexOf('if _product_prefers_custom_reply_images(')
  const bestMatchIndex = collectSource.indexOf('best_match_files = await self._collect_best_match_reply_files(')

  assert.ok(customPriorityIndex >= 0)
  assert.ok(bestMatchIndex >= 0)
  assert.ok(customPriorityIndex < bestMatchIndex)
})
