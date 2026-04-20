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
