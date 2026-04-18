import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import {
  hasWebsiteBlockUserTriggerFilter,
  hasWebsiteOcrContainsFilter,
} from './lib/website-filters.ts'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('website block helper only enables blocked-user UI when block trigger exists', () => {
  assert.equal(hasWebsiteBlockUserTriggerFilter([]), false)
  assert.equal(
    hasWebsiteBlockUserTriggerFilter([
      { filter_type: 'contains', filter_value: 'http' },
      { filter_type: 'website_block_user_trigger', filter_value: 'https' },
    ]),
    true
  )
})

test('website OCR helper only enables OCR stage when OCR keyword filter exists', () => {
  assert.equal(hasWebsiteOcrContainsFilter([]), false)
  assert.equal(
    hasWebsiteOcrContainsFilter([
      { filter_type: 'user_id', filter_value: '123' },
      { filter_type: 'ocr_contains', filter_value: 'nike,aj4' },
    ]),
    true
  )
})

test('accounts view renders blocked users in compact grid only when block trigger exists', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /hasWebsiteBlockUserTriggerFilter/)
  assert.match(source, /grid gap-2 sm:grid-cols-2 xl:grid-cols-3/)
  assert.match(source, /text-\[11px\]/)
})
