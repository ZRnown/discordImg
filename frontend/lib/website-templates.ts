export type WebsiteConfigDraft = {
  name: string
  display_name: string
  url_template: string
  id_pattern: string
  badge_color: string
  reply_template: string
  reply_language?: string | string[]
}

export type WebsiteTemplate = WebsiteConfigDraft & {
  key: string
  description: string
}

export const CUSTOM_WEBSITE_TEMPLATE_KEY = 'custom'
export const DEFAULT_WEBSITE_TEMPLATE_KEY = 'weidian'
const RAW_WEIDIAN_URL_TEMPLATE = 'https://weidian.com/item.html?itemID={id}'
const ENCODED_WEIDIAN_URL_TEMPLATE = 'https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}'
const DOUBLE_ENCODED_WEIDIAN_URL_TEMPLATE = 'https%253A%252F%252Fweidian.com%252Fitem.html%253FitemID%253D{id}'

export const BUILTIN_WEBSITE_TEMPLATES: WebsiteTemplate[] = [
  {
    key: 'weidian',
    name: 'weidian',
    display_name: '微店',
    url_template: RAW_WEIDIAN_URL_TEMPLATE,
    id_pattern: '{id}',
    badge_color: 'gray',
    reply_template: '{url}',
    description: '微店商品原始链接',
  },
  {
    key: 'kakobuy',
    name: 'kakobuy',
    display_name: 'Kakobuy',
    url_template: `https://www.kakobuy.com/item/details?url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'red',
    reply_template: '{url}',
    description: 'Kakobuy 微店商品链接',
  },
  {
    key: 'cnfans',
    name: 'cnfans',
    display_name: 'CNFans',
    url_template: 'https://cnfans.com/product?id={id}&platform=WEIDIAN',
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'CNFans 微店代购链接',
  },
  {
    key: 'acbuy',
    name: 'acbuy',
    display_name: 'AcBuy',
    url_template: 'https://www.acbuy.com/product/?id={id}&source=WD',
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'AcBuy 微店商品链接',
  },
  {
    key: 'superbuy',
    name: 'superbuy',
    display_name: 'Superbuy',
    url_template: `https://www.superbuy.com/en/page/buy/?nTag=Home-search&from=search-input&url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'Superbuy 微店代购链接',
  },
  {
    key: 'litbuy',
    name: 'litbuy',
    display_name: 'Litbuy',
    url_template: 'https://litbuy.com/product/weidian/{id}',
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'Litbuy 微店商品链接',
  },
  {
    key: 'mulebuy',
    name: 'mulebuy',
    display_name: 'MuleBuy',
    url_template: 'https://mulebuy.com/product?id={id}&platform=WEIDIAN',
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'MuleBuy 微店商品链接',
  },
  {
    key: 'oopbuy',
    name: 'oopbuy',
    display_name: 'OOPBuy',
    url_template: 'https://www.oopbuy.com/product/weidian/{id}',
    id_pattern: '{id}',
    badge_color: 'purple',
    reply_template: '{url}',
    description: 'OOPBuy 微店商品链接',
  },
  {
    key: 'cssbuy',
    name: 'cssbuy',
    display_name: 'CSSBuy',
    url_template: 'https://www.cssbuy.com/item-micro-{id}.html',
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'CSSBuy 微店商品链接',
  },
  {
    key: 'sugargoo',
    name: 'sugargoo',
    display_name: 'Sugargoo',
    url_template: `https://www.sugargoo.com/#/home/productDetail?productLink=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'Sugargoo 微店商品链接',
  },
  {
    key: 'usfans',
    name: 'usfans',
    display_name: 'USFans',
    url_template: 'https://usfans.com/product/3/{id}',
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'USFans 微店商品链接',
  },
  {
    key: 'allchinabuy',
    name: 'allchinabuy',
    display_name: 'AllChinaBuy',
    url_template:
      `https://www.allchinabuy.com/en/page/buy/?nTag=Home-search&from=search-input&_search=url&position=&url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'AllChinaBuy 微店商品链接',
  },
  {
    key: 'hoobuy',
    name: 'hoobuy',
    display_name: 'Hoobuy',
    url_template: 'https://hoobuy.com/product/2/{id}',
    id_pattern: '{id}',
    badge_color: 'red',
    reply_template: '{url}',
    description: 'Hoobuy 微店商品链接',
  },
  {
    key: 'joyagoo',
    name: 'joyagoo',
    display_name: 'JoyaGoo',
    url_template: 'https://joyagoo.com/product?id={id}&platform=WEIDIAN',
    id_pattern: '{id}',
    badge_color: 'purple',
    reply_template: '{url}',
    description: 'JoyaGoo 微店商品链接',
  },
  {
    key: 'hipobuy',
    name: 'hipobuy',
    display_name: 'HipoBuy',
    url_template: 'https://hipobuy.com/product/weidian/{id}',
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'HipoBuy 微店商品链接',
  },
  {
    key: 'lovegobuy',
    name: 'lovegobuy',
    display_name: 'LoveGoBuy',
    url_template: 'https://www.lovegobuy.com/product?id={id}&shop_type=weidian',
    id_pattern: '{id}',
    badge_color: 'red',
    reply_template: '{url}',
    description: 'LoveGoBuy 微店商品链接',
  },
  {
    key: 'basetao',
    name: 'basetao',
    display_name: 'Basetao',
    url_template: 'https://www.basetao.com/best-taobao-agent-service/products/agent/weidian/{id}.html',
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'Basetao 微店商品链接',
  },
  {
    key: 'rizzitgo',
    name: 'rizzitgo',
    display_name: 'RizzitGo',
    url_template: 'https://rizzitgo.com/detail-page?goodsId={id}&source=3',
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'RizzitGo 微店商品链接',
  },
  {
    key: 'hubbuycn',
    name: 'hubbuycn',
    display_name: 'HubbuyCN',
    url_template: 'https://www.hubbuycn.com/index/item/index.html?tp=micro&tid={id}',
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'HubbuyCN 微店商品链接',
  },
  {
    key: 'mycnbox',
    name: 'mycnbox',
    display_name: 'MYCNBOX',
    url_template:
      `https://www.mycnbox.com/goodsdetails/index.html?url=${ENCODED_WEIDIAN_URL_TEMPLATE}&shop_type=weidian`,
    id_pattern: '{id}',
    badge_color: 'purple',
    reply_template: '{url}',
    description: 'MYCNBOX 微店商品链接',
  },
  {
    key: 'itaobuy',
    name: 'itaobuy',
    display_name: 'iTaoBuy',
    url_template: `https://www.itaobuy.com/product-detail?url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'iTaoBuy 微店商品链接',
  },
  {
    key: 'gtbuy',
    name: 'gtbuy',
    display_name: 'GTBuy',
    url_template: 'https://gtbuy.com/product/weidian/{id}',
    id_pattern: '{id}',
    badge_color: 'red',
    reply_template: '{url}',
    description: 'GTBuy 微店商品链接',
  },
  {
    key: 'orientdig',
    name: 'orientdig',
    display_name: 'OrientDig',
    url_template: 'https://orientdig.com/product/?id={id}&shop_type=weidian',
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'OrientDig 微店商品链接',
  },
  {
    key: 'bbdbuy',
    name: 'bbdbuy',
    display_name: 'BBDBuy',
    url_template: 'https://bbdbuy.com/index/item/index.html?tp=micro&tid={id}',
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'BBDBuy 微店商品链接',
  },
  {
    key: 'eastmallbuy',
    name: 'eastmallbuy',
    display_name: 'EastMallBuy',
    url_template:
      `https://eastmallbuy.com/index/item/index.html?searchlang=en&url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'EastMallBuy 微店商品链接',
  },
  {
    key: 'loongbuy',
    name: 'loongbuy',
    display_name: 'LoongBuy',
    url_template: 'https://loongbuy.com/product-details?weidian={id}',
    id_pattern: '{id}',
    badge_color: 'green',
    reply_template: '{url}',
    description: 'LoongBuy 微店商品链接',
  },
  {
    key: 'fishgoo',
    name: 'fishgoo',
    display_name: 'Fishgoo',
    url_template: `https://www.fishgoo.com/#/product?productLink=${DOUBLE_ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'blue',
    reply_template: '{url}',
    description: 'Fishgoo 微店商品链接',
  },
  {
    key: 'kameymall',
    name: 'kameymall',
    display_name: 'KameyMall',
    url_template:
      `https://www.kameymall.com/purchases/search/item?url=${ENCODED_WEIDIAN_URL_TEMPLATE}`,
    id_pattern: '{id}',
    badge_color: 'orange',
    reply_template: '{url}',
    description: 'KameyMall 微店商品链接',
  },
  {
    key: 'ponybuy',
    name: 'ponybuy',
    display_name: 'PonyBuy',
    url_template: 'https://www.ponybuy.com/products/3/{id}',
    id_pattern: '{id}',
    badge_color: 'purple',
    reply_template: '{url}',
    description: 'PonyBuy 微店商品链接',
  },
]

