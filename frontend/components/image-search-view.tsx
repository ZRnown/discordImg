"use client"

import type React from "react"
import { useState, useCallback, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Upload, Search, ExternalLink, Settings, X, Clock, Trash2, Copy } from "lucide-react"
import { toast } from "sonner"

export function ImageSearchView() {
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

  // 加载搜索历史
  useEffect(() => {
    fetchSearchHistory()
  }, [])

  const fetchSearchHistory = async (page: number = 1) => {
    try {
      const limit = 10 // 每页显示10条记录
      const offset = (page - 1) * limit
      const response = await fetch(`/api/search_history?limit=${limit}&offset=${offset}`)
      if (response.ok) {
        const result = await response.json()
        setSearchHistory(result.history || [])
        setTotalHistory(result.total || 0)
        setHasMoreHistory(result.has_more || false)
        setCurrentPage(page)
      }
    } catch (error) {
      console.error('Failed to fetch search history:', error)
    }
  }

  // 删除单条搜索历史
  const handleDeleteHistory = async (historyId: number) => {
    try {
      const response = await fetch(`/api/search_history/${historyId}`, {
        method: 'DELETE',
      })
      if (response.ok) {
        setSearchHistory(prev => prev.filter(h => h.id !== historyId))
        setTotalHistory(prev => prev - 1)
        toast.success('搜索记录已删除')
      } else {
        toast.error('删除失败')
      }
    } catch (error) {
      console.error('Failed to delete history:', error)
      toast.error('删除失败')
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
        setSearchHistory([])
        setTotalHistory(0)
        toast.success('所有搜索记录已清空')
      } else {
        toast.error('清空失败')
      }
    } catch (error) {
      console.error('Failed to clear history:', error)
      toast.error('清空失败')
    }
  }

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.type.startsWith("image/")) {
      toast.error("请上传图片文件")
      return
    }

    const reader = new FileReader()
    reader.onload = (event) => {
      setUploadedImage(event.target?.result as string)
      // 清空链接输入
      setImageUrl("")
      toast.success("图片已上传")
    }
    reader.readAsDataURL(file)
  }, [])

  const handleClearImage = () => {
    setUploadedImage(null)
  }

  const handleSearch = async () => {
    if (!uploadedImage && !imageUrl.trim()) {
      toast.error("请上传图片或输入图片链接")
      return
    }

    setIsSearching(true)

    try {
      // 创建FormData
      const formData = new FormData();

      if (uploadedImage) {
        // 将base64图片转换为blob
        try {
          const base64Data = uploadedImage.split(',')[1]; // 去掉data:image/jpeg;base64,前缀
          const byteCharacters = atob(base64Data);
          const byteNumbers = new Array(byteCharacters.length);
          for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
          }
          const byteArray = new Uint8Array(byteNumbers);
          const blob = new Blob([byteArray], { type: 'image/jpeg' });
        formData.append('image', blob, 'search.jpg');
        console.log('使用上传的图片进行搜索');
        } catch (error) {
          console.error('图片转换失败:', error);
          toast.error('图片处理失败，请重试');
          setIsSearching(false);
          return;
        }
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
          await fetchSearchHistory()
          toast.success(`找到 ${result.results.length} 个相似商品，最佳相似度 ${(result.results[0].similarity * 100).toFixed(1)}%`);
        } else {
          setSearchResults([])
          toast.info(result.message || "未找到相似商品");
        }
      } else {
        const errorText = await searchRes.text();
        console.error('Search failed:', errorText);
        toast.error("搜索失败");
      }
    } catch (error) {
      console.error('Search error:', error);
      toast.error("搜索过程中发生错误");
    } finally {
      setIsSearching(false);
    }
  }




  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">以图搜图</h2>
        <p className="text-muted-foreground">上传图片，测试向量搜索功能并获取 CNFans 链接</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-1">
        <Card>
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
                  disabled={(!uploadedImage && !imageUrl.trim()) || isSearching}
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
                  const displayedLinks = websiteLinks
                    .slice(0, 12)
                    .map((site: any) => ({
                      ...site,
                      badge_color: resolveBadgeColor(site.badge_color || site.badgeColor || '')
                    }))

                  return (
                    <div key={index} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                    {/* 匹配图片和基本信息 */}
                    <div className="flex gap-3 items-center flex-1">
                      {/* 匹配的商品图片 */}
                      <div className="flex-shrink-0">
                        <div className="w-16 h-16 bg-muted rounded-lg overflow-hidden">
                          <img
                            src={result.matchedImage}
                            alt={result.product.title}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.src = '/placeholder.jpg'
                            }}
                          />
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
                      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
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
                <CardTitle className="text-lg">搜索记录</CardTitle>
                <CardDescription>历史搜索结果，按时间倒序排列</CardDescription>
              </div>
              {searchHistory.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleClearAllHistory}
                  className="shrink-0"
                >
                  <Trash2 className="w-4 h-4 mr-1" />
                  清空历史
                </Button>
              )}
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
                  const historyLinks = (history.websiteUrls && history.websiteUrls.length > 0)
                    ? history.websiteUrls
                    : [
                        { display_name: '微店', url: history.weidian_url, badge_color: 'gray' },
                        { display_name: 'CNFans', url: history.cnfans_url, badge_color: 'blue' },
                        { display_name: 'ACBuy', url: history.acbuy_url, badge_color: 'purple' }
                      ].filter(site => site.url)
                  const limitedHistoryLinks = historyLinks
                    .slice(0, 12)
                    .map((site: any) => ({
                      ...site,
                      badge_color: resolveBadgeColor(site.badge_color || site.badgeColor || '')
                    }))

                  return (
                    <div key={history.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                      {/* 匹配图片和基本信息 */}
                      <div className="flex gap-3 items-center flex-1">
                        {/* 匹配的商品图片 */}
                        {history.matched_product_id && (
                          <div className="flex-shrink-0">
                            <div className="w-16 h-16 bg-muted rounded-lg overflow-hidden">
                              <img
                                src={`/api/image/${history.matched_product_id}/${history.matched_image_index}`}
                                alt="匹配的商品图片"
                                className="w-full h-full object-cover"
                                onError={(e) => {
                                  e.currentTarget.src = '/placeholder.jpg'
                                }}
                              />
                            </div>
                          </div>
                        )}

                        <div className="space-y-0.5 min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <h4 className="font-bold text-base truncate max-w-[200px] sm:max-w-[400px]">{history.title}</h4>
                            <Badge
                              className={
                                history.similarity >= 0.95
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
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                            <span className="font-mono">ID: {history.weidian_url?.split('itemID=')?.[1] || 'N/A'}</span>
                            <span>|</span>
                            <span>匹配图片: #{history.matched_image_index}</span>
                            <span>|</span>
                            <span>阈值: {history.threshold * 100}%</span>
                            <span>|</span>
                            <span>搜索时间: {new Date(history.search_time).toLocaleString('zh-CN')}</span>
                          </div>
                        </div>
                      </div>

                      {/* 链接显示区域 */}
                      <div className="w-full lg:w-1/2 mt-2 lg:mt-0 flex items-start gap-2">
                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 flex-1 min-w-0">
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
                      显示第 {((currentPage - 1) * 10) + 1} - {Math.min(currentPage * 10, totalHistory)} 条，共 {totalHistory} 条记录
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchSearchHistory(currentPage - 1)}
                        disabled={currentPage <= 1}
                        className="h-8 px-3"
                      >
                        上一页
                      </Button>
                      <div className="text-sm font-medium bg-primary text-primary-foreground px-3 py-1 rounded">
                        {currentPage}
                      </div>
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
