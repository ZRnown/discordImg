export const PRODUCT_TITLE_LANGUAGE_OPTIONS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英文' },
  { value: 'es', label: '西班牙语' },
  { value: 'fr', label: '法语' },
  { value: 'de', label: '德语' },
  { value: 'ru', label: '俄语' },
  { value: 'ja', label: '日语' },
  { value: 'ko', label: '韩语' },
] as const

export const WEBSITE_REPLY_LANGUAGE_OPTIONS = [
  { value: 'link_only', label: '只发链接' },
  ...PRODUCT_TITLE_LANGUAGE_OPTIONS,
] as const

export const LANGUAGE_AWARE_DEFAULT_TEMPLATE = '{title}\n{url}'

type ProductTitleLanguage = typeof PRODUCT_TITLE_LANGUAGE_OPTIONS[number]['value']
type WebsiteReplyLanguage = typeof WEBSITE_REPLY_LANGUAGE_OPTIONS[number]['value']

const SUPPORTED_TITLE_LANGUAGE_SET = new Set<string>(
  PRODUCT_TITLE_LANGUAGE_OPTIONS.map(option => option.value),
)
const SUPPORTED_REPLY_LANGUAGE_SET = new Set<string>(
  WEBSITE_REPLY_LANGUAGE_OPTIONS.map(option => option.value),
)

const coerceText = (value: unknown) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

export const getNormalizedWebsiteReplyLanguage = (value: unknown): WebsiteReplyLanguage => {
  const normalized = coerceText(value).toLowerCase()
  return SUPPORTED_REPLY_LANGUAGE_SET.has(normalized) ? normalized as WebsiteReplyLanguage : 'link_only'
}

export const normalizeProductTitleTranslations = (
  rawValue: unknown,
  fallback: { title?: unknown; englishTitle?: unknown } = {},
) => {
  let parsed = rawValue
  if (typeof rawValue === 'string') {
    try {
      parsed = JSON.parse(rawValue)
    } catch {
      parsed = {}
    }
  }

  const normalized: Record<string, string> = {}
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    Object.entries(parsed as Record<string, unknown>).forEach(([language, value]) => {
      const key = coerceText(language).toLowerCase()
      if (!SUPPORTED_TITLE_LANGUAGE_SET.has(key)) return
      const text = coerceText(value)
      if (text) {
        normalized[key] = text
      }
    })
  }

  const zhTitle = coerceText(fallback.title)
  const enTitle = coerceText(fallback.englishTitle)
  if (zhTitle && !normalized.zh) normalized.zh = zhTitle
  if (enTitle && !normalized.en) normalized.en = enTitle
  return normalized
}

export const serializeProductTitleTranslations = (
  rawValue: unknown,
  fallback: { title?: unknown; englishTitle?: unknown } = {},
) => JSON.stringify(normalizeProductTitleTranslations(rawValue, fallback))

export const getProductTitleByLanguage = (
  rawValue: unknown,
  replyLanguage: unknown,
) => {
  const normalized = normalizeProductTitleTranslations(rawValue)
  const language = getNormalizedWebsiteReplyLanguage(replyLanguage)
  const preferredLanguage: ProductTitleLanguage = language === 'link_only' ? 'en' : language
  return normalized[preferredLanguage] || normalized.en || normalized.zh || ''
}

export const getReplyTemplateForLanguageChange = (
  template: unknown,
  replyLanguage: unknown,
) => {
  const normalizedTemplate = coerceText(template) || '{url}'
  const normalizedLanguage = getNormalizedWebsiteReplyLanguage(replyLanguage)
  if (normalizedLanguage === 'link_only') {
    return normalizedTemplate === LANGUAGE_AWARE_DEFAULT_TEMPLATE ? '{url}' : normalizedTemplate
  }
  if (normalizedTemplate === '{url}') {
    return LANGUAGE_AWARE_DEFAULT_TEMPLATE
  }
  return normalizedTemplate
}
