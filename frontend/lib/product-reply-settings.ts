export type ProductReplyScopeWebsite = {
  id: string | number
  name: string
}

export type WebsiteReplySetting = {
  customReplyText: string
  imageSource: 'product' | 'upload' | 'custom'
  selectedImageIndexes: number[]
  customImageUrls: string[]
  existingUploadedImageUrls: string[]
  uploadedImages: File[]
}

export const parseReplyScopes = (rawScope: any): string[] => {
  if (!rawScope || rawScope === 'all') return []
  if (Array.isArray(rawScope)) return rawScope.map(scope => String(scope))
  if (typeof rawScope === 'string') {
    const trimmed = rawScope.trim()
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) {
          return parsed.map(scope => String(scope))
        }
      } catch {
        return [trimmed]
      }
    }
    return [trimmed]
  }
  return [String(rawScope)]
}

export const normalizeStringList = (value: any): string[] => {
  if (!value) return []
  if (Array.isArray(value)) {
    return value.map(item => String(item).trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return []
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) {
          return parsed.map(item => String(item).trim()).filter(Boolean)
        }
      } catch {
        return []
      }
    }
    return trimmed.split('\n').map(item => item.trim()).filter(Boolean)
  }
  return []
}

export const normalizeIndexList = (value: any): number[] => {
  return normalizeStringList(value)
    .map(item => Number(item))
    .filter(item => Number.isFinite(item))
}

export const normalizeImageSource = (value: any): WebsiteReplySetting['imageSource'] => {
  const normalized = String(value || 'product').trim().toLowerCase()
  return ['product', 'upload', 'custom'].includes(normalized)
    ? (normalized as WebsiteReplySetting['imageSource'])
    : 'product'
}

export const createEmptyWebsiteReplySetting = (): WebsiteReplySetting => ({
  customReplyText: '',
  imageSource: 'product',
  selectedImageIndexes: [],
  customImageUrls: [],
  existingUploadedImageUrls: [],
  uploadedImages: [],
})

export const cloneWebsiteReplySetting = (setting: WebsiteReplySetting): WebsiteReplySetting => ({
  customReplyText: setting.customReplyText || '',
  imageSource: normalizeImageSource(setting.imageSource),
  selectedImageIndexes: [...(setting.selectedImageIndexes || [])],
  customImageUrls: [...(setting.customImageUrls || [])],
  existingUploadedImageUrls: [...(setting.existingUploadedImageUrls || [])],
  uploadedImages: [...(setting.uploadedImages || [])],
})

export const normalizeWebsiteReplySetting = (value: any): WebsiteReplySetting => ({
  customReplyText: value?.customReplyText || value?.custom_reply_text || '',
  imageSource: normalizeImageSource(value?.imageSource || value?.image_source || 'product'),
  selectedImageIndexes: normalizeIndexList(
    value?.selectedImageIndexes ?? value?.custom_reply_images
  ),
  customImageUrls: normalizeStringList(
    value?.customImageUrls ?? value?.custom_image_urls
  ),
  existingUploadedImageUrls: normalizeStringList(
    value?.existingUploadedImageUrls ?? value?.uploadedImages
  ),
  uploadedImages: Array.isArray(value?.uploadedImages)
    ? value.uploadedImages.filter((item: any) => item instanceof File)
    : [],
})

export const getScopedWebsites = (
  product: any,
  availableWebsites: ProductReplyScopeWebsite[],
) => {
  if (!product) return []
  if (product.replyScope === 'all') return availableWebsites
  const scopes = parseReplyScopes(product.replyScope)
  return availableWebsites.filter(site => scopes.includes(site.name))
}

export const getLegacyWebsiteReplySetting = (product: any) => normalizeWebsiteReplySetting({
  customReplyText: product?.customReplyText || product?.custom_reply_text || '',
  imageSource: product?.imageSource || product?.image_source || (product?.custom_image_urls ? 'custom' : 'upload'),
  selectedImageIndexes: product?.selectedImageIndexes || product?.custom_reply_images || [],
  customImageUrls: product?.customImageUrls || product?.custom_image_urls || [],
  existingUploadedImageUrls: product?.existingUploadedImageUrls || product?.uploadedImages || [],
})

export const normalizePerWebsiteReplySettings = (
  rawSettings: any,
): Record<string, WebsiteReplySetting> => {
  if (!rawSettings) return {}

  let parsed = rawSettings
  if (typeof rawSettings === 'string') {
    try {
      parsed = JSON.parse(rawSettings)
    } catch {
      return {}
    }
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return {}
  }

  return Object.fromEntries(
    Object.entries(parsed).map(([websiteId, setting]) => [
      String(websiteId),
      normalizeWebsiteReplySetting(setting),
    ]),
  )
}

export const createInitialWebsiteReplySetting = (
  product: any,
  options: { useLegacyFallback?: boolean } = {},
): WebsiteReplySetting => {
  const existingSettings = normalizePerWebsiteReplySettings(
    product?.perWebsiteReplySettings || product?.per_website_reply_settings,
  )
  if (Object.keys(existingSettings).length > 0) {
    return createEmptyWebsiteReplySetting()
  }
  if (options.useLegacyFallback) {
    return getLegacyWebsiteReplySetting(product)
  }
  return createEmptyWebsiteReplySetting()
}

export const ensurePerWebsiteReplySettings = (product: any) => {
  return normalizePerWebsiteReplySettings(
    product?.perWebsiteReplySettings || product?.per_website_reply_settings,
  )
}

export const getWebsiteReplySetting = (
  product: any,
  websiteId: string | number,
  availableWebsites: ProductReplyScopeWebsite[],
): WebsiteReplySetting => {
  const settings = normalizePerWebsiteReplySettings(
    product?.perWebsiteReplySettings || product?.per_website_reply_settings,
  )
  const key = String(websiteId)
  if (settings[key]) {
    return settings[key]
  }
  if (Object.keys(settings).length > 0) {
    return createEmptyWebsiteReplySetting()
  }
  const scopedWebsites = getScopedWebsites(product, availableWebsites)
  if (scopedWebsites.length <= 1) {
    return getLegacyWebsiteReplySetting(product)
  }
  return createEmptyWebsiteReplySetting()
}
