"use client"

import type React from "react"
import { useState, useCallback, useEffect, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { getApiErrorMessage } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Upload, Search, ExternalLink, Settings, X, Trash2, Copy } from "lucide-react"
import { toast } from "sonner"

export function ImageSearchView() {
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [uploadedImage, setUploadedImage] = useState<string | null>(null)
  const [imageUrl, setImageUrl] = useState<string>("")
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [threshold, setThreshold] = useState(30) // 0-100，默认30% (降低阈值以提高匹配成功率)
  const [maxResults, setMaxResults] = useState(5) // 返回最相似的前N个结果

  // 搜索历史相关状态
  const [searchHistory, setSearchHistory] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalHistory, setTotalHistory] = useState(0)
  const [hasMoreHistory, setHasMoreHistory] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [historyFilter, setHistoryFilter] = useState<"all" | "normal" | "skipped">("all")
  const [previewImage, setPreviewImage] = useState<{ src: string; title: string } | null>(null)
  const [availableWebsites, setAvailableWebsites] = useState<any[]>([])
  const historyPageSize = 10
  const historyPageCacheRef = useRef(new Map<string, { history: any[]; total: number; hasMore: boolean }>())
  const historyRequestVersionRef = useRef(0)

  const copyToClipboard = async (text: string) => {
    if (!text) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        toast.success("链接已复制")
        return
      }
    } catch {
      // fallback below
    }

    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      toast.success("链接已复制")
    } catch {
      toast.error("复制失败")
    }
  }

  const resolveBadgeColor = (value?: string) => {
    if (!value) return '#6b7280'
    const trimmed = value.trim()
    if (trimmed.startsWith('#') || trimmed.startsWith('rgb') || trimmed.startsWith('hsl')) {
      return trimmed
    }
    const palette: Record<string, string> = {
      blue: '#2563eb',
      green: '#16a34a',
      orange: '#ea580c',
      red: '#dc2626',
      purple: '#7c3aed',
      gray: '#4b5563'
    }
    return palette[trimmed] || trimmed
  }

  const getWeidianIdFromUrl = (url?: string) => {
    if (!url) return ''
    const match = url.match(/itemID=(\d+)/i)
    return match ? match[1] : ''
  }

  const mergeWebsiteLinks = (links: any[], weidianId: string) => {
    const normalized = Array.isArray(links)
      ? links
          .map((site: any) => ({
            name: site.name || site.display_name || site.url || '',
            display_name: site.display_name || site.name || '网站',
            url: site.url || '',
            badge_color: resolveBadgeColor(site.badge_color || site.badgeColor || '')
          }))
          .filter((link: any) => link.url && link.url.trim() !== '')
      : []

    if (!availableWebsites.length || !weidianId) {
      return normalized
    }

    const existingByKey = new Map<string, any>()
    const unnamed: any[] = []

    normalized.forEach((link: any) => {
      const key = String(link.name || '').toLowerCase()
      if (key) {
        if (!existingByKey.has(key)) {
          existingByKey.set(key, link)
        }
      } else {
        unnamed.push(link)
      }
    })

    const merged: any[] = []
    const used = new Set<string>()

    availableWebsites.forEach((site: any) => {
      const name = String(site.name || '').trim()
      if (!name) return
      const key = name.toLowerCase()
      const existing = existingByKey.get(key)
      if (existing) {
        merged.push({
          ...existing,
          display_name: site.display_name || existing.display_name,
          badge_color: resolveBadgeColor(site.badge_color || existing.badge_color || '')
        })
        used.add(key)
        return
      }

      const template = site.url_template || site.urlTemplate || ''
      const url = template ? template.replace('{id}', weidianId) : ''
      if (!url) return
      merged.push({
        name,
        display_name: site.display_name || name,
        url,
        badge_color: resolveBadgeColor(site.badge_color || site.badgeColor || '')
      })
      used.add(key)
    })

    existingByKey.forEach((link, key) => {
      if (!used.has(key)) {
        merged.push(link)
      }
    })

    unnamed.forEach((link) => merged.push(link))

    return merged.length ? merged : normalized
  }

  const getLinkGridClass = (count: number, extra?: string) => {
    const base = `grid gap-2${extra ? ` ${extra}` : ''}`
    if (count <= 1) return `${base} grid-cols-1`
    if (count === 2) return `${base} grid-cols-2`
    if (count === 3) return `${base} grid-cols-3`
    return `${base} grid-cols-4`
  }

  const currentQueryPreviewSrc = uploadedImage || imageUrl.trim()
  const buildHistoryCacheKey = (page: number) => `${historyFilter}:${page}`

  const clearHistoryPageCache = () => {
    historyPageCacheRef.current.clear()
  }

  const prefetchSearchHistory = async (page: number) => {
    if (page < 1) return

    const cacheKey = buildHistoryCacheKey(page)
    if (historyPageCacheRef.current.has(cacheKey)) {
      return
    }

    try {
      const limit = historyPageSize
      const offset = (page - 1) * limit
      const response = await fetch(`/api/search_history?limit=${limit}&offset=${offset}&skipped=${historyFilter}`)
      if (!response.ok) {
        return
      }

      const result = await response.json()
      historyPageCacheRef.current.set(cacheKey, {
        history: result.history || [],
        total: result.total || 0,
        hasMore: result.has_more || false,
      })
    } catch {
      // 预取失败不影响当前页
    }
  }

  const getHistoryPageItems = () => {
    const totalPages = Math.max(1, Math.ceil(totalHistory / historyPageSize))
    if (totalPages <= 11) {
      return Array.from({ length: totalPages }, (_, index) => index + 1)
    }

    const firstWindowEnd = 3
    const lastWindowStart = totalPages - 2
    const pages = new Set<number>()

    for (let page = 1; page <= firstWindowEnd; page += 1) {
      pages.add(page)
    }
    for (let page = currentPage - 2; page <= currentPage + 2; page += 1) {
      pages.add(page)
    }
    for (let page = lastWindowStart; page <= totalPages; page += 1) {
      pages.add(page)
    }

    const sorted = Array.from(pages)
      .filter(page => page >= 1 && page <= totalPages)
      .sort((a, b) => a - b)

    const items: Array<number | string> = []
    sorted.forEach((page, index) => {
      const previous = sorted[index - 1]
      if (previous && page - previous > 1) {
        items.push(`ellipsis-${previous}-${page}`)
      }
      items.push(page)
    })
    return items
  }

  // 加载搜索历史
  useEffect(() => {
    clearHistoryPageCache()
    void fetchSearchHistory(1, { forceRefresh: true })
  }, [historyFilter])

  useEffect(() => {
    const fetchWebsites = async () => {
      try {
        const response = await fetch('/api/websites', { credentials: 'include' })
        if (response.ok) {
          const data = await response.json()
          setAvailableWebsites(data.websites || [])
        } else {
          const errorData = await response.json().catch(() => ({}))
          toast.error(getApiErrorMessage(errorData, '加载网站列表失败'))
        }
      } catch (error) {
        console.error('Failed to fetch websites:', error)
        toast.error(getApiErrorMessage(error, '加载网站列表失败'))
      }
    }

    fetchWebsites()
  }, [])

  useEffect(() => {
    if (!uploadedFile) {
      setUploadedImage(null)
      return
    }

    const objectUrl = URL.createObjectURL(uploadedFile)
    setUploadedImage(objectUrl)

    return () => {
      URL.revokeObjectURL(objectUrl)
    }
  }, [uploadedFile])

  const fetchSearchHistory = async (
    page: number = 1,
    options?: { forceRefresh?: boolean },
  ) => {
    try {
      const cacheKey = buildHistoryCacheKey(page)
      if (!options?.forceRefresh) {
        const cached = historyPageCacheRef.current.get(cacheKey)
        if (cached) {
          setSearchHistory(cached.history)
          setTotalHistory(cached.total)
          setHasMoreHistory(cached.hasMore)
          setCurrentPage(page)
          return
        }
      }

      const requestVersion = historyRequestVersionRef.current + 1
      historyRequestVersionRef.current = requestVersion
      const limit = historyPageSize
      const offset = (page - 1) * limit
      const response = await fetch(`/api/search_history?limit=${limit}&offset=${offset}&skipped=${historyFilter}`)
      if (response.ok) {
        const result = await response.json()
        const nextHistory = result.history || []
        const nextTotal = result.total || 0
        const nextHasMore = result.has_more || false
        historyPageCacheRef.current.set(cacheKey, {
          history: nextHistory,
          total: nextTotal,
          hasMore: nextHasMore,
        })
        if (historyRequestVersionRef.current === requestVersion) {
          setSearchHistory(nextHistory)
          setTotalHistory(nextTotal)
          setHasMoreHistory(nextHasMore)
          setCurrentPage(page)
        }
        if (nextHasMore) {
          void prefetchSearchHistory(page + 1)
        }
      } else {
        const errorData = await response.json().catch(() => ({}))
        toast.error(getApiErrorMessage(errorData, '加载搜索历史失败'))
      }
    } catch (error) {
      console.error('Failed to fetch search history:', error)
      toast.error(getApiErrorMessage(error, '加载搜索历史失败'))
    }
  }

  // 删除单条搜索历史
  const handleDeleteHistory = async (historyId: number) => {
    try {
      const response = await fetch(`/api/search_history/${historyId}`, {
        method: 'DELETE',
      })
      if (response.ok) {
        clearHistoryPageCache()
        await fetchSearchHistory(currentPage, { forceRefresh: true })
        toast.success('搜索记录已删除')
      } else {
        const errorData = await response.json().catch(() => ({}))
        toast.error(getApiErrorMessage(errorData, '删除失败'))
      }
    } catch (error) {
      console.error('Failed to delete history:', error)
      toast.error(getApiErrorMessage(error, '删除失败'))
    }
  }

  // 清空所有搜索历史
  const handleClearAllHistory = () => {
    setShowClearConfirm(true)
  }

  const confirmClearAllHistory = async () => {
    setShowClearConfirm(false)
    try {
      const response = await fetch('/api/search_history', {
        method: 'DELETE',
      })
      if (response.ok) {
        clearHistoryPageCache()
        setSearchHistory([])
        setTotalHistory(0)
        setHasMoreHistory(false)
        setCurrentPage(1)
        toast.success('所有搜索记录已清空')
      } else {
        const errorData = await response.json().catch(() => ({}))
        toast.error(getApiErrorMessage(errorData, '清空失败'))
      }
    } catch (error) {
      console.error('Failed to clear history:', error)
      toast.error(getApiErrorMessage(error, '清空失败'))
    }
  }


  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.type.startsWith("image/")) {
      toast.error("请上传图片文件")
      return
    }

    setUploadedFile(file)
    setImageUrl("")
    e.target.value = ""
    toast.success("图片已上传")
  }, [])

  const handleClearImage = () => {
    setUploadedFile(null)
    setUploadedImage(null)
  }

  const handleSearch = async () => {
    if (!uploadedFile && !imageUrl.trim()) {
      toast.error("请上传图片或输入图片链接")
      return
    }

    setIsSearching(true)

    try {
      // 创建FormData
      const formData = new FormData();

      if (uploadedFile) {
        formData.append('image', uploadedFile);
        console.log('使用上传的图片进行搜索');
      } else if (imageUrl.trim()) {
        // 发送图片URL
        formData.append('image_url', imageUrl.trim());
        console.log('使用图片链接进行搜索:', imageUrl.trim());
      }

      formData.append('threshold', (threshold / 100).toString()); // 转换为0-1
      formData.append('limit', maxResults.toString()); // 返回结果数量

      // 发送到后端进行向量搜索
      const searchRes = await fetch('/api/search_similar', {
        method: 'POST',
        body: formData
      });

      if (searchRes.ok) {
        const result = await searchRes.json();
        if (result.success && result.results && result.results.length > 0) {
          // 设置搜索结果
          setSearchResults(result.results)
          // 重新加载搜索历史（新记录已保存到数据库）
          clearHistoryPageCache()
          await fetchSearchHistory(1, { forceRefresh: true })
          toast.success(`找到 ${result.results.length} 个相似商品，最佳相似度 ${(result.results[0].similarity * 100).toFixed(1)}%`);
        } else {
          setSearchResults([])
          toast.info(result.message || "未找到相似商品");
        }
      } else {
        const errorData = await searchRes.json().catch(() => ({}))
        console.error('Search failed:', errorData);
        const message =
          typeof (errorData as { message?: unknown }).message === 'string'
            ? (errorData as { message: string }).message.trim()
            : ''
        toast.error(message || getApiErrorMessage(errorData, "搜索失败"));
      }
    } catch (error) {
      console.error('Search error:', error);
      toast.error("搜索过程中发生错误");
    } finally {
      setIsSearching(false);
    }
  }




  return (
    <div className="space-y-6" data-tutorial="image-search-root">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">以图搜图</h2>
        <p className="text-muted-foreground">上传图片，测试向量搜索功能并获取 CNFans 链接</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-1">
        <Card data-tutorial="image-search-upload">
          <CardHeader>
            <CardTitle>上传图片或输入链接进行搜索</CardTitle>
            <CardDescription>支持 JPG、PNG、WebP 格式，可上传图片文件或输入图片链接进行向量搜索</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-6">
              {/* 左侧：图片输入区域 */}
              <div className="flex-1 space-y-4">
                {/* 图片上传区域 */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">上传图片</label>
                  <div className="space-y-3">
                    {!uploadedImage ? (
                      <label
                        htmlFor="image-upload"
                        className={`flex flex-col items-center justify-center h-48 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                          imageUrl.trim()
                            ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-50'
                            : 'border-muted-foreground/25 hover:border-muted-foreground/50'
                        }`}
                      >
                        <Upload className="size-12 text-muted-foreground mb-2" />
                        <input
                          id="image-upload"
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={handleFileUpload}
                          disabled={!!imageUrl.trim()}
                        />
                      </label>
                    ) : (
                      <div className="relative">
                        <img
                          src={uploadedImage || "/placeholder.svg"}
                          alt="Uploaded"
                          className="w-full h-48 object-contain rounded-lg border"
                        />
                        <Button
                          variant="destructive"
                          size="icon"
                          className="absolute top-2 right-2 w-8 h-8"
                          onClick={handleClearImage}
                        >
                          <X className="w-4 h-4" />
                        </Button>
                      </div>
                    )}
                  </div>
                </div>

                {/* 图片链接输入 */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">图片链接</label>
                  <input
                    type="url"
                    value={imageUrl}
                          onChange={(e) => {
                      setImageUrl(e.target.value)
                      // 当输入链接时，清空已上传的图片
                      if (e.target.value.trim()) {
                        setUploadedFile(null)
                        setUploadedImage(null)
                      }
                    }}
                    placeholder="输入图片链接 (https://...)"
                    className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                      uploadedImage ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-50' : 'border-gray-300'
                    }`}
                  disabled={!!uploadedImage}
                />
                  {imageUrl && !uploadedImage && (
                    <div className="flex items-center gap-2">
                      <img
                        src={imageUrl}
                        alt="Preview"
                        className="w-16 h-16 object-cover rounded border"
                        onError={(e) => {
                          e.currentTarget.style.display = 'none';
                        }}
                      />
                      <span className="text-sm text-muted-foreground">图片预览</span>
                    </div>
                  )}
                  {uploadedImage && (
                    <p className="text-xs text-muted-foreground">已上传图片，无法输入链接</p>
                  )}
                </div>
              </div>

              {/* 右侧：搜索设置 */}
              <div className="w-80 space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium">相似度阈值</label>
                    <span className="text-sm text-muted-foreground">{threshold}%</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={threshold}
                    onChange={(e) => setThreshold(Number.parseInt(e.target.value))}
                    className="w-full"
                  />
                  <p className="text-xs text-muted-foreground">只显示相似度超过此阈值的商品 (0-100%)</p>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium">返回结果数量</label>
                    <span className="text-sm text-muted-foreground">{maxResults}个</span>
                  </div>
                  <select
                    value={maxResults}
                    onChange={(e) => setMaxResults(Number.parseInt(e.target.value))}
                    className="w-full px-3 py-2 border border-input rounded-md bg-background text-sm"
                  >
                    <option value={1}>1个</option>
                    <option value={3}>3个</option>
                    <option value={5}>5个</option>
                    <option value={10}>10个</option>
                    <option value={20}>20个</option>
                  </select>
                  <p className="text-xs text-muted-foreground">返回最相似的前N个结果进行筛选</p>
                </div>

                <Button
                  className="w-full"
                  onClick={handleSearch}
                  disabled={(!uploadedFile && !imageUrl.trim()) || isSearching}
                >
                  <Search className="w-4 h-4 mr-2" />
                  {isSearching ? "搜索中..." : "开始搜索"}
                </Button>

                {isSearching && (
                  <div className="flex items-center justify-center py-4">
                    <div className="text-center space-y-2">
                      <div className="animate-spin size-6 border-4 border-primary border-t-transparent rounded-full mx-auto" />
                      <p className="text-xs text-muted-foreground">正在匹配向量...</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 搜索结果 */}
        {searchResults && searchResults.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Search className="w-5 h-5" />
                    搜索结果
                  </CardTitle>
                  <CardDescription>
                    找到 {searchResults.length} 个相似商品，按相似度排序
                  </CardDescription>
                </div>
                <div className="flex items-center gap-3">
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="space-y-4">
                {searchResults.map((result, index) => {
                  const websiteLinks = Array.isArray(result.product?.websiteUrls)
                    ? result.product.websiteUrls
                    : []
                  const weidianId = getWeidianIdFromUrl(result.product?.weidianUrl)
                  const displayedLinks = mergeWebsiteLinks(websiteLinks, weidianId).slice(0, 12)
                  const matchedImageTitle = `${result.product.title || '命中商品'} - 命中图`

                  return (
                    <div key={index} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                    {/* 匹配图片和基本信息 */}
                    <div className="flex gap-3 items-center flex-1">
                      <div className="flex shrink-0 gap-3">
                        {currentQueryPreviewSrc && (
                          <div className="space-y-1">
                            <p className="text-[11px] font-medium text-muted-foreground">搜索图</p>
                            <button
                              type="button"
                              className="w-16 h-16 bg-muted rounded-lg overflow-hidden border border-transparent hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              onClick={() => setPreviewImage({
                                src: currentQueryPreviewSrc,
                                title: '搜索图',
                              })}
                              title="预览搜索图"
                            >
                              <img
                                src={currentQueryPreviewSrc}
                                alt="搜索图"
                                className="w-full h-full object-cover"
                                onError={(e) => {
                                  e.currentTarget.src = '/placeholder.jpg'
                                }}
                              />
                            </button>
                          </div>
                        )}

                        <div className="space-y-1">
                          <p className="text-[11px] font-medium text-muted-foreground">命中图</p>
                          <button
                            type="button"
                            className="w-16 h-16 bg-muted rounded-lg overflow-hidden border border-transparent hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => setPreviewImage({
                              src: result.matchedImage,
                              title: matchedImageTitle,
                            })}
                            title="预览命中图"
                          >
                            <img
                              src={result.matchedImage}
                              alt={matchedImageTitle}
                              className="w-full h-full object-cover"
                              onError={(e) => {
                                e.currentTarget.src = '/placeholder.jpg'
                              }}
                            />
                          </button>
                        </div>
                      </div>

                      <div className="space-y-0.5 min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="font-bold text-base truncate max-w-[200px] sm:max-w-[400px]">{result.product.title}</h4>
                          <Badge
                            className={
                              result.similarity >= 0.95
                                ? "bg-green-600 hover:bg-green-700"
                                : result.similarity >= 0.85
                                ? "bg-blue-600 hover:bg-blue-700"
                                : "bg-yellow-600 hover:bg-yellow-700"
                            }
                          >
                            {(result.similarity * 100).toFixed(1)}% 相似度
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <p className="text-sm font-bold text-blue-600 truncate max-w-[240px] sm:max-w-[500px]">{result.product.englishTitle || "No English Title"}</p>
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                          <span className="font-mono">ID: {result.product.weidianUrl?.split('itemID=')?.[1] || 'N/A'}</span>
                          <span>|</span>
                          <span>排名: #{result.rank}</span>
                          <span>|</span>
                          <span>搜索时间: {new Date().toLocaleString('zh-CN')}</span>
                        </div>
                      </div>
                    </div>

                    {/* 网站链接网格显示区域 */}
                    <div className="w-full lg:w-1/2 mt-2 lg:mt-0">
                      <div className={getLinkGridClass(displayedLinks.length)}>
                        {displayedLinks.map((site: any, index: number) => (
                          <div
                            key={index}
                            className="flex items-center gap-1 min-w-0 bg-muted/40 p-1 rounded border border-transparent hover:border-border transition-colors"
                          >
                            <Badge
                              className="text-[9px] px-1.5 py-0.5 h-5 border-none justify-center shrink-0 text-white font-normal w-14"
                              style={{ backgroundColor: site.badge_color || '#6b7280' }}
                            >
                              {site.display_name}
                            </Badge>
                            <div className="flex-1 min-w-0 flex items-center justify-between">
                              <a
                                href={site.url}
                                target="_blank"
                                className="text-[10px] truncate hover:underline text-foreground/80 px-1"
                                title={site.url}
                              >
                                {site.url}
                              </a>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 shrink-0 opacity-50 hover:opacity-100"
                                onClick={(event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  copyToClipboard(site.url)
                                }}
                              >
                                <Copy className="h-3 w-3"/>
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 搜索历史 - 列表形式 */}
        <Card>
          <CardHeader className="pb-4">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
              <div>
                <CardTitle className="text-lg">
                  {historyFilter === "skipped" ? "被略过的商品" : "搜索记录"}
                </CardTitle>
                <CardDescription>
                  {historyFilter === "skipped"
                    ? "没有达到阈值的群内图片消息会记录在这里"
                    : "历史搜索结果和群内图片略过记录，按时间倒序排列"}
                </CardDescription>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-sm text-muted-foreground" htmlFor="image-search-history-filter">记录类型</label>
                <select
                  id="image-search-history-filter"
                  value={historyFilter}
                  onChange={(event) => {
                    setCurrentPage(1)
                    setHistoryFilter(event.target.value as "all" | "normal" | "skipped")
                  }}
                  className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                >
                  <option value="all">全部</option>
                  <option value="normal">未略过</option>
                  <option value="skipped">已略过</option>
                </select>
                {searchHistory.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleClearAllHistory}
                    className="shrink-0"
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    {historyFilter === "skipped" ? "清空记录" : "清空历史"}
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {searchHistory.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>暂无搜索记录</p>
                <p className="text-sm">上传图片并搜索后，结果将显示在这里</p>
              </div>
            ) : (
              <div className="space-y-3">
                {searchHistory.map((history) => {
                  const isSkipped = Boolean(Number(history.is_skipped || 0))
                  const queryImageSrc = history.query_image_path ? `/api/search_history/${history.id}/query-image` : ''
                  const matchedImageSrc = history.matched_product_id && history.matched_image_index !== null && history.matched_image_index !== undefined
                    ? `/api/image/${history.matched_product_id}/${history.matched_image_index}`
                    : ''
                  const matchedImageTitle = history.title
                    ? `${history.title} - 命中图`
                    : '命中图'
                  const historyLinks = (history.websiteUrls && history.websiteUrls.length > 0)
                    ? history.websiteUrls
                    : [
                        { display_name: '微店', url: history.weidian_url, badge_color: 'gray' },
                        { display_name: 'CNFans', url: history.cnfans_url, badge_color: 'blue' },
                        { display_name: 'ACBuy', url: history.acbuy_url, badge_color: 'purple' }
                      ].filter(site => site.url)
                  const weidianId = getWeidianIdFromUrl(history.weidian_url)
                  const limitedHistoryLinks = mergeWebsiteLinks(historyLinks, weidianId).slice(0, 12)

                  return (
                    <div key={history.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                      {/* 匹配图片和基本信息 */}
                      <div className="flex gap-3 items-center flex-1">
                        <div className="flex shrink-0 gap-3">
                          {queryImageSrc && (
                            <div className="space-y-1">
                              <p className="text-[11px] font-medium text-muted-foreground">搜索图</p>
                              <button
                                type="button"
                                className="w-16 h-16 bg-muted rounded-lg overflow-hidden border border-transparent hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                onClick={() => setPreviewImage({
                                  src: queryImageSrc,
                                  title: '搜索图',
                                })}
                                title="预览搜索图"
                              >
                                <img
                                  src={queryImageSrc}
                                  alt="搜索图"
                                  className="w-full h-full object-cover"
                                  onError={(e) => {
                                    e.currentTarget.src = '/placeholder.jpg'
                                  }}
                                />
                              </button>
                            </div>
                          )}

                          {matchedImageSrc && (
                            <div className="space-y-1">
                              <p className="text-[11px] font-medium text-muted-foreground">命中图</p>
                              <button
                                type="button"
                                className="w-16 h-16 bg-muted rounded-lg overflow-hidden border border-transparent hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                onClick={() => setPreviewImage({
                                  src: matchedImageSrc,
                                  title: isSkipped ? "最高相似商品图" : matchedImageTitle,
                                })}
                                title="预览命中图"
                              >
                                <img
                                  src={matchedImageSrc}
                                  alt={isSkipped ? "最高相似商品图" : matchedImageTitle}
                                  className="w-full h-full object-cover"
                                  onError={(e) => {
                                    e.currentTarget.src = '/placeholder.jpg'
                                  }}
                                />
                              </button>
                            </div>
                          )}
                        </div>

                        <div className="space-y-0.5 min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <h4 className="font-bold text-base truncate max-w-[200px] sm:max-w-[400px]">{history.title || '未命中商品'}</h4>
                            {isSkipped && (
                              <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
                                已略过
                              </Badge>
                            )}
                            <Badge
                              className={
                                isSkipped
                                  ? "bg-red-600 hover:bg-red-700"
                                  : history.similarity >= 0.95
                                  ? "bg-green-600 hover:bg-green-700"
                                  : history.similarity >= 0.85
                                  ? "bg-blue-600 hover:bg-blue-700"
                                  : "bg-yellow-600 hover:bg-yellow-700"
                              }
                            >
                              {(history.similarity * 100).toFixed(1)}% 相似度
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2 mt-1">
                            <p className="text-sm font-bold text-blue-600 truncate max-w-[240px] sm:max-w-[500px]">{history.english_title || "No English Title"}</p>
                          </div>
                          {isSkipped && (
                            <p className="text-xs text-muted-foreground truncate max-w-[520px]">
                              {history.message_content || '群内图片未达到阈值，未发送回复'}
                            </p>
                          )}
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                            <span className="font-mono">ID: {history.weidian_url?.split('itemID=')?.[1] || 'N/A'}</span>
                            <span>|</span>
                            <span>匹配图片: #{history.matched_image_index}</span>
                            <span>|</span>
                            <span>阈值: {history.threshold * 100}%</span>
                            {isSkipped && (
                              <>
                                <span>|</span>
                                <span>频道: {history.discord_channel_name || history.discord_channel_id || '未知频道'}</span>
                              </>
                            )}
                            <span>|</span>
                            <span>搜索时间: {new Date(history.search_time).toLocaleString('zh-CN')}</span>
                          </div>
                        </div>
                      </div>

                      {/* 链接显示区域 */}
                      <div className="w-full lg:w-1/2 mt-2 lg:mt-0 flex items-start gap-2">
                        <div className={getLinkGridClass(limitedHistoryLinks.length, 'flex-1 min-w-0')}>
                          {limitedHistoryLinks.map((site: any, index: number) => (
                            <div
                              key={`${history.id}-${index}`}
                              className="flex items-center gap-1 min-w-0 bg-muted/40 p-1 rounded border border-transparent hover:border-border transition-colors"
                            >
                              <Badge
                                className="text-[9px] px-1.5 py-0.5 h-5 border-none justify-center shrink-0 text-white font-normal w-14"
                                style={{ backgroundColor: site.badge_color || '#6b7280' }}
                              >
                                {site.display_name}
                              </Badge>
                              <div className="flex-1 min-w-0 flex items-center justify-between">
                                <a
                                  href={site.url}
                                  target="_blank"
                                  className="text-[10px] truncate hover:underline text-foreground/80 px-1"
                                  title={site.url}
                                >
                                  {site.url}
                                </a>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 shrink-0 opacity-50 hover:opacity-100"
                                  onClick={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    copyToClipboard(site.url)
                                  }}
                                >
                                  <Copy className="h-3 w-3"/>
                                </Button>
                              </div>
                            </div>
                          ))}
                        </div>

                        {/* 删除按钮 */}
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8 shrink-0 hover:bg-red-50 hover:text-red-600"
                          onClick={() => handleDeleteHistory(history.id)}
                        >
                          <X className="size-3.5" />
                        </Button>
                      </div>
                    </div>
                  )
                })}

                {/* 分页控件 */}
                {searchHistory.length > 0 && (
                  <div className="flex flex-col sm:flex-row justify-between items-center gap-4 pt-4 border-t mt-4">
                    <div className="text-sm text-muted-foreground font-medium">
                      显示第 {((currentPage - 1) * historyPageSize) + 1} - {Math.min(currentPage * historyPageSize, totalHistory)} 条，共 {totalHistory} 条记录
                    </div>
                    <div className="flex flex-wrap items-center justify-center gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchSearchHistory(currentPage - 1)}
                        disabled={currentPage <= 1}
                        className="h-8 px-3"
                      >
                        上一页
                      </Button>
                      {getHistoryPageItems().map((item) => (
                        typeof item === "number" ? (
                          <Button
                            key={item}
                            variant={item === currentPage ? "default" : "outline"}
                            size="sm"
                            onClick={() => fetchSearchHistory(item)}
                            className="h-8 min-w-8 px-2"
                          >
                            {item}
                          </Button>
                        ) : (
                          <span key={item} className="px-2 text-sm text-muted-foreground">...</span>
                        )
                      ))}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchSearchHistory(currentPage + 1)}
                        disabled={!hasMoreHistory || searchHistory.length === 0}
                        className="h-8 px-3"
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Dialog open={Boolean(previewImage)} onOpenChange={(open) => !open && setPreviewImage(null)}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{previewImage?.title || "图片预览"}</DialogTitle>
              <DialogDescription>点击图片外区域或关闭按钮返回列表</DialogDescription>
            </DialogHeader>
            {previewImage && (
              <div className="max-h-[70vh] overflow-hidden rounded-md bg-muted">
                <img
                  src={previewImage.src}
                  alt={previewImage.title}
                  className="mx-auto max-h-[70vh] w-full object-contain"
                />
              </div>
            )}
          </DialogContent>
        </Dialog>

        {/* 清空历史确认对话框 */}
        <Dialog open={showClearConfirm} onOpenChange={setShowClearConfirm}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认清空历史</DialogTitle>
              <DialogDescription>
                确定要清空所有搜索记录吗？此操作不可撤销。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                取消
              </Button>
              <Button variant="destructive" onClick={confirmClearAllHistory}>
                确认清空
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

      </div>
    </div>
  )
}
