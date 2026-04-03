import test from 'node:test'
import assert from 'node:assert/strict'

test('product title translation helpers exist and normalize language-aware defaults', async () => {
  const mod = await import('./lib/product-title-translations.ts').catch(() => null)

  assert.notEqual(mod, null)
  assert.equal(typeof mod?.normalizeProductTitleTranslations, 'function')
  assert.equal(typeof mod?.getProductTitleByLanguage, 'function')
  assert.equal(typeof mod?.getNormalizedWebsiteReplyLanguage, 'function')
  assert.equal(typeof mod?.getReplyTemplateForLanguageChange, 'function')

  const normalized = mod?.normalizeProductTitleTranslations(
    { es: 'Zapatillas' },
    { title: '运动鞋', englishTitle: 'Sneakers' },
  )
  assert.deepEqual(normalized, {
    zh: '运动鞋',
    en: 'Sneakers',
    es: 'Zapatillas',
  })

  assert.equal(mod?.getProductTitleByLanguage(normalized, 'es'), 'Zapatillas')
  assert.equal(mod?.getProductTitleByLanguage(normalized, 'de'), 'Sneakers')
  assert.equal(mod?.getNormalizedWebsiteReplyLanguage('unknown'), 'link_only')
  assert.equal(mod?.getReplyTemplateForLanguageChange('{url}', 'es'), '{title}\n{url}')
  assert.equal(mod?.getReplyTemplateForLanguageChange('{title}\n{url}', 'link_only'), '{url}')
})
