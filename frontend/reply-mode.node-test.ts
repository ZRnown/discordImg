import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getKeywordBatchDispatchModeLabel,
  getReplyModeLabel,
  getDisplayedReplyMode,
  getReplyModeSettingsSection,
  getReplyModeSwitchError,
  isReplyModeOptionDisabled,
} from './lib/utils.ts'

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

test('all mode never blocks switching', () => {
  assert.equal(getReplyModeSwitchError(0, 'all'), null)
  assert.equal(getReplyModeSwitchError(5, 'all'), null)
})

test('default mode never blocks switching', () => {
  assert.equal(getReplyModeSwitchError(0, 'default'), null)
  assert.equal(getReplyModeSwitchError(3, 'default'), null)
})

test('reply mode labels cover the new default mode', () => {
  assert.equal(getReplyModeLabel('default'), '默认模式')
  assert.equal(getReplyModeLabel('rotation'), '轮换模式')
  assert.equal(getReplyModeLabel('keyword'), '关键词模式')
  assert.equal(getReplyModeLabel('all'), '一起回复模式')
})

test('default mode hides both rotation and keyword settings', () => {
  assert.equal(getReplyModeSettingsSection('default'), 'none')
  assert.equal(getReplyModeSettingsSection('rotation'), 'rotation')
  assert.equal(getReplyModeSettingsSection('keyword'), 'keyword')
  assert.equal(getReplyModeSettingsSection('all'), 'all')
})

test('keyword option is disabled unless exactly one sender is bound', () => {
  assert.equal(isReplyModeOptionDisabled(0, 'keyword'), true)
  assert.equal(isReplyModeOptionDisabled(2, 'keyword'), true)
  assert.equal(isReplyModeOptionDisabled(1, 'keyword'), false)
  assert.equal(isReplyModeOptionDisabled(2, 'rotation'), false)
  assert.equal(isReplyModeOptionDisabled(5, 'all'), false)
  assert.equal(isReplyModeOptionDisabled(0, 'default'), false)
})

test('displayed reply mode prefers pending value for immediate UI feedback', () => {
  assert.equal(getDisplayedReplyMode('rotation', 'default'), 'default')
  assert.equal(getDisplayedReplyMode('default', 'keyword'), 'keyword')
  assert.equal(getDisplayedReplyMode('keyword', undefined), 'keyword')
  assert.equal(getDisplayedReplyMode(undefined, undefined), 'rotation')
})

test('keyword batch dispatch labels cover both policies', () => {
  assert.equal(getKeywordBatchDispatchModeLabel('immediate'), '满额立即发送')
  assert.equal(getKeywordBatchDispatchModeLabel('window_end'), '满额后窗口结束发送')
})
