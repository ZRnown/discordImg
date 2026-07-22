import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('website config stats use the current user scope for admins too', () => {
  const source = readFileSync(new URL('./app.py', import.meta.url), 'utf8')
  const routeStart = source.indexOf("def get_website_configs():")
  assert.notEqual(routeStart, -1)
  const routeEnd = source.indexOf("@app.route('/api/websites'", routeStart + 1)
  const routeSource = source.slice(routeStart, routeEnd === -1 ? undefined : routeEnd)

  assert.match(routeSource, /user_website_stats_map = db\.get_user_website_reply_stats_map\(current_user\['id'\], website_ids\)/)
  assert.doesNotMatch(routeSource, /current_user\.get\('role'\) != 'admin'[\s\S]{0,120}else \{\}/)
  assert.match(routeSource, /config\['stat_replies_total'\] = user_stats\.get\('stat_replies_total', 0\)/)
})
