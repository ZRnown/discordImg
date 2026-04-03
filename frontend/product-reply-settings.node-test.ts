import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createInitialWebsiteReplySetting,
  createEmptyWebsiteReplySetting,
  ensurePerWebsiteReplySettings,
  getWebsiteReplySetting,
} from './lib/product-reply-settings.ts'

const websites = [
  { id: 1, name: 'cnfans' },
  { id: 2, name: 'acbuy' },
]

test('single scoped website can still reuse legacy custom reply as the starting value', () => {
  const product = {
    replyScope: '["cnfans"]',
    customReplyText: 'legacy text',
    imageSource: 'custom',
    customImageUrls: ['https://example.com/legacy.jpg'],
  }

  assert.deepEqual(
    getWebsiteReplySetting(product, 1, websites),
    {
      customReplyText: 'legacy text',
      imageSource: 'custom',
      selectedImageIndexes: [],
      customImageUrls: ['https://example.com/legacy.jpg'],
      existingUploadedImageUrls: [],
      uploadedImages: [],
    },
  )
})

test('multiple scoped websites no longer auto-share the same legacy content', () => {
  const product = {
    replyScope: '["cnfans","acbuy"]',
    customReplyText: 'legacy text',
    imageSource: 'custom',
    customImageUrls: ['https://example.com/legacy.jpg'],
  }

  assert.deepEqual(
    getWebsiteReplySetting(product, 2, websites),
    createEmptyWebsiteReplySetting(),
  )
})

test('adding another website after one site is configured starts from empty', () => {
  const product = {
    replyScope: '["cnfans","acbuy"]',
    perWebsiteReplySettings: {
      '1': {
        customReplyText: 'cnfans only',
        imageSource: 'upload',
        existingUploadedImageUrls: ['/api/custom_reply_image/1/a.jpg'],
      },
    },
  }

  assert.deepEqual(
    createInitialWebsiteReplySetting(product, { useLegacyFallback: true }),
    createEmptyWebsiteReplySetting(),
  )
})

test('ensure helper keeps only persisted per-website settings', () => {
  const product = {
    replyScope: 'all',
    customReplyText: 'legacy text',
    perWebsiteReplySettings: {
      '1': {
        customReplyText: 'cnfans only',
        imageSource: 'product',
        selectedImageIndexes: [0, 1],
      },
    },
  }

  assert.deepEqual(ensurePerWebsiteReplySettings(product), {
    '1': {
      customReplyText: 'cnfans only',
      imageSource: 'product',
      selectedImageIndexes: [0, 1],
      customImageUrls: [],
      existingUploadedImageUrls: [],
      uploadedImages: [],
    },
  })
})
