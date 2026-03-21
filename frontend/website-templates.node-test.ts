import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BUILTIN_WEBSITE_TEMPLATES,
  buildWebsiteInternalName,
  CUSTOM_WEBSITE_TEMPLATE_KEY,
  DEFAULT_WEBSITE_TEMPLATE_KEY,
  createEmptyWebsiteConfig,
  createWebsiteConfigFromTemplateKey,
  getWebsiteTemplateByKey,
} from './lib/website-templates.ts'

test('built-in website templates cover core supported purchasing sites', () => {
  const keys = BUILTIN_WEBSITE_TEMPLATES.map(template => template.key)

  assert.deepEqual(keys, [
    'weidian',
    'kakobuy',
    'cnfans',
    'acbuy',
    'superbuy',
    'litbuy',
    'mulebuy',
    'oopbuy',
    'cssbuy',
    'sugargoo',
    'usfans',
    'allchinabuy',
    'hoobuy',
    'joyagoo',
    'hipobuy',
    'lovegobuy',
    'basetao',
    'rizzitgo',
    'hubbuycn',
    'mycnbox',
    'itaobuy',
    'gtbuy',
    'orientdig',
    'bbdbuy',
    'eastmallbuy',
    'loongbuy',
    'fishgoo',
    'kameymall',
    'ponybuy',
  ])
})

test('default website template is weidian', () => {
  assert.equal(DEFAULT_WEBSITE_TEMPLATE_KEY, 'weidian')
})

test('template lookup returns full built-in config', () => {
  const template = getWebsiteTemplateByKey('kameymall')

  assert.equal(template?.display_name, 'KameyMall')
  assert.match(template?.url_template || '', /kameymall\.com/)
  assert.match(template?.url_template || '', /itemID%3D\{id\}/)
})

test('creating config from built-in template returns save-ready payload', () => {
  assert.deepEqual(createWebsiteConfigFromTemplateKey('superbuy'), {
    name: 'superbuy',
    display_name: 'Superbuy',
    url_template:
      'https://www.superbuy.com/en/page/buy/?nTag=Home-search&from=search-input&url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}',
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
  })
})

test('fishgoo template uses double-encoded weidian product links', () => {
  const template = getWebsiteTemplateByKey('fishgoo')

  assert.equal(template?.display_name, 'Fishgoo')
  assert.match(template?.url_template || '', /fishgoo\.com/)
  assert.match(template?.url_template || '', /itemID%253D\{id\}/)
})

test('custom template path starts with an empty editable config', () => {
  assert.equal(CUSTOM_WEBSITE_TEMPLATE_KEY, 'custom')
  assert.deepEqual(createEmptyWebsiteConfig(), createWebsiteConfigFromTemplateKey('missing'))
})

test('buildWebsiteInternalName derives stable internal keys from display names', () => {
  assert.equal(buildWebsiteInternalName('My CN Box'), 'my-cn-box')
  assert.equal(buildWebsiteInternalName('  链接雷达  '), '链接雷达')
  assert.equal(buildWebsiteInternalName(''), '')
})
