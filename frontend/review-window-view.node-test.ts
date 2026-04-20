import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = () => {
  const candidates = [
    path.join(process.cwd(), 'frontend/components/review-window-view.tsx'),
    path.join(process.cwd(), 'components/review-window-view.tsx'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find review-window-view.tsx in: ${candidates.join(', ')}`)
}

test('review window toolbar stays bottom aligned without manual top padding', () => {
  const source = readSource()

  assert.match(source, /sm:grid-cols-\[240px_auto\]/)
  assert.match(source, /sm:items-end/)
  assert.doesNotMatch(source, /pt-5 sm:pt-0/)
})

test('review window uses Shanghai timezone and the updated message labels', () => {
  const source = readSource()

  assert.match(source, /timeZone:\s*"Asia\/Shanghai"/)
  assert.match(source, /发送内容/)
  assert.match(source, /发送账号/)
  assert.doesNotMatch(source, /保留原始发送文本/)
})

test('review window removes the badge summary row and keeps original message above sent content', () => {
  const source = readSource()

  assert.doesNotMatch(source, /消息 #\{item\.id\}/)
  assert.doesNotMatch(source, /<Badge/)

  const sourceMessageIndex = source.indexOf('原始消息')
  const sendContentIndex = source.indexOf('发送内容')

  assert.notEqual(sourceMessageIndex, -1)
  assert.notEqual(sendContentIndex, -1)
  assert.ok(sourceMessageIndex < sendContentIndex)
})
