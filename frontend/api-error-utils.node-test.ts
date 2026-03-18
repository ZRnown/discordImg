import test from 'node:test'
import assert from 'node:assert/strict'

import { getApiErrorMessage } from './lib/utils.ts'

test('prefers backend error field when present', () => {
  assert.equal(
    getApiErrorMessage({ error: '仅绑定1个发送账号时可切换到关键词模式' }, '操作失败'),
    '仅绑定1个发送账号时可切换到关键词模式',
  )
})

test('falls back to message field when error field is missing', () => {
  assert.equal(
    getApiErrorMessage({ message: '保存失败' }, '操作失败'),
    '保存失败',
  )
})

test('falls back to Error message for thrown errors', () => {
  assert.equal(
    getApiErrorMessage(new Error('网络错误'), '操作失败'),
    '网络错误',
  )
})

test('uses fallback when payload has no usable message', () => {
  assert.equal(
    getApiErrorMessage({}, '操作失败'),
    '操作失败',
  )
})
