import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import * as replySettings from './lib/product-reply-settings.ts'
import {
  createEmptyWebsiteReplySetting,
  ensurePerWebsiteReplySettings,
  getLegacyWebsiteReplySetting,
  getWebsiteReplySetting,
  hasWebsiteReplyCustomization,
  SHARED_REPLY_TARGET_KEY,
} from './lib/product-reply-settings.ts'

const websites = [
  { id: 1, name: 'cnfans' },
  { id: 2, name: 'acbuy' },
]

test('shared reply target reads the legacy global product reply fields', () => {
  const product = {
    replyScope: '["cnfans"]',
    customReplyText: 'legacy text',
    imageSource: 'custom',
    customImageUrls: ['https://example.com/legacy.jpg'],
  }

  assert.deepEqual(
    getWebsiteReplySetting(product, SHARED_REPLY_TARGET_KEY, websites),
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

test('single website editor starts empty until that site has its own override', () => {
  const product = {
    replyScope: '["cnfans"]',
    customReplyText: 'legacy text',
    imageSource: 'custom',
    customImageUrls: ['https://example.com/legacy.jpg'],
  }

  assert.deepEqual(
    getWebsiteReplySetting(product, 1, websites),
    createEmptyWebsiteReplySetting(),
  )
})

test('site override wins when that website has its own reply setting', () => {
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
    getWebsiteReplySetting(product, 1, websites),
    {
      customReplyText: 'cnfans only',
      imageSource: 'upload',
      selectedImageIndexes: [],
      customImageUrls: [],
      existingUploadedImageUrls: ['/api/custom_reply_image/1/a.jpg'],
      uploadedImages: [],
    },
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

test('customization helper only treats real content or images as an override', () => {
  assert.equal(hasWebsiteReplyCustomization(createEmptyWebsiteReplySetting()), false)
  assert.equal(hasWebsiteReplyCustomization({
    customReplyText: '',
    imageSource: 'product',
    selectedImageIndexes: [1],
  }), true)
  assert.equal(hasWebsiteReplyCustomization(getLegacyWebsiteReplySetting({
    customReplyText: 'shared text',
  })), true)
})

test('reply editor dialog uses a wider width when auto reply rules are disabled', () => {
  assert.equal(typeof replySettings.getReplyEditorDialogClass, 'function')
  assert.equal(
    replySettings.getReplyEditorDialogClass?.(false),
    'max-w-6xl max-h-[85vh] overflow-y-auto',
  )
  assert.equal(
    replySettings.getReplyEditorDialogClass?.(true),
    'max-w-3xl max-h-[85vh] overflow-y-auto',
  )
})

test('reply scope row text is not bound to checkbox htmlFor toggles', () => {
  const source = readFileSync(new URL('./components/scraper-view.tsx', import.meta.url), 'utf8')
  assert.equal(source.includes('htmlFor="scope-all"'), false)
  assert.equal(source.includes('htmlFor={`scope-${site.name}`}'), false)
})
