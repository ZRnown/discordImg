"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Copy, ChevronLeft, ChevronRight, Trash2, ImageIcon, Edit, X, Download, Loader2, List, Upload, Store, CheckSquare, Square, Search, ChevronDown, ChevronUp } from "lucide-react"
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

export function ScraperView({ currentUser }: { currentUser: any }) {
  const [batchIds, setBatchIds] = useState('')
  const [isBatchScraping, setIsBatchScraping] = useState(false)
  const [batchProgress, setBatchProgress] = useState(0)
  const [products, setProducts] = useState<any[]>([])
  const [totalProducts, setTotalProducts] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [jumpPage, setJumpPage] = useState("")
  const [itemsPerPage, setItemsPerPage] = useState(50)
  const [editingProduct, setEditingProduct] = useState<any>(null)
  const [selectedProducts, setSelectedProducts] = useState<number[]>([])
  const [selectAll, setSelectAll] = useState(false)
  const [indexedIds, setIndexedIds] = useState<string[]>([])
  const [shopFilter, setShopFilter] = useState('__ALL__')
  const [keywordSearch, setKeywordSearch] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deletingProductId, setDeletingProductId] = useState<number | null>(null)
  // 图片上传 ref
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const [isUploadingImg, setIsUploadingImg] = useState(false)
  const [productUrls, setProductUrls] = useState<{[key: number]: any[]}>({})
  const [expandedProducts, setExpandedProducts] = useState<Set<number>>(new Set())
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null)
  const [batchUploading, setBatchUploading] = useState(false)

  // 抓取相关状态
  const [shopId, setShopId] = useState('')
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [shopScrapeProgress, setShopScrapeProgress] = useState(0)
  const [availableShops, setAvailableShops] = useState<any[]>([])
  const [selectedShopId, setSelectedShopId] = useState('')
  const [totalProductsCount, setTotalProductsCount] = useState(0)
  // 搜索类型状态
  const [searchType, setSearchType] = useState<'all' | 'id' | 'keyword' | 'chinese'>('all')

  useEffect(() => {
    fetchProducts()
    fetchIndexedIds()
    fetchAvailableShops()
    fetchProductsCount()

    // 定期检查抓取状态和商品数量
    const statusInterval = setInterval(() => {
      fetchScrapeStatus()
      fetchProductsCount()
    }, 2000)
    return () => clearInterval(statusInterval)
  }, [])

  const fetchProducts = async () => {
    try {
      const res = await fetch('/api/products', {
        credentials: 'include'
      })
      const data = await res.json()

      // 调试信息
      console.log('商品列表API响应:', {
        total: data.total,
        productsCount: data.products?.length || 0,
        debug: data.debug,
        firstProduct: data.products?.[0] ? {
          id: data.products[0].id,
          shopName: data.products[0].shopName || data.products[0].shop_name,
          title: data.products[0].title
        } : null
      })

      const processedProducts = (Array.isArray(data.products) ? data.products : []).map((product: any) => ({
        ...product,
        id: product.id,
        shopName: product.shopName || product.shop_name || '未知店铺',
        title: product.title || '',
        englishTitle: product.englishTitle || product.english_title || '',
        weidianUrl: product.weidianUrl || product.product_url || '',
        cnfansUrl: product.cnfansUrl || product.cnfans_url || '',
        acbuyUrl: product.acbuyUrl || product.acbuy_url || '',
        weidianId: product.weidianId || '',
        autoReplyEnabled: product.autoReplyEnabled !== undefined ? product.autoReplyEnabled : (product.ruleEnabled !== undefined ? product.ruleEnabled : true)
      }))
      setProducts(processedProducts)
      setTotalProducts(data.total || 0)
    } catch (e) {
      toast.error("加载商品库失败")
    }
  }

  const fetchIndexedIds = async () => {
    try {
      const res = await fetch('/api/scrape?type=indexed', { credentials: 'include' })
      const data = await res.json()
      setIndexedIds(data.indexedIds || [])
    } catch (e) {}
  }

  const fetchAvailableShops = async () => {
    try {
      const res = await fetch('/api/shops', {
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setAvailableShops(data.shops || [])
      }
    } catch (e) {}
  }

  const fetchProductsCount = async () => {
    try {
      const res = await fetch('/api/products/count', {
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setTotalProductsCount(data.count || 0)
      }
    } catch (e) {
      // 静默失败
    }
  }

  const fetchScrapeStatus = async () => {
    try {
      const res = await fetch('/api/scrape/shop/status')
      if (res.ok) {
        const text = await res.text()
        if (text.trim()) {
          const status = JSON.parse(text)
          setIsShopScraping(status.is_scraping)
          setShopScrapeProgress(status.progress || 0)
          // 如果抓取完成，刷新商品列表
          if (!status.is_scraping && status.completed) {
            fetchProducts()
            fetchProductsCount()
          }
        }
      }
    } catch (e) {
      console.error('获取抓取状态失败:', e)
      // 静默失败
    }
  }

  // === 链接生成逻辑 ===

  const getProductLinks = (product: any) => {
    const links = [
        { name: 'cnfans', display_name: 'CNFans', url: product.cnfansUrl, badge_color: 'blue' },
        { name: 'weidian', display_name: '微店', url: product.weidianUrl, badge_color: 'gray' },
        { name: 'acbuy', display_name: 'AcBuy', url: product.acbuyUrl, badge_color: 'orange' }
    ].filter(link => link.url && link.url.trim() !== '');

    // 如果有从后端获取的额外链接，可以合并（这里简化处理，只用上面的）
    return links;
  }

  // ... (保留 handleBatchDelete, confirmBatchDelete, handleUploadImage, handleBatchUploadImages) ...

  const handleBatchDelete = async () => {
    console.log('批量删除按钮被点击，选中商品数量:', selectedProducts.length)
    if (selectedProducts.length === 0) {
      console.log('没有选中商品，返回')
      return
    }
    console.log('设置显示确认对话框')
    setShowDeleteConfirm(true)
  }

  const confirmBatchDelete = async () => {
    setShowDeleteConfirm(false)
    setIsDeleting(true)
    try {
      const res = await fetch(`/api/products?ids=${selectedProducts.join(',')}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        toast.success("批量删除成功")
        setProducts(products.filter(p => !selectedProducts.includes(p.id)))
        setSelectedProducts([])
      } else {
        toast.error("批量删除失败")
      }
    } catch (e) {
      toast.error("网络错误")
    } finally {
      setIsDeleting(false)
    }
  }

  const handleUploadImage = async (productId: number, file: File) => {
    if (!file) return
    setIsUploadingImg(true)
    const formData = new FormData()
    formData.append('image', file)
    try {
      const res = await fetch(`/api/products/${productId}/images`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      })
      if (res.ok) {
        const data = await res.json()
        setProducts(products.map(p => p.id === productId ? data.product : p))
        toast.success("图片上传成功")
      } else {
        toast.error("上传失败")
      }
    } catch (e) {
      toast.error("上传出错")
    } finally {
      setIsUploadingImg(false)
    }
  }

  const handleBatchUploadImages = async (productId: number, files?: FileList | null) => {
    const filesToUpload = files || selectedFiles
    if (!filesToUpload || filesToUpload.length === 0) return
    setBatchUploading(true)
    let successCount = 0
    try {
      for (let i = 0; i < filesToUpload.length; i++) {
        const file = filesToUpload[i]
        const formData = new FormData()
        formData.append('image', file)
          const res = await fetch(`/api/products/${productId}/images`, {
            method: 'POST',
            credentials: 'include',
            body: formData
          })
        if (res.ok) successCount++
      }
      if (successCount > 0) {
        const productRes = await fetch(`/api/products/${productId}`, {
          credentials: 'include'
        }) // Fix: fetch specific product if endpoint exists, else refresh all or return from API
        // Refresh products for simplicity
        fetchProducts();
      }
      toast.success(`上传完成：${successCount}张图片`)
      setSelectedFiles(null)
    } catch (e) {
      toast.error('批量上传错误')
    } finally {
      setBatchUploading(false)
    }
  }

  const handleSelectAll = () => {
    if (selectedProducts.length === filteredProducts.length && filteredProducts.length > 0) {
      setSelectedProducts([])
    } else {
      setSelectedProducts(filteredProducts.map(p => p.id))
    }
  }

  const toggleProductExpansion = (productId: number) => {
    setExpandedProducts(prev => {
      const newSet = new Set(prev)
      if (newSet.has(productId)) newSet.delete(productId)
      else newSet.add(productId)
      return newSet
    })
  }

  const handleDeleteProduct = async (id: number) => {
    setDeletingProductId(id)
    setShowDeleteConfirm(true)
  }

  const confirmDeleteProduct = async () => {
    if (!deletingProductId) return

    setShowDeleteConfirm(false)

    // 显示删除进度提示
    toast.loading("正在删除商品...", { id: `delete-${deletingProductId}` })

    try {
      const response = await fetch(`/api/products/${deletingProductId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        setProducts(products.filter(p => p.id !== deletingProductId))
        setTotalProducts(totalProducts - 1)
        setSelectedProducts(selectedProducts.filter(pid => pid !== deletingProductId))
        toast.success("删除成功", { id: `delete-${deletingProductId}` })
      } else {
        toast.error("删除失败", { id: `delete-${deletingProductId}` })
      }
    } catch (e) {
      toast.error("删除失败", { id: `delete-${deletingProductId}` })
    } finally {
      setDeletingProductId(null)
    }
  }

  const handleUpdateProduct = async (updatedProduct: any) => {
    try {
      const res = await fetch('/api/products', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
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


  // ... (保留 handleScrapeShop, handleBatchScrape, handleJumpPage) ...

  const handleScrapeShop = async () => {
    if (!selectedShopId) {
      toast.error("请选择要抓取的店铺")
      return
    }

    setIsShopScraping(true)
    setShopScrapeProgress(0)

    try {
      const response = await fetch('/api/scrape/shop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ shopId: selectedShopId })
      })

      if (response.ok) {
        const data = await response.json()
        toast.success(`店铺抓取完成！共获取 ${data.totalProducts} 个商品`)
        fetchProducts()
      } else {
        const errorData = await response.json()
        toast.error(errorData.error || "店铺抓取失败")
      }
    } catch (error) {
      toast.error("网络错误，无法抓取店铺")
    } finally {
      setIsShopScraping(false)
      setShopScrapeProgress(0)
    }
  }

  const handleBatchScrape = async () => { /* ... existing code with 409 fix ... */
    const ids = batchIds.split('\n').map(id => id.trim()).filter(id => id && id.match(/^\d+$/))
    if (ids.length === 0) { toast.error("请输入有效的商品ID"); return }
    setIsBatchScraping(true)
    setBatchProgress(0)
    let successCount = 0
    let skipCount = 0
    try {
        for(let i=0; i<ids.length; i++) {
        const id = ids[i]
            const res = await fetch('/api/scrape', {
            method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
            body: JSON.stringify({ weidianId: id })
            })
            if(res.ok) successCount++
            else if(res.status === 409) skipCount++
            setBatchProgress(((i+1)/ids.length)*100)
        }
        toast.success(`完成: 成功 ${successCount}, 跳过 ${skipCount}`)
        fetchProducts()
        setBatchIds('')
    } catch(e) { toast.error("错误") }
    finally { setIsBatchScraping(false) }
  }

  const handleJumpPage = () => { /* ... */ }

  // 筛选和分页逻辑
  const uniqueShops = Array.from(new Set(products.map(p => p?.shopName || '').filter(name => name && name.trim()))).sort()
  const filteredProducts = products.filter(p => {
    let matchesSearch = true
    if (keywordSearch) {
      if (searchType === 'id') {
        matchesSearch = p.weidianId?.includes(keywordSearch)
      } else if (searchType === 'keyword') {
        matchesSearch = p.englishTitle?.toLowerCase().includes(keywordSearch.toLowerCase())
      } else if (searchType === 'chinese') {
        matchesSearch = p.title?.toLowerCase().includes(keywordSearch.toLowerCase())
      } else {
        matchesSearch = p.title?.toLowerCase().includes(keywordSearch.toLowerCase()) ||
      p.englishTitle?.toLowerCase().includes(keywordSearch.toLowerCase()) ||
      p.weidianId?.includes(keywordSearch)
      }
    }
    const matchesShop = !shopFilter || shopFilter === "__ALL__" || p.shopName === shopFilter
    return matchesSearch && matchesShop
  })
  const totalPages = Math.ceil(filteredProducts.length / itemsPerPage)
  const currentProducts = filteredProducts.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)

  return (
    <div className="space-y-8">
      {/* ... 顶部标题和管理员/普通用户上传区域 (保持不变) ... */}

      <div>
        <h2 className="text-3xl font-bold tracking-tight">微店抓取</h2>
        <p className="text-muted-foreground">商品管理与抓取</p>
      </div>

      {(currentUser?.role === 'admin' || (currentUser?.shops && currentUser.shops.length > 0)) ? (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
             {/* Shop Scrape Card */}
        <Card className="border-2 border-dashed border-purple-300/50 hover:border-purple-400 transition-colors">
          <CardContent className="p-6">
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                            <div className="p-3 bg-purple-100 rounded-xl"><Store className="h-6 w-6 text-purple-600"/></div>
                            <div><h4 className="text-xl font-bold">店铺商品抓取</h4><p className="text-sm text-muted-foreground">输入店铺ID</p></div>
                </div>
                        <div className="space-y-3">
                <div>
                                <Label className="text-sm">选择店铺</Label>
                                <Select value={selectedShopId} onValueChange={setSelectedShopId} disabled={isShopScraping}>
                                    <SelectTrigger className="w-full">
                                        <SelectValue placeholder="请选择要抓取的店铺" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {availableShops.map((shop) => (
                                            <SelectItem key={shop.shop_id} value={shop.shop_id}>
                                                {shop.name} (ID: {shop.shop_id})
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                </div>
                            <Button onClick={handleScrapeShop} disabled={!selectedShopId || isShopScraping} className="w-full">
                                {isShopScraping ? "抓取中..." : "抓取店铺"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
             {/* Batch Scrape Card */}
        <Card className="border-2 border-dashed border-green-300/50 hover:border-green-400 transition-colors">
          <CardContent className="p-6">
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                            <div className="p-3 bg-green-100 rounded-xl"><List className="h-6 w-6 text-green-600"/></div>
                            <div><h4 className="text-xl font-bold">批量上传</h4><p className="text-sm text-muted-foreground">输入商品ID</p></div>
                </div>
              <div className="space-y-3">
                            <textarea placeholder="每行一个ID" value={batchIds} onChange={e=>setBatchIds(e.target.value)} className="w-full h-32 p-4 text-sm border-2 rounded-lg resize-none"/>
                            <Button onClick={handleBatchScrape} disabled={!batchIds.trim() || isBatchScraping} className="w-full">
                                {isBatchScraping ? "上传中..." : `批量上传`}
                  </Button>
              </div>
            </div>
          </CardContent>
        </Card>
        </div>
      ) : (
          /* User View - 普通用户只能看到批量上传 */
        <div className="max-w-2xl mx-auto">
             <Card className="border-2 border-dashed border-green-300/50">
            <CardContent className="p-8">
                    <div className="space-y-4">
                  <h4 className="text-2xl font-bold mb-2">批量商品上传</h4>
                        <textarea id="batch-ids" placeholder="每行一个ID" value={batchIds} onChange={e=>setBatchIds(e.target.value)} className="w-full h-40 p-4 border-2 rounded-lg"/>
                        <Button onClick={handleBatchScrape} disabled={!batchIds.trim() || isBatchScraping} className="w-full">批量上传</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Progress Bar - 只显示批量抓取进度 */}
      {isBatchScraping && (
        <div className="space-y-3">
          <Progress value={batchProgress} className="h-3" />
          <p className="text-center text-sm text-muted-foreground">{batchProgress.toFixed(1)}%</p>
        </div>
      )}

      {/* Product List */}
      <div className="space-y-4">
        <Card className="shadow-sm">
            <CardHeader className="py-4 border-b">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
            <div className="flex flex-col gap-1">
                        <CardTitle className="text-xl font-bold">
                          商品库 ({totalProductsCount}{isShopScraping ? ' - 抓取中...' : ''})
                        </CardTitle>
            </div>
                    <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center w-full sm:w-auto">
                        {/* 搜索控件 */}
                        <div className="flex gap-2 flex-1 sm:flex-initial">
                <div className="relative">
                                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                                    placeholder={
                                        searchType === 'id' ? '输入商品ID...' :
                                        searchType === 'keyword' ? '输入英文关键词...' :
                                        searchType === 'chinese' ? '输入中文关键词...' :
                                        '输入商品标题、中文关键词、英文关键词或ID...'
                                    }
                    value={keywordSearch}
                                    onChange={e=>setKeywordSearch(e.target.value)}
                                    className="pl-10 h-9 w-full sm:w-[400px]"
                  />
                </div>
                            <Select value={searchType} onValueChange={(value: 'all' | 'id' | 'keyword' | 'chinese') => setSearchType(value)}>
                                <SelectTrigger className="h-9 w-28">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">全部</SelectItem>
                                    <SelectItem value="id">按ID</SelectItem>
                                    <SelectItem value="keyword">英文关键词</SelectItem>
                                    <SelectItem value="chinese">中文关键词</SelectItem>
                                </SelectContent>
                            </Select>
                  <Select value={shopFilter} onValueChange={setShopFilter}>
                                <SelectTrigger className="h-9 w-32">
                                    <SelectValue placeholder="全部店铺" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__ALL__">全部店铺</SelectItem>
                                    {uniqueShops.map(s=><SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
              <Select value={itemsPerPage.toString()} onValueChange={(v) => {
                setItemsPerPage(parseInt(v))
                setCurrentPage(1)
              }}>
                                <SelectTrigger className="h-9 w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                                    <SelectItem value="20">20个/页</SelectItem>
                                    <SelectItem value="50">50个/页</SelectItem>
                                    <SelectItem value="100">100个/页</SelectItem>
                                    <SelectItem value="200">200个/页</SelectItem>
                </SelectContent>
              </Select>
            </div>
                        {/* 操作按钮 */}
                        <div className="flex items-center gap-3">
                            <Button variant={selectedProducts.length===filteredProducts.length && filteredProducts.length>0?"secondary":"outline"} size="sm" onClick={handleSelectAll}>
                                {selectedProducts.length===filteredProducts.length && filteredProducts.length>0 ? <CheckSquare className="mr-2 h-4 w-4"/> : <Square className="mr-2 h-4 w-4"/>} 全选 ({filteredProducts.length})
            </Button>
                            {selectedProducts.length > 0 && (
                                <Button variant="destructive" size="sm" onClick={handleBatchDelete} disabled={isDeleting}>
                                    <Trash2 className="mr-2 h-4 w-4" /> 删除 ({selectedProducts.length})
                                </Button>
                            )}
          </div>
              </div>
            </div>
            </CardHeader>
            <CardContent className="p-0">
                {/* 列表 */}
          <div className="divide-y">
                    {currentProducts.map((product) => {
                        const links = getProductLinks(product);
                        const showAllLinks = expandedProducts.has(product.id);
                        const displayedLinks = showAllLinks ? links : links.slice(0, 3);
                        return (
              <div key={product.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3">
                <div className="flex gap-3 items-center">
                                <Checkbox checked={selectedProducts.includes(product.id)} onCheckedChange={(checked)=>{
                                    if(checked) setSelectedProducts([...selectedProducts, product.id])
                                    else setSelectedProducts(selectedProducts.filter(id=>id!==product.id))
                                }}/>
                </div>

                            {/* 图片与基本信息 */}
                <div className="flex gap-3 items-center flex-1">
                                {/* 图片弹窗 (保持原逻辑) */}
                  <Dialog>
                    <DialogTrigger asChild>
                                        <Button variant="ghost" className="size-10 p-0 rounded bg-muted flex items-center justify-center flex-shrink-0 border shadow-sm">
                        {product.images && product.images.length > 0 ? (
                                                <img src={product.images[0]} alt="thumb" className="object-cover w-12 h-12 rounded-md" />
                                            ) : <ImageIcon className="size-4 text-muted-foreground" />}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-4xl">
                      <DialogHeader>
                        <DialogTitle className="text-xl">商品图集 - {product.weidianId}</DialogTitle>
                        <div className="flex gap-2 mt-2">
                          <input
                            type="file"
                            accept="image/*"
                            multiple
                            className="hidden"
                            id={`upload-${product.id}`}
                            onChange={(e) => {
                              const files = (e.target as HTMLInputElement).files
                              if (files && files.length > 0) {
                                handleBatchUploadImages(product.id, files)
                              }
                            }}
                          />
                          <label htmlFor={`upload-${product.id}`}>
                            <Button size="sm" disabled={isUploadingImg || batchUploading} asChild>
                              <span className="cursor-pointer">
                                <Upload className="mr-2 h-4 w-4" />
                                {isUploadingImg || batchUploading ? "上传中..." : "添加图片"}
                              </span>
                            </Button>
                          </label>
                        </div>
                      </DialogHeader>
                      <ScrollArea className="max-h-[70vh] mt-4">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-1">
                          {product.images?.map((img: string, idx: number) => (
                            <div key={img} className="aspect-square rounded-xl border-2 bg-muted overflow-hidden group relative">
                              <img src={img} alt={`Img ${idx}`} className="object-cover w-full h-full transition-transform group-hover:scale-110" />
                              <button
                                                            onClick={async (e) => {
                                                                e.preventDefault()
                                                                e.stopPropagation()
                                                                try {
                                                                    // 从图片URL中提取image_index
                                                                    // URL格式: /api/image/{product_id}/{image_index}
                                                                    const urlParts = img.split('/')
                                                                    const imageIndex = urlParts[urlParts.length - 1] // 获取最后一个部分

                                                                    // 验证imageIndex是否为有效数字
                                                                    if (!imageIndex || isNaN(Number(imageIndex))) {
                                                                        toast.error("无法确定要删除的图片")
                                                                        return
                                                                    }

                                                                    const res = await fetch(`/api/products/${product.id}/images/${imageIndex}`, {
                                                                        method: 'DELETE',
                                                                        credentials: 'include'
                                  })
                                  if (res.ok) {
                                    const data = await res.json()
                                                                        // 更新产品状态，替换整个产品对象
                                                                        setProducts(prevProducts =>
                                                                            prevProducts.map(p =>
                                                                                p.id === product.id ? { ...data.product } : p
                                                                            )
                                                                        )
                                                                        toast.success("图片已删除")
                                  } else {
                                                                        const errorData = await res.json().catch(() => ({ error: 'Delete failed' }))
                                                                        toast.error(errorData.error || "删除失败")
                                                                        console.error('Delete failed:', errorData)
                                                                    }
                                                                } catch (error) {
                                                                    console.error('Delete image error:', error)
                                                                    toast.error("网络错误，删除失败")
                                  }
                                }}
                                                            className="absolute top-1 right-1 p-1 bg-red-500 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600 shadow-lg z-10"
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
                                        <h4 className="font-bold text-base truncate">{product.title}</h4>
                                        {/* 已删除这里原本的小编辑按钮 */}
                                        {indexedIds.includes(product.weidianId) && <Badge className="bg-blue-600 text-[10px] h-4 px-2">已索引</Badge>}
                                        {product.ruleEnabled && <Badge className="bg-purple-600 text-[10px] h-4 px-2">规则启用</Badge>}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                                        <p className="text-sm font-bold text-blue-600 truncate">{product.englishTitle || "No English Title"}</p>
                    </div>
                                    <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                                        <span className="font-mono">ID: {product.weidianId}</span>
                                        <span>|</span>
                                        <span>店铺: {product.shopName}</span>
                                        <span>|</span>
                                        <span>{product.images?.length || 0}张图片</span>
                      {((product.createdAt) || (product.created_at)) && (
                                            <>
                                                <span>|</span>
                                                <span>创建: {(() => {
                          try {
                            const date = new Date(product.createdAt || product.created_at);
                            return isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN');
                          } catch {
                            return '未知时间';
                          }
                        })()}</span>
                                            </>
                      )}
                    </div>
                  </div>
                </div>
                            {/* 链接显示区域 */}
                <div className="flex items-center gap-4">
                                <div className="flex flex-col gap-1 min-w-0 flex-1 max-w-md">
                                    {displayedLinks.map((link) => (
                      <div key={link.name} className="flex items-center gap-1.5">
                                            <Badge className={`text-[9px] px-1 py-0 h-4 border-none w-12 justify-center shrink-0 text-white ${
                          link.badge_color === 'blue' ? 'bg-blue-600' :
                          link.badge_color === 'green' ? 'bg-green-600' :
                                                link.badge_color === 'orange' ? 'bg-orange-600' : 'bg-gray-600'
                                            }`}>{link.display_name}</Badge>
                        <div className="flex-1 bg-muted/30 p-0.5 px-2 rounded border text-[10px] flex items-center justify-between overflow-hidden">
                                                <a href={link.url} target="_blank" className="font-mono truncate hover:underline text-muted-foreground">{link.url}</a>
                                                <Button variant="ghost" size="icon" className="h-4 w-4" onClick={()=>{navigator.clipboard.writeText(link.url); toast.success("Copied")}}><Copy className="h-2.5 w-2.5"/></Button>
                        </div>
                      </div>
                    ))}
                                    {links.length > 3 && (
                                        <Button variant="ghost" size="sm" className="h-5 text-xs w-full" onClick={()=>toggleProductExpansion(product.id)}>
                                            {showAllLinks ? <ChevronUp className="h-3 w-3"/> : <ChevronDown className="h-3 w-3"/>}
                                            {showAllLinks ? "收起" : `显示更多 (${links.length - 3})`}
                      </Button>
                    )}
                  </div>
                                {/* 操作按钮组 */}
                                <div className="flex items-center gap-1">
                                    {/* 编辑按钮 */}
                                    <Dialog open={editingProduct?.id === product.id} onOpenChange={(open)=>!open && setEditingProduct(null)}>
                      <DialogTrigger asChild>
                                            <Button variant="outline" size="icon" className="h-8 w-8" onClick={()=>setEditingProduct(product)}>
                                                <Edit className="size-3.5"/>
                        </Button>
                      </DialogTrigger>
                                        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
                        <DialogHeader>
                                                <DialogTitle>编辑商品与规则 - {product.weidianId}</DialogTitle>
                          <DialogDescription>配置商品信息和自动回复规则</DialogDescription>
                        </DialogHeader>

                                            <div className="space-y-6 py-4">
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
                                                        <p className="text-xs text-muted-foreground">当检测到关键词时自动发送链接</p>
                            </div>
                                                    <Switch checked={editingProduct?.ruleEnabled || false} onCheckedChange={(c) => setEditingProduct({...editingProduct, ruleEnabled: c})} />
                          </div>
                        </div>
                        <DialogFooter>
                                                <Button variant="outline" onClick={()=>setEditingProduct(null)}>取消</Button>
                                                <Button onClick={()=>handleUpdateProduct(editingProduct)}>保存修改</Button>
                        </DialogFooter>
                      </DialogContent>
                    </Dialog>

                                    {/* 删除按钮 */}
                                    <Button variant="outline" size="icon" className="h-8 w-8 hover:bg-red-50 hover:text-red-600" onClick={()=>handleDeleteProduct(product.id)}>
                                        <Trash2 className="size-3.5"/>
                    </Button>
                  </div>
                </div>
              </div>
                        )
                    })}
          </div>
          
                {/* 分页组件 */}
                {filteredProducts.length > 0 && (
                    <div className="flex flex-col sm:flex-row justify-between items-center gap-4 p-6 border-t bg-muted/5">
              <div className="text-sm text-muted-foreground font-medium">
                            显示第 {(currentPage-1)*itemsPerPage + 1} - {Math.min(currentPage*itemsPerPage, filteredProducts.length)} 条，共 {filteredProducts.length} 条记录
                            <span className="ml-2">({currentPage}/{totalPages}页)</span>
              </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                                onClick={()=>setCurrentPage(p=>Math.max(1, p-1))}
                                disabled={currentPage===1}
                                className="h-8 px-3"
                  >
                                <ChevronLeft className="h-4 w-4 mr-1"/> 上一页
                  </Button>
                            <div className="text-sm font-medium bg-primary text-primary-foreground px-3 py-1 rounded">
                    {currentPage} / {totalPages}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                                onClick={()=>setCurrentPage(p=>Math.min(totalPages, p+1))}
                                disabled={currentPage===totalPages}
                                className="h-8 px-3"
                  >
                                下一页 <ChevronRight className="h-4 w-4 ml-1"/>
                  </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

        {/* 单个商品删除确认对话框 */}
        <Dialog open={showDeleteConfirm && deletingProductId !== null} onOpenChange={(open) => {
          if (!open) {
            setShowDeleteConfirm(false)
            setDeletingProductId(null)
          }
        }}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除商品</DialogTitle>
              <DialogDescription>
                确定要删除商品 {deletingProductId} 吗？此操作不可恢复。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => {
                setShowDeleteConfirm(false)
                setDeletingProductId(null)
              }}>
                取消
              </Button>
              <Button
                variant="destructive"
                onClick={confirmDeleteProduct}
              >
                确认删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

      {/* 批量删除确认对话框 */}
        <Dialog open={showDeleteConfirm && deletingProductId === null} onOpenChange={setShowDeleteConfirm}>
        <DialogContent>
          <DialogHeader>
              <DialogTitle>确认批量删除</DialogTitle>
            <DialogDescription>
              确定要删除选中的 {selectedProducts.length} 个商品吗？此操作不可恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDeleteConfirm(false)}>
              取消
            </Button>
              <Button
                variant="destructive"
                onClick={confirmBatchDelete}
                disabled={isDeleting}
              >
              {isDeleting ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      </div>
    </div>
  )
}