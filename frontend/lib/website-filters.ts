type WebsiteFilter = {
  filter_type?: string | null
}

const hasFilterType = (filters: WebsiteFilter[] | null | undefined, filterType: string) =>
  (filters || []).some(filter => filter?.filter_type === filterType)

export const hasWebsiteBlockUserTriggerFilter = (filters: WebsiteFilter[] | null | undefined) =>
  hasFilterType(filters, 'website_block_user_trigger')

export const hasWebsiteOcrContainsFilter = (filters: WebsiteFilter[] | null | undefined) =>
  hasFilterType(filters, 'ocr_contains')
