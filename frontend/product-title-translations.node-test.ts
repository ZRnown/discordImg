import test from 'node:test'
import assert from 'node:assert/strict'

test('product title translation helpers exist and normalize language-aware defaults', async () => {
  const mod = await import('./lib/product-title-translations.ts').catch(() => null)

  assert.notEqual(mod, null)
  assert.equal(typeof mod?.normalizeProductTitleTranslations, 'function')
  assert.equal(typeof mod?.normalizeEnabledTitleLanguages, 'function')
  assert.equal(typeof mod?.normalizeWebsiteReplyLanguages, 'function')
  assert.equal(typeof mod?.getEnabledProductTitleLanguageOptions, 'function')
  assert.equal(typeof mod?.getUsedProductTitleLanguageOptions, 'function')
  assert.equal(typeof mod?.getReplyTitleValue, 'function')
  assert.equal(typeof mod?.getProductTitleByLanguage, 'function')
  assert.equal(typeof mod?.getNormalizedWebsiteReplyLanguage, 'function')
  assert.equal(typeof mod?.getReplyTemplateForLanguageChange, 'function')

  const normalized = mod?.normalizeProductTitleTranslations(
    { pt: 'Tenis', es: 'Zapatillas' },
    { title: '运动鞋', englishTitle: 'Sneakers' },
  )
  assert.deepEqual(normalized, {
    zh: '运动鞋',
    en: 'Sneakers',
    pt: 'Tenis',
    es: 'Zapatillas',
  })

  assert.deepEqual(mod?.normalizeEnabledTitleLanguages(undefined), ['en'])
  assert.deepEqual(mod?.normalizeEnabledTitleLanguages(['pt', 'fr']), ['en', 'pt', 'fr'])
  assert.deepEqual(mod?.normalizeWebsiteReplyLanguages(undefined), ['en'])
  assert.deepEqual(mod?.normalizeWebsiteReplyLanguages(undefined, 'link_only'), [])
  assert.deepEqual(mod?.normalizeWebsiteReplyLanguages(['pt', 'es']), ['pt', 'es'])
  assert.deepEqual(
    mod?.getEnabledProductTitleLanguageOptions(['en', 'pt', 'fr']).map((option: any) => option.value),
    ['pt', 'fr'],
  )
  assert.deepEqual(
    mod?.getUsedProductTitleLanguageOptions([
      { reply_language: ['en', 'pt'] },
      { reply_language: ['ja'] },
      { reply_language: ['pt'] },
    ]).map((option: any) => option.value),
    ['pt', 'ja'],
  )
  assert.equal(mod?.getReplyTitleValue(normalized, ['pt', 'es']), 'Tenis / Zapatillas')
  assert.equal(mod?.getProductTitleByLanguage(normalized, 'es'), 'Zapatillas')
  assert.equal(mod?.getProductTitleByLanguage(normalized, ['pt', 'es']), 'Tenis / Zapatillas')
  assert.equal(mod?.getNormalizedWebsiteReplyLanguage('unknown'), 'link_only')
  assert.equal(mod?.getReplyTemplateForLanguageChange('{url}', ['pt', 'es']), '{url}')
  assert.equal(mod?.getReplyTemplateForLanguageChange('{title}\n{url}', 'link_only'), '{url}')
  assert.equal(mod?.getReplyTemplateForLanguageChange('{title}\n{url}', []), '{url}')
})
