import test from 'node:test'
import assert from 'node:assert/strict'

import { getReplyModeSwitchError } from './lib/utils.ts'

test('allows switching to keyword mode when exactly one sender is bound', () => {
  assert.equal(getReplyModeSwitchError(1, 'keyword'), null)
})

test('returns a clear error when switching to keyword mode with no sender', () => {
  assert.equal(
    getReplyModeSwitchError(0, 'keyword'),
    '请先绑定 1 个发送账号后再切换到关键词模式',
  )
})

test('returns a clear error when switching to keyword mode with multiple senders', () => {
  assert.equal(
    getReplyModeSwitchError(3, 'keyword'),
    '当前绑定了 3 个发送账号，关键词模式只支持 1 个发送账号',
  )
})

test('rotation mode never blocks switching', () => {
  assert.equal(getReplyModeSwitchError(0, 'rotation'), null)
  assert.equal(getReplyModeSwitchError(3, 'rotation'), null)
})
