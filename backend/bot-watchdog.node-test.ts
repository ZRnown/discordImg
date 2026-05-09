import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = () => {
  const candidates = [
    path.join(process.cwd(), 'backend/bot_watchdog.py'),
    path.join(process.cwd(), 'bot_watchdog.py'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find bot_watchdog.py in: ${candidates.join(', ')}`)
}

test('watchdog does not restart a ready client only because its startup future is done', () => {
  const source = readSource()
  const start = source.indexOf('def collect_watchdog_restart_candidates')
  assert.notEqual(start, -1)
  const collectSource = source.slice(start)

  assert.match(collectSource, /client_ready = _client_ready\(client\)/)
  assert.match(collectSource, /client_ready is not True/)
  assert.match(collectSource, /task_done/)
  assert.doesNotMatch(collectSource, /if _task_done\(runtime_entry\.get\("task"\)\):\n\s+reason = "task_done"/)
})
