import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('website filter editor exposes OCR and website block trigger options', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /SelectItem value="ocr_contains">图片OCR关键词<\/SelectItem>/)
  assert.match(source, /SelectItem value="website_block_user_trigger">网站拉黑触发词<\/SelectItem>/)
})

test('global message filter editor treats OCR and website block trigger as multi-value keywords', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /GLOBAL_KEYWORD_FILTER_TYPES/)
  assert.match(source, /'ocr_contains'/)
  assert.match(source, /'website_block_user_trigger'/)
})

test('global website block trigger card renders compact matching-user grid', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /对应用户/)
  assert.match(source, /\/api\/message-filters\/\$\{filterId\}\/blocked-users/)
  assert.match(source, /grid gap-2 sm:grid-cols-2 xl:grid-cols-3/)
  assert.match(source, /text-\[11px\]/)
})

test('global message filters render with pagination controls', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /const MESSAGE_FILTERS_PER_PAGE = 5/)
  assert.match(source, /messageFilterPage/)
  assert.match(source, /paginatedMessageFilters/)
  assert.match(source, /上一页/)
  assert.match(source, /下一页/)
})

test('global blocked users are collapsed by default and can be toggled open', () => {
  const source = readSource('frontend/components/accounts-view.tsx')

  assert.match(source, /expandedMessageFilterIds/)
  assert.match(source, /展开/)
  assert.match(source, /收起/)
  assert.match(source, /ChevronRight/)
  assert.match(source, /ChevronDown/)
})

test('shop id input no longer shows example text', () => {
  const source = readSource('frontend/components/shops-view.tsx')

  assert.doesNotMatch(source, /输入店铺ID \(例如:/)
})
