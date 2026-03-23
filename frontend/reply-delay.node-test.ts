import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeReplyDelayDraft, normalizeReplyDelayRange } from './lib/reply-delay.ts'

test('mergeReplyDelayDraft preserves existing min when max changes later', () => {
  const afterMin = mergeReplyDelayDraft({ min: '', max: '' }, { min: '1.2' })
  const afterMax = mergeReplyDelayDraft(afterMin, { max: '1.7' })

  assert.deepEqual(afterMin, { min: '1.2', max: '' })
  assert.deepEqual(afterMax, { min: '1.2', max: '1.7' })
})

test('mergeReplyDelayDraft preserves existing max when min changes later', () => {
  const afterMax = mergeReplyDelayDraft({ min: '', max: '' }, { max: '2.3' })
  const afterMin = mergeReplyDelayDraft(afterMax, { min: '1.8' })

  assert.deepEqual(afterMax, { min: '', max: '2.3' })
  assert.deepEqual(afterMin, { min: '1.8', max: '2.3' })
})

test('normalizeReplyDelayRange returns an object with normalized min and max', () => {
  const normalized = normalizeReplyDelayRange(3, 3)

  assert.deepEqual(normalized, { minDelay: 3, maxDelay: 3.1 })
})
