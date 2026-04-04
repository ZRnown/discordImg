export const PRODUCT_TITLE_LANGUAGE_OPTIONS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英文' },
  { value: 'pt', label: '葡萄牙语' },
  { value: 'es', label: '西班牙语' },
  { value: 'fr', label: '法语' },
  { value: 'de', label: '德语' },
  { value: 'ru', label: '俄语' },
  { value: 'ja', label: '日语' },
  { value: 'ko', label: '韩语' },
] as const

export const WEBSITE_REPLY_LANGUAGE_OPTIONS = PRODUCT_TITLE_LANGUAGE_OPTIONS
export const LANGUAGE_AWARE_DEFAULT_TEMPLATE = '{title}\n{url}'
export const TITLE_JOIN_SEPARATOR = ' / '
export const DEFAULT_ENABLED_TITLE_LANGUAGES = ['en'] as const
export const DEFAULT_REPLY_LANGUAGES = ['en'] as const

type ProductTitleLanguage = typeof PRODUCT_TITLE_LANGUAGE_OPTIONS[number]['value']
type WebsiteReplyLanguage = ProductTitleLanguage

const SUPPORTED_TITLE_LANGUAGE_SET = new Set<string>(
  PRODUCT_TITLE_LANGUAGE_OPTIONS.map(option => option.value),
)

const TRANSLATABLE_LANGUAGE_SET = new Set<string>(
  PRODUCT_TITLE_LANGUAGE_OPTIONS
    .map(option => option.value)
    .filter(value => value !== 'zh'),
)

const coerceText = (value: unknown) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const parseLanguageValues = (value: unknown): string[] | null => {
  if (value === null || value === undefined) {
    return null
  }

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return []
    if (trimmed === 'link_only' || trimmed === 'none' || trimmed === 'null') {
      return []
    }
    try {
      const parsed = JSON.parse(trimmed)
      if (Array.isArray(parsed)) {
        return parsed.map(item => coerceText(item))
      }
      if (typeof parsed === 'string') {
        return [parsed]
      }
    } catch {
      return trimmed
        .replaceAll('，', ',')
        .split(',')
        .map(item => item.trim())
        .filter(Boolean)
    }
    return []
  }

  if (Array.isArray(value)) {
    return value.map(item => coerceText(item))
  }

  return [coerceText(value)]
}

export const getNormalizedWebsiteReplyLanguage = (value: unknown) => {
  const normalized = coerceText(value).toLowerCase()
  return SUPPORTED_TITLE_LANGUAGE_SET.has(normalized)
    ? normalized as WebsiteReplyLanguage
    : 'link_only'
}

export const normalizeEnabledTitleLanguages = (value: unknown) => {
  const parsed = parseLanguageValues(value)
  const normalized: string[] = ['en']
  const seen = new Set(normalized)

  if (parsed === null) return normalized

  parsed.forEach(item => {
    const language = coerceText(item).toLowerCase()
    if (language === 'en') return
    if (!TRANSLATABLE_LANGUAGE_SET.has(language) || seen.has(language)) return
    normalized.push(language)
    seen.add(language)
  })

  return normalized
}

export const getEnabledProductTitleLanguageOptions = (value: unknown) => {
  const enabled = new Set(normalizeEnabledTitleLanguages(value))
  return PRODUCT_TITLE_LANGUAGE_OPTIONS.filter(
    option => option.value !== 'zh' && option.value !== 'en' && enabled.has(option.value),
  )
}

export const normalizeWebsiteReplyLanguages = (
  value: unknown,
  legacyReplyLanguage?: unknown,
) => {
  const parsed = parseLanguageValues(value)
  if (parsed === null) {
    const legacy = getNormalizedWebsiteReplyLanguage(legacyReplyLanguage)
    if (legacyReplyLanguage !== undefined && legacyReplyLanguage !== null) {
      return legacy === 'link_only' ? [] : [legacy]
    }
    return [...DEFAULT_REPLY_LANGUAGES]
  }

  const normalized: string[] = []
  const seen = new Set<string>()
  parsed.forEach(item => {
    const language = getNormalizedWebsiteReplyLanguage(item)
    if (language === 'link_only' || seen.has(language)) return
    normalized.push(language)
    seen.add(language)
  })
  return normalized
}

