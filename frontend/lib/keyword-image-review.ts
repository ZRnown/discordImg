export function getKeywordImageSearchModeLabel(mode: string | undefined | null): string {
  if (String(mode || '').trim().toLowerCase() === 'auto') {
    return '自动发送'
  }
  return '人工审核发送'
}

export function getKeywordImageSearchStatusLabel(status: string | undefined | null): string {
  switch (String(status || '').trim().toLowerCase()) {
    case 'ready':
      return '待人工处理'
    case 'sent':
      return '已发送'
    case 'no_match':
      return '无匹配'
    case 'failed':
      return '执行失败'
    case 'pending':
    default:
      return '处理中'
  }
}

export function getInitialKeywordImageSearchCredentialsExpanded(
  apiKey: unknown,
): boolean {
  return Boolean(String(apiKey || '').trim())
}

export function normalizeKeywordImageSearchMaxImages(value: unknown): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return 3
  }
  return Math.max(1, Math.min(Math.trunc(parsed), 10))
}
