"use client"

import type React from "react"
import { useState, useCallback, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Upload, Search, ExternalLink, Settings, X, Clock, Trash2 } from "lucide-react"
import { toast } from "sonner"

export function ImageSearchView() {
  const [uploadedImage, setUploadedImage] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [threshold, setThreshold] = useState(30) // 0-100，默认30% (降低阈值以提高匹配成功率)
  const [maxResults, setMaxResults] = useState(5) // 返回最相似的前N个结果

  // 搜索历史相关状态
  const [searchHistory, setSearchHistory] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalHistory, setTotalHistory] = useState(0)
  const [hasMoreHistory, setHasMoreHistory] = useState(false)

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
  const handleClearAllHistory = async () => {
    if (!confirm('确定要清空所有搜索记录吗？此操作不可撤销。')) return

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
      toast.success("图片已上传")
    }
    reader.readAsDataURL(file)
  }, [])

  const handleSearch = async () => {
    if (!uploadedImage) {
      toast.error("请先上传图片")
      return
    }

    setIsSearching(true)

    try {
      // 将base64图片转换为blob
      const response = await fetch(uploadedImage);
      const blob = await response.blob();

      // 创建FormData
      const formData = new FormData();
      formData.append('image', blob, 'search.jpg');
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

  const handleClearImage = () => {
    setUploadedImage(null)
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
            <CardTitle>上传图片并搜索</CardTitle>
            <CardDescription>支持 JPG、PNG、WebP 格式，拖拽或点击上传图片进行向量搜索</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-4">
              {/* 图片上传区域 */}
              <div className="flex-1">
                {!uploadedImage ? (
                  <label
                    htmlFor="image-upload"
                    className="flex flex-col items-center justify-center h-48 border-2 border-dashed border-muted-foreground/25 rounded-lg cursor-pointer hover:border-muted-foreground/50 transition-colors"
                  >
                    <Upload className="size-12 text-muted-foreground mb-2" />
                    <p className="text-sm text-muted-foreground">点击或拖拽上传图片</p>
                    <input id="image-upload" type="file" accept="image/*" className="hidden" onChange={handleFileUpload} />
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

              {/* 搜索设置 */}
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
                  disabled={!uploadedImage || isSearching}
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
                {searchResults.map((result, index) => (
                  <div key={index} className="border rounded-lg p-4 hover:bg-muted/50 transition-colors">
                    <div className="flex items-start gap-4">
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
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary">
                            #{result.rank}
                          </span>
                          <span className="text-sm font-medium text-green-600">
                            相似度 {(result.similarity * 100).toFixed(1)}%
                          </span>
                        </div>
                        <h3 className="font-medium text-sm mb-1 line-clamp-2">
                          {result.product.title}
                        </h3>
                        {result.product.englishTitle && (
                          <p className="text-xs text-muted-foreground mb-2 line-clamp-1">
                            {result.product.englishTitle}
                          </p>
                        )}
                        <div className="flex items-center gap-4 text-xs text-muted-foreground">
                          <a
                            href={result.product.weidianUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:text-primary underline"
                          >
                            查看商品
                          </a>
                          {result.product.cnfansUrl && (
                            <a
                              href={result.product.cnfansUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:text-primary underline"
                            >
                              CNFans链接
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 搜索历史 - 列表形式 */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-lg">搜索记录</CardTitle>
                <CardDescription>历史搜索结果，按时间倒序排列</CardDescription>
              </div>
              {searchHistory.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleClearAllHistory}
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
                {searchHistory.map((history) => (
                  <div key={history.id} className="border rounded-lg p-4 hover:bg-muted/30 transition-colors">
                    <div className="flex items-start justify-between gap-4">
                      {/* 查询图片和商品信息 */}
                      <div className="flex gap-4 flex-1">
                        {/* 查询图片 */}
                        <div className="flex-shrink-0">
                          <div className="w-16 h-16 bg-muted rounded-lg flex items-center justify-center">
                            <Search className="w-6 h-6 text-muted-foreground" />
                          </div>
                        </div>

                        {/* 商品信息 */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex-1 min-w-0">
                              <h4 className="font-medium text-base truncate">{history.title}</h4>
                              {history.english_title && (
                                <p className="text-sm text-blue-600 mt-1">英文关键词: {history.english_title}</p>
                              )}
                            </div>
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

                          {/* 匹配图片显示 */}
                          {history.matched_image_path && (
                            <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg mb-3">
                              <img
                                src={`/api/image/${history.matched_product_id}/${history.matched_image_index}`}
                                alt="匹配的商品图片"
                                className="w-12 h-12 object-cover rounded border"
                              />
                              <div className="text-sm">
                                <p className="font-medium">匹配的商品图片 #{history.matched_image_index}</p>
                                <p className="text-muted-foreground">这是数据库中最相似的图片</p>
                              </div>
                            </div>
                          )}

                          {/* 商品详情 */}
                          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground mb-3">
                            <span>微店 ID: {history.weidian_url?.split('itemID=')?.[1] || 'N/A'}</span>
                            <span>•</span>
                            <span>匹配图片: #{history.matched_image_index}</span>
                            <span>•</span>
                            <span>阈值: {history.threshold * 100}%</span>
                          </div>

                          {/* 操作按钮 */}
                          <div className="flex gap-2">
                            <Button variant="outline" size="sm" asChild>
                              <a href={history.weidian_url} target="_blank" rel="noopener noreferrer">
                                <ExternalLink className="w-3 h-3 mr-1" />
                                微店链接
                              </a>
                            </Button>
                            <Button variant="default" size="sm" asChild>
                              <a href={history.cnfans_url} target="_blank" rel="noopener noreferrer">
                                <ExternalLink className="w-3 h-3 mr-1" />
                                CNFans链接
                              </a>
                            </Button>
                          </div>
                        </div>
                      </div>

                      {/* 时间和删除按钮 */}
                      <div className="flex flex-col items-end gap-2">
                        <div className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Clock className="w-3 h-3" />
                          {new Date(history.search_time).toLocaleString()}
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="w-8 h-8 hover:bg-red-50 hover:text-red-600"
                          onClick={() => handleDeleteHistory(history.id)}
                        >
                          <X className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>

                    {/* 进度条 */}
                    <Progress value={history.similarity * 100} className="h-2 mt-3" />
                  </div>
                ))}

                {/* 分页控件 */}
                {totalHistory > 10 && (
                  <div className="flex items-center justify-between pt-4 border-t">
                    <div className="text-sm text-muted-foreground">
                      显示 {((currentPage - 1) * 10) + 1} - {Math.min(currentPage * 10, totalHistory)} 条，共 {totalHistory} 条记录
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchSearchHistory(currentPage - 1)}
                        disabled={currentPage <= 1}
                      >
                        上一页
                      </Button>
                      <span className="px-3 py-1 text-sm">
                        {currentPage}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchSearchHistory(currentPage + 1)}
                        disabled={!hasMoreHistory || searchHistory.length === 0}
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
      </div>
    </div>
  )
}
