import { useCallback, useRef } from 'react'
import { getApiErrorMessage } from '@/lib/utils'

interface CacheEntry {
  data: any
  timestamp: number
}

export function useApiCache(cacheDuration: number = 30000) {
  const cacheRef = useRef<{[key: string]: CacheEntry}>({})

  const cachedFetch = useCallback(async (url: string, options?: RequestInit): Promise<any> => {
    const cacheKey = `${options?.method || 'GET'}:${url}`
    const now = Date.now()

    // 检查缓存
    const cached = cacheRef.current[cacheKey]
    if (cached && (now - cached.timestamp) < cacheDuration) {
      console.log(`使用缓存数据: ${cacheKey}`)
      return cached.data
    }

    // 发起新请求
    console.log(`发起API请求: ${cacheKey}`)
    const response = await fetch(url, options)
    const text = await response.text()
    let data: any = {}
    if (text.trim()) {
      try {
        data = JSON.parse(text)
      } catch {
        data = { message: text.trim() }
      }
    }

    if (!response.ok) {
      throw new Error(getApiErrorMessage(data, `API request failed: ${response.status}`))
    }

    // 更新缓存
    cacheRef.current[cacheKey] = { data, timestamp: now }

    return data
  }, [cacheDuration])

  const clearCache = useCallback(() => {
    cacheRef.current = {}
  }, [])

  const invalidateCache = useCallback((url: string, method: string = 'GET') => {
    const cacheKey = `${method}:${url}`
    delete cacheRef.current[cacheKey]
  }, [])

  return { cachedFetch, clearCache, invalidateCache }
}
