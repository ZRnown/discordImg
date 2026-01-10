"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Search, Copy, ChevronLeft, ChevronRight, Trash2, ImageIcon, Edit, X, Download, Loader2, List, Upload, Store, CheckSquare, Square, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"

export function ScraperView() {
  const [searchTerm, setSearchTerm] = useState("")
  const [batchIds, setBatchIds] = useState('')
  const [isBatchScraping, setIsBatchScraping] = useState(false)
  const [batchProgress, setBatchProgress] = useState(0)
  const [products, setProducts] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [jumpPage, setJumpPage] = useState("")
  const [itemsPerPage, setItemsPerPage] = useState(50)
  const [editingProduct, setEditingProduct] = useState<any>(null)
  const [selectedProducts, setSelectedProducts] = useState<number[]>([])
  const [selectAll, setSelectAll] = useState(false)
  const [indexedIds, setIndexedIds] = useState<string[]>([])
  const [shopFilter, setShopFilter] = useState('__ALL__')
  const [keywordSearch, setKeywordSearch] = useState('')
  // 抓取相关状态
  const [shopId, setShopId] = useState('')
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [shopScrapeProgress, setShopScrapeProgress] = useState(0)

  useEffect(() => {
    fetchProducts()
    fetchIndexedIds()

  }, [])

  const fetchProducts = async () => {
    try {
      const res = await fetch('/api/scrape')
      const data = await res.json()
      setProducts(Array.isArray(data) ? data : [])
    } catch (e) {
      toast.error("加载商品库失败")
    }
  }

  const fetchIndexedIds = async () => {
    try {
      const res = await fetch('/api/scrape?type=indexed')
      const data = await res.json()
      setIndexedIds(data.indexedIds || [])
    } catch (e) {
      console.log("获取索引状态失败:", e)
    }
  }


  const handleDeleteProduct = async (id: number) => {
    try {
      // 通过 Next.js API 代理到后端
      const response = await fetch('/api/scrape', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
      })

      if (response.ok) {
      setProducts(products.filter(p => p.id !== id))
        toast.success("商品及其所有数据已完全删除")
      } else {
        const err = await response.json()
        console.error('删除返回错误:', err)
        toast.error("删除失败")
      }
    } catch (e) {
      console.error('删除异常:', e)
      toast.error("删除失败")
    }
  }

  const handleUpdateProduct = async (updatedProduct: any) => {
    try {
      const res = await fetch('/api/scrape', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedProduct)
      })
      if (res.ok) {
        const data = await res.json()
        setProducts(products.map(p => p.id === data.id ? data : p))
        setEditingProduct(null)
        toast.success("更新成功")
      }
    } catch (e) {
      toast.error("更新失败")
    }
  }

  // 店铺相关处理函数
  const handleScrapeShop = async () => {
    if (!shopId.trim()) {
      toast.error("请输入店铺ID")
      return
    }

    setIsShopScraping(true)
    setShopScrapeProgress(10)

    try {
      const response = await fetch('/api/scrape/shop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopId: shopId.trim() })
      })

      if (response.ok) {
        const result = await response.json()

        // 模拟进度更新
        const progressInterval = setInterval(() => {
          setShopScrapeProgress(prev => {
            if (prev >= 90) {
              clearInterval(progressInterval)
              return prev
            }
            return prev + 10
          })
        }, 1000)

        toast.success(`店铺抓取完成，共获取 ${result.totalProducts || 0} 个商品`)

        // 刷新商品列表
        await fetchProducts()
        setShopId('')
        setShopScrapeProgress(100)

        setTimeout(() => {
          setShopScrapeProgress(0)
        }, 2000)
      } else {
        const error = await response.json()
        toast.error(error.error || "店铺抓取失败")
      }
    } catch (error) {
      console.error('Shop scraping error:', error)
      toast.error("网络错误，请重试")
    } finally {
      setIsShopScraping(false)
    }
  }


  const handleBatchScrape = async () => {
    const ids = batchIds.split('\n').map(id => id.trim()).filter(id => id && id.match(/^\d+$/))

    if (ids.length === 0) {
      toast.error("请输入有效的商品ID")
      return
    }

    if (ids.length > 50) {
      toast.error("单次最多支持50个商品ID")
      return
    }

    setIsBatchScraping(true)
    setBatchProgress(0)

    let successCount = 0
    let skipCount = 0

    try {
      for (let i = 0; i < ids.length; i++) {
        const id = ids[i]

        try {
          const response = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ weidianId: id })
          })

          if (response.ok) {
            successCount++
          } else if (response.status === 409) {
            // 商品已存在
            skipCount++
          } else {
            console.warn(`Failed to scrape ${id}:`, await response.text())
          }
        } catch (error) {
          console.error(`Error scraping ${id}:`, error)
        }

        // 更新进度
        setBatchProgress(((i + 1) / ids.length) * 100)

        // 添加小延迟避免请求过于频繁
        if (i < ids.length - 1) {
          await new Promise(resolve => setTimeout(resolve, 200))
        }
      }

      if (successCount > 0) {
        toast.success(`批量抓取完成：成功 ${successCount} 个，跳过 ${skipCount} 个`)
        await fetchProducts()
        setBatchIds('')
      } else if (skipCount > 0) {
        toast.info(`所有商品已存在，跳过 ${skipCount} 个`)
      } else {
        toast.error("批量抓取失败")
      }

    } catch (error) {
      console.error('Batch scraping error:', error)
      toast.error("批量抓取过程中发生错误")
    } finally {
      setIsBatchScraping(false)
      setBatchProgress(0)
    }
  }

  const handleJumpPage = () => {
    const page = parseInt(jumpPage)
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page)
      setJumpPage("")
    } else {
      toast.error("无效的页码")
    }
  }

  // 获取所有不重复的店铺名称
  const uniqueShops = Array.from(new Set(products.map(p => p.shopName).filter(Boolean))).sort()

  const filteredProducts = products.filter(p => {
    const matchesKeyword = !keywordSearch ||
      p.title?.toLowerCase().includes(keywordSearch.toLowerCase()) ||
      p.englishTitle?.toLowerCase().includes(keywordSearch.toLowerCase()) ||
      p.weidianId?.includes(keywordSearch)

    const matchesShop = !shopFilter || shopFilter === "__ALL__" ||
      p.shopName === shopFilter

    return matchesKeyword && matchesShop
  })

  const totalPages = Math.ceil(filteredProducts.length / itemsPerPage)
  const currentProducts = filteredProducts.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)

  return (
    <div className="space-y-8">
      {/* 页面标题 */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">微店抓取</h2>
        <p className="text-muted-foreground">批量抓取商品或通过店铺获取所有商品</p>
      </div>

      {/* 店铺商品抓取 - 顶部 */}
      <Card className="border-2 border-dashed border-purple-300/50 hover:border-purple-400 transition-colors">
        <CardContent className="p-6">
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-purple-100 rounded-xl">
                <Store className="h-6 w-6 text-purple-600" />
              </div>
              <div>
                <h4 className="text-xl font-bold">店铺商品抓取</h4>
                <p className="text-sm text-muted-foreground">通过店铺ID抓取所有商品</p>
              </div>
            </div>

            <div className="space-y-3">
              <Input
                placeholder="输入店铺ID (例如: 12345678)"
                value={shopId}
                onChange={(e) => setShopId(e.target.value)}
                disabled={isShopScraping}
                className="h-10"
              />
              <Button
                onClick={handleScrapeShop}
                disabled={!shopId.trim() || isShopScraping}
                className="w-full h-11 text-base font-semibold"
                size="lg"
              >
                {isShopScraping ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    抓取中...
                  </>
                ) : (
                  <>
                    <Download className="mr-2 h-5 w-5" />
                    抓取店铺商品
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 批量商品上传 - 中间 */}
      <Card className="border-2 border-dashed border-green-300/50 hover:border-green-400 transition-colors">
        <CardContent className="p-6">
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-green-100 rounded-xl">
                <List className="h-6 w-6 text-green-600" />
              </div>
              <div>
                <h4 className="text-xl font-bold">批量商品上传</h4>
                <p className="text-sm text-muted-foreground">批量上传多个商品</p>
              </div>
            </div>

            <div className="space-y-3">
              <textarea
                placeholder="每行一个商品ID&#10;7516912690&#10;7480992768&#10;7478836242"
                value={batchIds}
                onChange={(e) => setBatchIds(e.target.value)}
                disabled={isBatchScraping}
                className="w-full h-32 p-4 text-sm border-2 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
              />
              <div className="flex gap-3">
                <Button
                  onClick={handleBatchScrape}
                  disabled={!batchIds.trim() || isBatchScraping}
                  className="flex-1 h-11 text-base font-semibold"
                  size="lg"
                >
                  {isBatchScraping ? (
                    <>
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      上传中...
                    </>
                  ) : (
                    <>
                      <Upload className="mr-2 h-5 w-5" />
                      批量上传 ({batchIds.split('\n').filter(id => id.trim()).length})
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setBatchIds('')}
                  disabled={isBatchScraping}
                  size="lg"
                  className="h-11 px-6"
                >
                  <X className="h-5 w-5" />
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 进度条 */}
      {(isBatchScraping || isShopScraping) && (
        <div className="space-y-3">
          <Progress value={
            isBatchScraping ? batchProgress : shopScrapeProgress
          } className="h-3" />
          <div className="flex items-center justify-between text-sm">
            <p className="text-blue-600 animate-pulse font-medium">
              {isBatchScraping ? '正在批量上传商品...' : '正在抓取店铺商品...'}
            </p>
            <p className="text-muted-foreground">
              {isBatchScraping ? `${batchProgress.toFixed(1)}%` : `${shopScrapeProgress.toFixed(1)}%`}
            </p>
          </div>
        </div>
      )}

      {/* 商品库 - 底部 */}
      <div className="space-y-4">
        <Card className="shadow-sm">
        <CardHeader className="py-4 border-b">
          <div className="flex flex-row items-center justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-xl font-bold">商品库</CardTitle>
            <CardDescription className="text-xs font-medium">共 {products.length} 个规则已生效。</CardDescription>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant={selectedProducts.length === filteredProducts.length && filteredProducts.length > 0 ? "default" : "outline"}
              size="sm"
              onClick={() => {
                if (selectedProducts.length === filteredProducts.length) {
                  // 取消全选
                  setSelectedProducts([])
                  setSelectAll(false)
                } else {
                  // 全选所有筛选结果
                  setSelectedProducts(filteredProducts.map(p => p.id))
                  setSelectAll(true)
                }
              }}
              className="h-9 px-4 text-sm font-medium shadow-sm hover:shadow-md transition-all"
              disabled={filteredProducts.length === 0}
            >
              {selectedProducts.length === filteredProducts.length && filteredProducts.length > 0 ? (
                <>
                  <CheckSquare className="h-4 w-4 mr-2" />
                  已全选 ({currentProducts.length})
                </>
              ) : (
                <>
                  <Square className="h-4 w-4 mr-2" />
                  全选 ({currentProducts.length})
                </>
              )}
            </Button>

            {selectedProducts.length > 0 && selectedProducts.length < currentProducts.length && (
              <span className="text-sm text-muted-foreground">
                已选择 {selectedProducts.length} 项 (共 {filteredProducts.length} 项)
              </span>
            )}
          </div>
            {selectedProducts.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">已选择 {selectedProducts.length} 个商品 (共 {filteredProducts.length} 个)</span>
                <Button variant="outline" size="sm" onClick={() => {
                  setSelectedProducts([])
                  setSelectAll(false)
                }}>
                  取消选择
                </Button>
                <Button variant="destructive" size="sm" onClick={() => {
                  selectedProducts.forEach(id => handleDeleteProduct(id))
                  setSelectedProducts([])
                  setSelectAll(false)
                }}>
                  <Trash2 className="size-4 mr-1" />
                  批量删除
                </Button>
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Label className="text-xs whitespace-nowrap font-bold text-muted-foreground">每页展示</Label>
              <Select value={itemsPerPage.toString()} onValueChange={(v) => {
                setItemsPerPage(parseInt(v))
                setCurrentPage(1)
              }}>
                <SelectTrigger className="h-8 w-24 text-xs font-bold bg-muted/30">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="20">20条</SelectItem>
                  <SelectItem value="50">50条</SelectItem>
                  <SelectItem value="100">100条</SelectItem>
                  <SelectItem value="200">200条</SelectItem>
                  <SelectItem value="500">500条</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="搜索 ID 或标题..."
                className="pl-9 h-9 w-[250px] text-xs font-medium"
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value)
                  setCurrentPage(1)
                }}
              />
            </div>
          </div>
        </CardHeader>

        <CardContent>
          {/* 商品库筛选控件 */}
          <div className="px-6 py-4 border-b bg-muted/20">
          <div className="flex flex-col sm:flex-row gap-4 items-end">
            {/* 关键词搜索 */}
            <div className="flex-1 space-y-2">
              <Label className="text-sm font-medium">搜索商品</Label>
              <Input
                placeholder="输入商品标题、英文标题或商品ID..."
                value={keywordSearch}
                onChange={(e) => setKeywordSearch(e.target.value)}
                className="h-9"
              />
            </div>

            {/* 店铺筛选 */}
            <div className="flex-1 space-y-2">
              <Label className="text-sm font-medium">筛选店铺</Label>
              <Select value={shopFilter} onValueChange={setShopFilter}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="选择店铺..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__ALL__">全部店铺</SelectItem>
                  {uniqueShops.map(shop => (
                    <SelectItem key={shop} value={shop}>{shop}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* 重置按钮 */}
            <Button
              variant="outline"
              onClick={() => {
                setKeywordSearch('')
                setShopFilter('__ALL__')
              }}
              className="h-9 px-4"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              重置
            </Button>
          </div>

          {(keywordSearch || (shopFilter && shopFilter !== '__ALL__')) && (
            <div className="mt-3 text-sm text-muted-foreground">
              筛选结果: {filteredProducts.length} 个商品
              {keywordSearch && <span className="ml-2">关键词: "{keywordSearch}"</span>}
              {shopFilter && shopFilter !== '__ALL__' && <span className="ml-2">店铺: "{shopFilter}"</span>}
            </div>
          )}
        </div>
          <div className="divide-y">
            {currentProducts.map((product) => (
              <div key={product.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                <div className="flex gap-3 items-center">
                  <Checkbox
                    checked={selectedProducts.includes(product.id)}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        const newSelected = [...selectedProducts, product.id]
                        setSelectedProducts(newSelected)
                        // 检查是否全选
                        setSelectAll(newSelected.length === filteredProducts.length)
                      } else {
                        const newSelected = selectedProducts.filter(id => id !== product.id)
                        setSelectedProducts(newSelected)
                        setSelectAll(false)
                      }
                    }}
                  />
                </div>
                <div className="flex gap-3 items-center flex-1">
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button variant="ghost" className="size-10 p-0 rounded bg-muted flex items-center justify-center flex-shrink-0 hover:bg-muted/80 border shadow-sm">
                        {product.images && product.images.length > 0 ? (
                          <img
                            src={product.images[0]}
                            alt="thumb"
                            className="object-cover w-12 h-12 rounded-md"
                          />
                        ) : (
                          <div className="flex flex-col items-center">
                        <ImageIcon className="size-4 text-muted-foreground" />
                        <span className="text-[8px] font-bold mt-0.5">{product.images?.length || 0}P</span>
                          </div>
                        )}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-4xl">
                      <DialogHeader>
                        <DialogTitle className="text-xl">商品图集 - {product.weidianId}</DialogTitle>
                        <DialogDescription className="font-bold text-primary">{product.title}</DialogDescription>
                      </DialogHeader>
                      <ScrollArea className="max-h-[70vh] mt-4">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-1">
                          {product.images?.map((img: string, idx: number) => (
                            <div key={idx} className="aspect-square rounded-xl border-2 bg-muted overflow-hidden group relative">
                              <img src={img} alt={`Img ${idx}`} className="object-cover w-full h-full transition-transform group-hover:scale-110" />
                              <button
                                onClick={async () => {
                                  try {
                                    const res = await fetch('/api/scrape', {
                                      method: 'PATCH',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({ productId: product.id, imageIndex: idx })
                                    });

                                    if (res.ok) {
                                      const data = await res.json();
                                      setProducts(products.map(p => p.id === product.id ? data.product : p));
                                      toast.success("图片已删除");
                                    } else {
                                      toast.error("删除失败");
                                    }
                                  } catch (e) {
                                    toast.error("删除失败");
                                  }
                                }}
                                className="absolute top-1 right-1 p-1 bg-red-500 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600 shadow-lg"
                              >
                                <X className="size-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </ScrollArea>
                    </DialogContent>
                  </Dialog>
                  
                  <div className="space-y-0.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h4 className="font-bold text-base leading-none truncate">{product.title}</h4>
                      <Badge className="bg-green-600 text-[10px] h-4 px-2 border-none">中文名</Badge>
                      {indexedIds.includes(product.weidianId) && (
                        <Badge className="bg-blue-600 text-[10px] h-4 px-2 border-none">已索引</Badge>
                      )}
                      {product.ruleEnabled && <Badge className="bg-purple-600 text-[10px] h-4 px-2 border-none">规则启用</Badge>}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-sm font-bold text-blue-600 truncate">{product.englishTitle || "未获取到英文名"}</p>
                      <Badge className="bg-blue-600 text-[10px] h-4 px-2 border-none">英文关键词</Badge>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="secondary" className="text-[11px] h-4 px-2 font-mono">ID: {product.weidianId}</Badge>
                      {product.shopName && (
                        <Badge variant="outline" className="text-[11px] h-4 px-2 font-mono">店铺: {product.shopName}</Badge>
                      )}
                      <span className="text-[11px] text-muted-foreground italic">{product.images?.length || 0}张图片</span>
                      {((product.createdAt) || (product.created_at)) && (
                        <span className="text-[11px] text-muted-foreground italic">创建: {(() => {
                          try {
                            const date = new Date(product.createdAt || product.created_at);
                            return isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN');
                          } catch {
                            return '未知时间';
                          }
                        })()}</span>
                      )}
                    </div>
                  </div>
                </div>
                
                <div className="flex items-center gap-4">
                  <div className="flex flex-col gap-1 min-w-[400px]">
                    <div className="flex items-center gap-1.5">
                      <Badge className="text-[9px] px-1 py-0 h-4 bg-blue-600 border-none shrink-0 text-white">CNFans</Badge>
                      <div className="flex-1 bg-muted/30 p-0.5 px-2 rounded border text-[10px] flex items-center justify-between overflow-hidden">
                        <a href={product.cnfansUrl} target="_blank" rel="noopener noreferrer" className="text-blue-500 font-mono font-bold hover:underline">{product.cnfansUrl}</a>
                        <Button variant="ghost" size="icon" className="h-4 w-4 shrink-0 ml-2" onClick={() => {
                          navigator.clipboard.writeText(product.cnfansUrl);
                          toast.success("链接已复制");
                        }}>
                          <Copy className="h-2.5 w-2.5" />
                        </Button>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Badge className="text-[9px] px-1 py-0 h-4 bg-gray-600 border-none shrink-0 text-white">微店</Badge>
                      <div className="flex-1 bg-muted/30 p-0.5 px-2 rounded border text-[10px] flex items-center justify-between overflow-hidden">
                        <a href={product.weidianUrl} target="_blank" rel="noopener noreferrer" className="text-muted-foreground font-mono hover:underline">{product.weidianUrl}</a>
                        <Button variant="ghost" size="icon" className="h-4 w-4 shrink-0 ml-2" onClick={() => {
                          navigator.clipboard.writeText(product.weidianUrl);
                          toast.success("链接已复制");
                        }}>
                          <Copy className="h-2.5 w-2.5" />
                        </Button>
                      </div>
                    </div>
                    {product.acbuyUrl && (
                      <div className="flex items-center gap-1.5">
                        <Badge className="text-[9px] px-1 py-0 h-4 bg-orange-600 border-none shrink-0 text-white">AcBuy</Badge>
                        <div className="flex-1 bg-muted/30 p-0.5 px-2 rounded border text-[10px] flex items-center justify-between overflow-hidden">
                          <a href={product.acbuyUrl} target="_blank" rel="noopener noreferrer" className="text-orange-600 font-mono font-bold hover:underline">{product.acbuyUrl}</a>
                          <Button variant="ghost" size="icon" className="h-4 w-4 shrink-0 ml-2" onClick={() => {
                            navigator.clipboard.writeText(product.acbuyUrl);
                            toast.success("链接已复制");
                          }}>
                            <Copy className="h-2.5 w-2.5" />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Dialog open={editingProduct?.id === product.id} onOpenChange={(open) => !open && setEditingProduct(null)}>
                      <DialogTrigger asChild>
                        <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setEditingProduct(product)}>
                          <Edit className="size-3.5" />
                        </Button>
                      </DialogTrigger>
                      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                        <DialogHeader>
                          <DialogTitle>编辑商品规则 - {product.weidianId}</DialogTitle>
                          <DialogDescription>配置商品信息和自动回复规则</DialogDescription>
                        </DialogHeader>
                        <div className="space-y-6 py-6">
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label>商品名称 (中文)</Label>
                              <Input value={editingProduct?.title || ""} onChange={(e) => setEditingProduct({...editingProduct, title: e.target.value})} />
                            </div>
                            <div className="space-y-2">
                              <Label>英文关键词</Label>
                              <Input value={editingProduct?.englishTitle || ""} onChange={(e) => setEditingProduct({...editingProduct, englishTitle: e.target.value})} />
                            </div>
                          </div>

                          <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/30">
                            <div className="space-y-1">
                              <Label className="text-sm font-bold">启用自动回复规则</Label>
                              <p className="text-xs text-muted-foreground">当检测到关键词时自动发送CNFans链接</p>
                            </div>
                            <Switch
                              checked={editingProduct?.ruleEnabled || false}
                              onCheckedChange={(checked) => setEditingProduct({...editingProduct, ruleEnabled: checked})}
                            />
                          </div>

                          {editingProduct?.ruleEnabled && (
                            <>
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label>匹配模式</Label>
                              <Select value={editingProduct?.matchType || "fuzzy"} onValueChange={(value) => setEditingProduct({...editingProduct, matchType: value})}>
                                <SelectTrigger>
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="fuzzy">模糊匹配</SelectItem>
                                  <SelectItem value="exact">精确匹配</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-2">
                              <Label>匹配选项</Label>
                              <div className="flex items-center space-x-2">
                                <input
                                  type="checkbox"
                                  id="case-insensitive"
                                  checked={editingProduct?.caseInsensitive || true}
                                  onChange={(e) => setEditingProduct({...editingProduct, caseInsensitive: e.target.checked})}
                                  className="rounded"
                                />
                                <label htmlFor="case-insensitive" className="text-sm">不区分大小写</label>
                              </div>
                            </div>
                          </div>

                          <div className="space-y-2">
                            <Label>消息类型过滤</Label>
                            <div className="space-y-2">
                              <div className="flex items-center space-x-2">
                                <input
                                  type="checkbox"
                                  id="reply-filter"
                                  checked={editingProduct?.filterReplies || true}
                                  onChange={(e) => setEditingProduct({...editingProduct, filterReplies: e.target.checked})}
                                  className="rounded"
                                />
                                <label htmlFor="reply-filter" className="text-sm">不回复回复别人的消息</label>
                              </div>
                              <div className="flex items-center space-x-2">
                                <input
                                  type="checkbox"
                                  id="mention-filter"
                                  checked={editingProduct?.filterMentions || true}
                                  onChange={(e) => setEditingProduct({...editingProduct, filterMentions: e.target.checked})}
                                  className="rounded"
                                />
                                <label htmlFor="mention-filter" className="text-sm">不回复@别人的消息</label>
                              </div>
                            </div>
                          </div>

                            </>
                          )}
                        </div>
                        <DialogFooter>
                          <Button variant="outline" onClick={() => setEditingProduct(null)}>取消</Button>
                          <Button onClick={() => handleUpdateProduct(editingProduct)}>保存修改</Button>
                        </DialogFooter>
                      </DialogContent>
                    </Dialog>
                    <Button variant="outline" size="icon" className="h-8 w-8 hover:bg-red-50 hover:text-red-600 transition-all shadow-sm" onClick={() => handleDeleteProduct(product.id)}>
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
            {currentProducts.length === 0 && (
              <div className="py-12 text-center text-muted-foreground text-sm italic">
                目前没有任何规则。
              </div>
            )}
          </div>
          
          {totalPages > 1 && (
            <div className="flex items-center justify-between p-6 border-t bg-muted/5">
              <div className="text-sm text-muted-foreground font-medium">
                当前显示第 <span className="text-foreground font-bold">{(currentPage - 1) * itemsPerPage + 1}</span> 至 <span className="text-foreground font-bold">{Math.min(currentPage * itemsPerPage, filteredProducts.length)}</span> 条，共 <span className="text-foreground font-bold">{filteredProducts.length}</span> 条数据
              </div>
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <Label className="text-xs font-bold text-muted-foreground">跳转至</Label>
                  <div className="flex items-center">
                    <Input 
                      type="number" 
                      className="h-8 w-16 text-xs font-bold px-2 rounded-r-none border-r-0 focus-visible:ring-0" 
                      value={jumpPage} 
                      onChange={(e) => setJumpPage(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleJumpPage()}
                      min={1}
                      max={totalPages}
                    />
                    <Button size="sm" variant="default" className="h-8 px-3 text-xs rounded-l-none font-bold" onClick={handleJumpPage}>跳转</Button>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="h-9 px-4 text-xs font-bold"
                  >
                    <ChevronLeft className="h-4 w-4 mr-1.5" />
                    上一页
                  </Button>
                  <div className="text-xs font-black bg-primary text-primary-foreground shadow-lg px-4 py-2 rounded-md">
                    {currentPage} / {totalPages}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="h-9 px-4 text-xs font-bold"
                  >
                    下一页
                    <ChevronRight className="h-4 w-4 ml-1.5" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  )
}
