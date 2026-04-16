import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('desktop app source exposes a manual refresh action that remounts the current view and listens for refresh shortcuts', () => {
  const source = readFileSync(new URL('./components/app-page-client.tsx', import.meta.url), 'utf8')

  assert.match(source, /handleManualRefresh/)
  assert.match(source, /window\.addEventListener\("keydown", handleRefreshShortcut\)/)
  assert.match(source, /刷新数据/)
  assert.match(source, /viewRefreshTokens/)
})
