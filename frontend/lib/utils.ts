import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'string') {
    const normalized = error.trim()
    return normalized || fallback
  }

  if (error instanceof Error) {
    const normalized = error.message?.trim()
    return normalized || fallback
  }

  if (error && typeof error === 'object') {
    const payload = error as Record<string, unknown>
    const directFields = [payload.error, payload.message, payload.detail]

    for (const field of directFields) {
      if (typeof field === 'string') {
        const normalized = field.trim()
        if (normalized) {
          return normalized
        }
      }
    }

    if (Array.isArray(payload.errors)) {
      for (const item of payload.errors) {
        if (typeof item === 'string' && item.trim()) {
          return item.trim()
        }
        if (item && typeof item === 'object') {
          const message = (item as Record<string, unknown>).message
          if (typeof message === 'string' && message.trim()) {
            return message.trim()
          }
        }
      }
    }
  }

  return fallback
}

export function formatDate(dateString: string | undefined | null): string {
  if (!dateString) return '未知时间'

  try {
    const date = new Date(dateString)
    if (isNaN(date.getTime())) return '无效时间'

    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: 'Asia/Shanghai'
    }).format(date)
  } catch {
    return '时间格式错误'
  }
}

export function getReplyModeSwitchError(
  senderCount: number,
  nextReplyMode: string,
): string | null {
  if (nextReplyMode !== 'keyword') {
    return null
  }

  if (senderCount === 1) {
    return null
  }

  if (senderCount <= 0) {
    return '请先绑定 1 个发送账号后再切换到关键词模式'
  }

  return `当前绑定了 ${senderCount} 个发送账号，关键词模式只支持 1 个发送账号`
}

export function isReplyModeOptionDisabled(
  senderCount: number,
  nextReplyMode: string,
): boolean {
  return getReplyModeSwitchError(senderCount, nextReplyMode) !== null
}

export function getDisplayedReplyMode(
  currentReplyMode: string | undefined | null,
  pendingReplyMode: string | undefined | null,
): string {
  return pendingReplyMode ?? currentReplyMode ?? 'rotation'
}

export function getReplyModeLabel(replyMode: string): string {
  switch (replyMode) {
    case 'default':
      return '默认模式'
    case 'keyword':
      return '关键词模式'
    case 'rotation':
    default:
      return '轮换模式'
  }
}

export function getReplyModeSettingsSection(replyMode: string): 'none' | 'rotation' | 'keyword' {
  if (replyMode === 'rotation') {
    return 'rotation'
  }
  if (replyMode === 'keyword') {
    return 'keyword'
  }
  return 'none'
}

export function getKeywordBatchDispatchModeLabel(mode: string): string {
  if (mode === 'window_end') {
    return '满额后窗口结束发送'
  }
  return '满额立即发送'
}
