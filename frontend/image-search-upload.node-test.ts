import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(path.join(process.cwd(), relativePath), 'utf8')

test('image search uploads preserve the original file instead of re-encoding base64', () => {
  const source = readSource('frontend/components/image-search-view.tsx')

  assert.doesNotMatch(source, /readAsDataURL/)
  assert.doesNotMatch(source, /atob\(/)
  assert.doesNotMatch(source, /new Blob\(\[byteArray\], \{ type: 'image\/jpeg' \}\)/)
  assert.match(source, /URL\.createObjectURL/)
  assert.match(source, /formData\.append\('image', uploadedFile\)/)
})
