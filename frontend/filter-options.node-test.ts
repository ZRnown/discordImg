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

test('shop id input no longer shows example text', () => {
  const source = readSource('frontend/components/shops-view.tsx')

  assert.doesNotMatch(source, /输入店铺ID \(例如:/)
})
