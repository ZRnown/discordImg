import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getInitialKeywordImageSearchCredentialsExpanded,
  getKeywordImageSearchModeLabel,
  getKeywordImageSearchStatusLabel,
  normalizeKeywordImageSearchMaxImages,
} from './lib/keyword-image-review.ts'

test('keyword image search mode labels cover manual and auto', () => {
  assert.equal(getKeywordImageSearchModeLabel('manual'), '人工审核发送')
  assert.equal(getKeywordImageSearchModeLabel('auto'), '自动发送')
  assert.equal(getKeywordImageSearchModeLabel('unknown'), '人工审核发送')
})

test('keyword image search status labels cover review lifecycle', () => {
  assert.equal(getKeywordImageSearchStatusLabel('ready'), '待人工处理')
  assert.equal(getKeywordImageSearchStatusLabel('sent'), '已发送')
  assert.equal(getKeywordImageSearchStatusLabel('no_match'), '无匹配')
  assert.equal(getKeywordImageSearchStatusLabel('failed'), '执行失败')
})

test('keyword image search max image count is clamped to safe range', () => {
  assert.equal(normalizeKeywordImageSearchMaxImages(undefined), 3)
  assert.equal(normalizeKeywordImageSearchMaxImages(0), 1)
  assert.equal(normalizeKeywordImageSearchMaxImages(5), 5)
  assert.equal(normalizeKeywordImageSearchMaxImages(20), 10)
})

test('keyword image search credential editor stays collapsed when both values are empty', () => {
  assert.equal(getInitialKeywordImageSearchCredentialsExpanded(''), false)
  assert.equal(getInitialKeywordImageSearchCredentialsExpanded('   '), false)
})

test('keyword image search credential editor auto-expands when SearchApi key exists', () => {
  assert.equal(getInitialKeywordImageSearchCredentialsExpanded('api-key'), true)
})