export const getEffectiveWebsiteReplyLanguages = (
  value: unknown,
  legacyReplyLanguage?: unknown,
) => {
  const normalized = normalizeWebsiteReplyLanguages(value, legacyReplyLanguage)
  return normalized.length > 0 ? normalized : [...DEFAULT_REPLY_LANGUAGES]
}

export const getWebsiteReplyLanguageEditorOptions = () => WEBSITE_REPLY_LANGUAGE_OPTIONS

export const getUsedProductTitleLanguageOptions = (websites: unknown) => {
  const used = new Set<string>()

  if (Array.isArray(websites)) {
    websites.forEach((website: any) => {
      getEffectiveWebsiteReplyLanguages(
        website?.reply_language ?? website?.replyLanguage,
      ).forEach(language => {
        if (language !== 'zh' && language !== 'en') {
          used.add(language)
        }
      })
    })
  }

  return PRODUCT_TITLE_LANGUAGE_OPTIONS.filter(
    option => option.value !== 'zh' && option.value !== 'en' && used.has(option.value),
  )
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

const getPreferredReplyLanguages = (
  replyLanguages: unknown,
  legacyReplyLanguage?: unknown,
) => getEffectiveWebsiteReplyLanguages(replyLanguages, legacyReplyLanguage)

export const getReplyTitleValue = (
  rawValue: unknown,
  replyLanguages: unknown,
  fallback: { title?: unknown; englishTitle?: unknown } = {},
) => {
  const normalized = normalizeProductTitleTranslations(rawValue, fallback)
  const preferredLanguages = getPreferredReplyLanguages(replyLanguages)
  const titles: string[] = []
  const seen = new Set<string>()

  preferredLanguages.forEach(language => {
    const title = normalized[language] || normalized.en || normalized.zh || ''
    if (!title || seen.has(title)) return
    titles.push(title)
    seen.add(title)
  })

  if (titles.length === 0) {
    return normalized.en || normalized.zh || ''
  }

  return titles.join(TITLE_JOIN_SEPARATOR)
}

export const getProductTitleByLanguage = (
  rawValue: unknown,
  replyLanguage: unknown,
) => {
  const normalized = normalizeProductTitleTranslations(rawValue)
  if (Array.isArray(replyLanguage)) {
    return getReplyTitleValue(normalized, replyLanguage)
  }
  const language = getNormalizedWebsiteReplyLanguage(replyLanguage)
  const preferredLanguage: ProductTitleLanguage = language === 'link_only' ? 'en' : language
  return normalized[preferredLanguage] || normalized.en || normalized.zh || ''
}

export const getReplyTemplateForLanguageChange = (
  template: unknown,
  replyLanguage: unknown,
) => {
  const normalizedTemplate = coerceText(template) || '{url}'
  if (Array.isArray(replyLanguage)) {
    const activeReplyLanguages = normalizeWebsiteReplyLanguages(replyLanguage)
    if (activeReplyLanguages.length === 0 && normalizedTemplate === LANGUAGE_AWARE_DEFAULT_TEMPLATE) {
      return '{url}'
    }
    return normalizedTemplate
  }

  const activeReplyLanguages = normalizeWebsiteReplyLanguages(undefined, replyLanguage)
  if (activeReplyLanguages.length === 0) {
    return normalizedTemplate === LANGUAGE_AWARE_DEFAULT_TEMPLATE ? '{url}' : normalizedTemplate
  }
  if (normalizedTemplate === '{url}') {
    return LANGUAGE_AWARE_DEFAULT_TEMPLATE
  }
  return normalizedTemplate
}
