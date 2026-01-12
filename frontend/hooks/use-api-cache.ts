import { useState, useCallback } from 'react'

interface CacheEntry {
  data: any
  timestamp: number
}

export function useApiCache(cacheDuration: number = 30000) {
  const [cache, setCache] = useState<{[key: string]: CacheEntry}>({})

  const cachedFetch = useCallback(async (url: string, options?: RequestInit): Promise<any> => {
    const cacheKey = `${options?.method || 'GET'}:${url}`
    const now = Date.now()

    // 检查缓存
    const cached = cache[cacheKey]
    if (cached && (now - cached.timestamp) < cacheDuration) {
      console.log(`使用缓存数据: ${cacheKey}`)
      return cached.data
    }

    // 发起新请求
    console.log(`发起API请求: ${cacheKey}`)
    const response = await fetch(url, options)
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`)
    }
    const data = await response.json()

    // 更新缓存
    setCache(prev => ({
      ...prev,
      [cacheKey]: { data, timestamp: now }
    }))

    return data
  }, [cache, cacheDuration])

  const clearCache = useCallback(() => {
    setCache({})
  }, [])

  const invalidateCache = useCallback((url: string, method: string = 'GET') => {
    const cacheKey = `${method}:${url}`
    setCache(prev => {
      const newCache = { ...prev }
      delete newCache[cacheKey]
      return newCache
    })
  }, [])

  return { cachedFetch, clearCache, invalidateCache }
}
