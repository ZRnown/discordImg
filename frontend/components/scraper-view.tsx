"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Search, Copy, ChevronLeft, ChevronRight, Trash2, ImageIcon, Edit, X, Settings } from "lucide-react"
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
  const [weidianId, setWeidianId] = useState("")
  const [searchTerm, setSearchTerm] = useState("")
  const [isScraing, setIsScraing] = useState(false)
  const [progress, setProgress] = useState(0)
  const [products, setProducts] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [jumpPage, setJumpPage] = useState("")
  const [itemsPerPage, setItemsPerPage] = useState(50)
  const [editingProduct, setEditingProduct] = useState<any>(null)
  const [selectedProducts, setSelectedProducts] = useState<number[]>([])
  const [selectAll, setSelectAll] = useState(false)
  const [indexedIds, setIndexedIds] = useState<string[]>([])
  const [globalMinDelay, setGlobalMinDelay] = useState(3)
  const [globalMaxDelay, setGlobalMaxDelay] = useState(8)
  const [showSettings, setShowSettings] = useState(false)

  useEffect(() => {
    fetchProducts()
    fetchIndexedIds()
    fetchGlobalDelay()
  }, [])

  const fetchGlobalDelay = async () => {
    try {
      const res = await fetch('/api/global-delay')
      if (res.ok) {
        const data = await res.json()
        setGlobalMinDelay(data.min_delay || 3)
        setGlobalMaxDelay(data.max_delay || 8)
      }
    } catch (e) {
      console.log("获取全局延迟设置失败:", e)
    }
  }

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

  const handleScrape = async () => {
    if (!weidianId.trim()) {
      toast.error("请输入微店商品 ID")
      return
    }

    if (products.some(p => p.weidianId === weidianId.trim())) {
      toast.error("该商品 ID 已存在于库中，禁止重复上传")
      return
    }

    setIsScraing(true)
    setProgress(10)
    
    try {
      const response = await fetch('/api/scrape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: `https://weidian.com/item.html?itemID=${weidianId.trim()}` })
      })
      
      if (!response.ok) {
        const errorData = await response.json()
        if (errorData.error && errorData.error.includes('已存在')) {
          throw new Error("该商品ID已存在，请勿重复添加")
        }
        throw new Error(errorData.error || "抓取失败")
      }
      
      const newProduct = await response.json()
      
      setProgress(100)
      setTimeout(async () => {
        setIsScraing(false)
        // 拉取完整的产品列表（以便获取后端生成的缩略图 URL / created_at 等字段）
        await fetchProducts()
        setWeidianId("")
        fetchIndexedIds() // 刷新索引状态
        toast.success(`抓取成功`)
      }, 500)

    } catch (error: any) {
      setIsScraing(false)
      setProgress(0)
      toast.error(`抓取失败: ${error.message}`)
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


  const handleJumpPage = () => {
    const page = parseInt(jumpPage)
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page)
      setJumpPage("")
    } else {
      toast.error("无效的页码")
    }
  }

  const filteredProducts = products.filter(p => 
    p.title?.toLowerCase().includes(searchTerm.toLowerCase()) || 
    p.weidianId?.includes(searchTerm)
  )

  const totalPages = Math.ceil(filteredProducts.length / itemsPerPage)
  const currentProducts = filteredProducts.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h2 className="text-3xl font-bold tracking-tight">微店抓取与规则中心</h2>
          <p className="text-muted-foreground">抓取商品 ID 建立图库索引，CNFans 英文标题将自动作为 Discord 匹配关键词</p>
        </div>
        <Dialog open={showSettings} onOpenChange={setShowSettings}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm">
              <Settings className="w-4 h-4 mr-2" />
              全局设置
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>全局延迟设置</DialogTitle>
              <DialogDescription>
                设置所有商品自动回复的默认延迟范围，新添加的商品将使用此设置
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="min-delay">最小延迟 (秒)</Label>
                  <Input
                    id="min-delay"
                    type="number"
                    min="0"
                    max="300"
                    value={globalMinDelay}
                    onChange={(e) => setGlobalMinDelay(parseInt(e.target.value) || 0)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="max-delay">最大延迟 (秒)</Label>
                  <Input
                    id="max-delay"
                    type="number"
                    min="0"
                    max="300"
                    value={globalMaxDelay}
                    onChange={(e) => setGlobalMaxDelay(parseInt(e.target.value) || 0)}
                  />
                </div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <p className="text-sm text-muted-foreground">
                  当前设置: {globalMinDelay}-{globalMaxDelay}秒随机延迟
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowSettings(false)}>
                取消
              </Button>
              <Button
                onClick={async () => {
                  try {
                    const res = await fetch('/api/global-delay', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        min_delay: globalMinDelay,
                        max_delay: globalMaxDelay
                      })
                    })
                    if (res.ok) {
                      toast.success("全局延迟设置已保存")
                      setShowSettings(false)
                    } else {
                      toast.error("保存失败")
                    }
                  } catch (e) {
                    toast.error("网络错误")
                  }
                }}
              >
                保存设置
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader className="py-4">
          <CardTitle className="text-lg">开始抓取并建立规则</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="weidian-id">微店商品 ID</Label>
            <div className="flex gap-2">
              <Input
                id="weidian-id"
                placeholder="在此输入商品 ID (例如: 7612504902)"
                value={weidianId}
                onChange={(e) => setWeidianId(e.target.value)}
                disabled={isScraing}
                className="h-10"
              />
              <Button onClick={handleScrape} disabled={isScraing} className="h-10 px-6 font-bold">
                <Search className="mr-2 h-4 w-4" />
                {isScraing ? "正在抓取数据..." : "建立索引与规则"}
              </Button>
            </div>
          </div>
          {isScraing && (
            <div className="space-y-2">
              <Progress value={progress} className="h-2" />
              <p className="text-[10px] text-blue-500 animate-pulse font-medium">正在解析数据，下载高清图片...</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader className="py-4 border-b">
          <div className="flex flex-row items-center justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-xl font-bold">商品库</CardTitle>
            <CardDescription className="text-xs font-medium">共 {products.length} 个规则已生效。</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              checked={selectAll && currentProducts.length > 0}
              onCheckedChange={(checked) => {
                setSelectAll(checked as boolean)
                if (checked) {
                  setSelectedProducts(currentProducts.map(p => p.id))
                } else {
                  setSelectedProducts([])
                }
              }}
            />
            <span className="text-sm text-muted-foreground">全选</span>
          </div>
            {selectedProducts.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">已选择 {selectedProducts.length} 个商品</span>
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
        <CardContent className="p-0">
          <div className="divide-y">
            {currentProducts.map((product) => (
              <div key={product.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                <div className="flex gap-3 items-center">
                  <Checkbox
                    checked={selectedProducts.includes(product.id)}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        setSelectedProducts([...selectedProducts, product.id])
                      } else {
                        setSelectedProducts(selectedProducts.filter(id => id !== product.id))
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
                      <span className="text-[11px] text-muted-foreground italic">{product.images?.length || 0}张图片</span>
                      {((product.createdAt) || (product.created_at)) && (
                        <span className="text-[11px] text-muted-foreground italic">创建: {new Date(product.createdAt || product.created_at).toLocaleString()}</span>
                      )}
                      {product.ruleEnabled && <span className="text-[11px] text-purple-600 font-bold">延迟: {product.min_delay}-{product.max_delay}s</span>}
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

                              <div className="space-y-2">
                                <Label>回复延迟范围 (秒)</Label>
                                <div className="flex gap-2">
                                  <div className="flex-1">
                                    <Label className="text-xs text-gray-600">最小</Label>
                                    <Input
                                      type="number"
                                      min="0"
                                      max="300"
                                      placeholder="0"
                                      value={editingProduct?.min_delay || 0}
                                      onChange={(e) => setEditingProduct({...editingProduct, min_delay: parseInt(e.target.value) || 0})}
                                    />
                                  </div>
                                  <div className="flex-1">
                                    <Label className="text-xs text-gray-600">最大</Label>
                                    <Input
                                      type="number"
                                      min="0"
                                      max="300"
                                      placeholder="0"
                                      value={editingProduct?.max_delay || 0}
                                      onChange={(e) => setEditingProduct({...editingProduct, max_delay: parseInt(e.target.value) || 0})}
                                    />
                                  </div>
                                </div>
                                <p className="text-xs text-gray-500">在指定范围内随机延迟回复，0表示立即回复</p>
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
  )
}