export function createEmptyWebsiteConfig(): WebsiteConfigDraft {
  return {
    name: '',
    display_name: '',
    url_template: '',
    id_pattern: '',
    badge_color: 'blue',
    reply_template: '{url}',
    reply_language: ['en'],
  }
}

export function buildWebsiteInternalName(displayName: string): string {
  const trimmed = displayName.trim()
  if (!trimmed) {
    return ''
  }

  const asciiSlug = trimmed
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

  if (asciiSlug) {
    return asciiSlug
  }

  return trimmed.replace(/\s+/g, '-')
}

export function buildUniqueWebsiteInternalName(baseName: string, existingNames: string[] = []): string {
  const normalizedBaseName = buildWebsiteInternalName(baseName)
  if (!normalizedBaseName) {
    return ''
  }

  const takenNames = new Set(
    existingNames
      .map(name => String(name || '').trim().toLowerCase())
      .filter(Boolean)
  )

  let candidate = normalizedBaseName
  let suffix = 2
  while (takenNames.has(candidate.toLowerCase())) {
    candidate = `${normalizedBaseName}-${suffix}`
    suffix += 1
  }

  return candidate
}

export function getWebsiteTemplateByKey(key: string | null | undefined): WebsiteTemplate | undefined {
  return BUILTIN_WEBSITE_TEMPLATES.find(template => template.key === key)
}

export function createWebsiteConfigFromTemplateKey(
  key: string | null | undefined,
  displayName?: string
): WebsiteConfigDraft {
  const template = getWebsiteTemplateByKey(key)
  if (!template) {
    return createEmptyWebsiteConfig()
  }
  return {
    name: template.name,
    display_name: displayName?.trim() || template.display_name,
    url_template: template.url_template,
    id_pattern: template.id_pattern,
    badge_color: template.badge_color,
    reply_template: template.reply_template,
    reply_language: template.reply_language || ['en'],
  }
}
