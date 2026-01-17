"use client"

import { useState, useEffect, useRef } from "react"
import { useApiCache } from "@/hooks/use-api-cache"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Copy, ChevronLeft, ChevronRight, Trash2, ImageIcon, Edit, X, Download, Loader2, List, Upload, Store, CheckSquare, Square, Search, ChevronDown, ChevronUp, Pause, Play, StopCircle } from "lucide-react"
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

  // 使用API缓存hook
  const { cachedFetch, invalidateCache } = useApiCache()

  // 抓取相关状态
  const [shopId, setShopId] = useState('')
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [shopScrapeProgress, setShopScrapeProgress] = useState(0)
  const [scrapeStatus, setScrapeStatus] = useState<any>(null)
  const [availableShops, setAvailableShops] = useState<any[]>([])
  const [selectedShopId, setSelectedShopId] = useState('')
  const [totalProductsCount, setTotalProductsCount] = useState(0)
  // 搜索类型状态
  const [searchType, setSearchType] = useState<'all' | 'id' | 'keyword' | 'chinese'>('all')

  // 优化：分离不同类型的加载逻辑
  useEffect(() => {
    fetchIndexedIds()
    fetchAvailableShops()
    fetchProductsCount()
    fetchScrapeStatus() // 初始化时检查抓取状态，恢复进度显示
  }, []) // 静态数据只加载一次

  // 监听店铺更新事件，实时刷新店铺列表
  useEffect(() => {
    const handleShopsUpdated = () => {
      // 清除店铺缓存并重新获取
      invalidateCache('/api/shops')
      fetchAvailableShops()
    }
    window.addEventListener('shops-updated', handleShopsUpdated)
    return () => window.removeEventListener('shops-updated', handleShopsUpdated)
  }, [invalidateCache])

  useEffect(() => {
    fetchProducts(currentPage)
  }, [currentPage, itemsPerPage, keywordSearch, shopFilter]) // 只在相关参数改变时重新加载商品

  useEffect(() => {
    // 当搜索条件改变时，重置到第一页
    if (keywordSearch || shopFilter) {
      setCurrentPage(1)
    }
  }, [keywordSearch, shopFilter])

  // 优化轮询机制：使用智能轮询，避免重复请求
  useEffect(() => {
    let statusInterval: NodeJS.Timeout | null = null

    // 如果没有抓取任务，减少轮询频率到60秒一次
    if (!isShopScraping && !isBatchScraping) {
      statusInterval = setInterval(() => {
        fetchScrapeStatus()
      }, 60000) // 60秒检查一次状态

      return () => {
        if (statusInterval) clearInterval(statusInterval)
      }
    }

    // 如果有抓取任务，使用更智能的轮询策略
    let pollCount = 0
    statusInterval = setInterval(() => {
      pollCount++

      // 总是检查抓取状态
      fetchScrapeStatus()

      // 只有在抓取进行中时才检查商品数量和列表
      // 前30秒（15次）每2秒检查一次，后续每10秒检查一次
      if ((isShopScraping || isBatchScraping)) {
        if (pollCount <= 15) {
          fetchProductsCount()
          fetchProducts(currentPage)
        } else if (pollCount % 5 === 0) {
          // 每10秒检查一次商品数量和列表
          fetchProductsCount()
          fetchProducts(currentPage)
        }
      }
    }, 2000) // 基础间隔2秒

    return () => {
      if (statusInterval) {
        clearInterval(statusInterval)
      }
    }
  }, [isShopScraping, isBatchScraping])

  const fetchProducts = async (page: number = 1, append: boolean = false, usePreload: boolean = true) => {
    try {
      // 首先检查是否有预加载数据（只在第一次加载且未追加时）
      if (page === 1 && !append && usePreload) {
        const preloadData = sessionStorage.getItem('preload_products')
        if (preloadData) {
          try {
            console.log('使用预加载商品数据')
            const data = JSON.parse(preloadData)
            // 使用预加载数据
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
              ruleEnabled: product.ruleEnabled !== undefined ? product.ruleEnabled : true,
              customReplyText: product.customReplyText || product.custom_reply_text || '',
              customReplyImages: product.customReplyImages || product.custom_reply_images || [],
              selectedImageIndexes: product.selectedImageIndexes || [],
              customImageUrls: product.customImageUrls || product.custom_image_urls || [],
              imageSource: product.imageSource || product.image_source || (product.custom_image_urls ? 'custom' : 'upload')
            }))

            setProducts(processedProducts)
            setTotalProducts(data.total || 0)

            // 清除预加载数据，避免重复使用
            sessionStorage.removeItem('preload_products')

            // 在后台获取最新数据，但不显示加载状态
            setTimeout(() => fetchProducts(1, false, false), 500)
            return
          } catch (e) {
            console.error('预加载数据解析失败:', e)
            // 预加载数据损坏，清除并重新获取
            sessionStorage.removeItem('preload_products')
          }
        } else {
          // 如果没有预加载数据，等待一下再试（给预加载一点时间）
          if (page === 1 && !append) {
            setTimeout(() => {
              const retryPreload = sessionStorage.getItem('preload_products')
              if (retryPreload) {
                fetchProducts(1, false, true)
              } else {
                fetchProducts(1, false, false)
              }
            }, 200)
            return
          }
        }
      }

      console.log('从API获取商品数据')
      const res = await fetch(`/api/products?page=${page}&limit=${itemsPerPage}`)
      const data = await res.json()

      // 调试信息
      console.log('商品列表API响应:', {
        page,
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
        ruleEnabled: product.ruleEnabled !== undefined ? product.ruleEnabled : true,
        customReplyText: product.customReplyText || product.custom_reply_text || '',
        customReplyImages: product.customReplyImages || product.custom_reply_images || [],
        selectedImageIndexes: product.selectedImageIndexes || [],
        customImageUrls: product.customImageUrls || product.custom_image_urls || [],
        imageSource: product.imageSource || product.image_source || (product.custom_image_urls ? 'custom' : 'upload'),
        uploadedImages: product.uploadedImages || []
      }))

      if (append) {
        // 分页加载更多
        setProducts(prev => [...prev, ...processedProducts])
      } else {
        // 重新加载第一页
        setProducts(processedProducts)
      }

      setTotalProducts(data.total || 0)
    } catch (e) {
      toast.error("加载商品库失败")
    }
  }

  const fetchIndexedIds = async () => {
    try {
      const data = await cachedFetch('/api/scrape?type=indexed', { credentials: 'include' })
      setIndexedIds(data.indexedIds || [])
    } catch (e) {
      console.error('获取已索引ID失败:', e)
    }
  }

  const fetchAvailableShops = async () => {
    try {
      const data = await cachedFetch('/api/shops')
      setAvailableShops(data.shops || [])
    } catch (e) {
      console.error('获取店铺列表失败:', e)
    }
  }

  const fetchProductsCount = async () => {
    try {
      const data = await cachedFetch('/api/products/count')
      setTotalProductsCount(data.count || 0)
    } catch (e) {
      console.error('获取商品数量失败:', e)
    }
  }

  const fetchScrapeStatus = async () => {
    try {
      const res = await fetch('/api/scrape/shop/status')
      if (res.ok) {
        const text = await res.text()
        if (text.trim()) {
          const status = JSON.parse(text)
          console.log('店铺抓取状态更新:', status)
          setScrapeStatus(status)
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
          body: formData
          })
        if (res.ok) successCount++
      }
      if (successCount > 0) {
        const productRes = await fetch(`/api/products/${productId}`) // Fix: fetch specific product if endpoint exists, else refresh all or return from API
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
    if (selectedProducts.length === currentProducts.length && currentProducts.length > 0) {
      setSelectedProducts([])
    } else {
      setSelectedProducts(currentProducts.map(p => p.id))
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
      let res;

      // 检查是否有上传的图片文件
      if (updatedProduct.uploadedImages && updatedProduct.uploadedImages.length > 0) {
        // 使用FormData发送文件
        const formData = new FormData();

        // 添加基本数据
        formData.append('id', updatedProduct.id.toString());
        if (updatedProduct.title) formData.append('title', updatedProduct.title);
        if (updatedProduct.englishTitle) formData.append('englishTitle', updatedProduct.englishTitle);
        if (updatedProduct.ruleEnabled !== undefined) formData.append('ruleEnabled', updatedProduct.ruleEnabled.toString());
        if (updatedProduct.customReplyText) formData.append('customReplyText', updatedProduct.customReplyText);
        if (updatedProduct.imageSource) formData.append('imageSource', updatedProduct.imageSource);

        // 添加数组数据（序列化为JSON）
        if (updatedProduct.selectedImageIndexes) {
          formData.append('selectedImageIndexes', JSON.stringify(updatedProduct.selectedImageIndexes));
        }
        if (updatedProduct.customImageUrls) {
          formData.append('customImageUrls', JSON.stringify(updatedProduct.customImageUrls));
        }

        // 添加上传的文件
        updatedProduct.uploadedImages.forEach((file: File, index: number) => {
          formData.append('uploadedImages', file);
        });

        res = await fetch('/api/products', {
          method: 'PUT',
          credentials: 'include',
          body: formData
        });
      } else {
        // 使用JSON发送普通数据
        res = await fetch('/api/products', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(updatedProduct)
        });
      }

      if (res.ok) {
        const data = await res.json()
        setProducts(products.map(p => p.id === data.product.id ? data.product : p))
        setEditingProduct(null)
        toast.success("更新成功")
      } else {
        const errorData = await res.json().catch(() => ({}));
        toast.error(errorData.error || "更新失败")
      }
    } catch (e) {
      console.error('Update error:', e);
      toast.error("更新失败")
    }
  }


  // ... (保留 handleScrapeShop, handleBatchScrape, handleJumpPage) ...

  const handleScrapeControl = async (action: 'stop') => {
    try {
      console.log(`🎮 发送抓取控制请求: action=${action}`)
      const response = await fetch('/api/scrape/shop/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action
        })
      })

      if (response.ok) {
        const result = await response.json()
        console.log(`🎮 控制API响应内容:`, result)

        if (action === 'stop') {
          // 立即更新本地状态
          setIsShopScraping(false)
          setShopScrapeProgress(100)
          toast.success('抓取已停止')

          // 重新获取状态确认
          setTimeout(() => {
            fetchScrapeStatus()
            fetchProductsCount()
            fetchProducts(currentPage)
          }, 1000)
        }
      } else {
        const errorText = await response.text()
        console.error(`控制API错误响应:`, errorText)
        try {
          const errorData = JSON.parse(errorText)
          toast.error(errorData.error || `操作失败: ${action}`)
        } catch {
          toast.error(`操作失败: ${action}`)
        }
      }
    } catch (error) {
      console.error(`控制请求异常:`, error)
      toast.error(`操作失败: ${action}`)
    }
  }

  const handleScrapeShop = async () => {
    if (!selectedShopId) {
      toast.error("请选择要抓取的店铺")
      return
    }

    // ==========================================
    // 修复：立即设置加载状态，防止UI闪烁
    // ==========================================
    setIsShopScraping(true)
    setShopScrapeProgress(0)
    setScrapeStatus((prev: any) => ({
       ...prev,
       message: '正在发送抓取请求...'
    }))

    try {
      const response = await fetch('/api/scrape/shop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopId: selectedShopId })
      })

      if (response.ok) {
        const data = await response.json()
        toast.success(`抓取指令已发送`)
        // 不需要在这里 setProducts，因为轮询会自动更新
      } else {
        const errorData = await response.json()
        toast.error(errorData.error || "请求被拒绝")

        // 只有请求失败时，才把状态改回去
        setIsShopScraping(false)
      }
    } catch (error: any) {
      toast.error("网络错误，无法连接服务器")
      setIsShopScraping(false)
    }
    // 注意：这里不要加 finally { setIsShopScraping(false) }
    // 因为抓取是异步的长任务，请求结束不代表抓取结束。
    // 状态应该由 useEffect 里的轮询来决定何时变回 false。
  }

  const handleBatchScrape = async () => {
    const ids = batchIds.split('\n').map(id => id.trim()).filter(id => id && id.match(/^\d+$/))
    if (ids.length === 0) {
      toast.error("请输入有效的商品ID")
      return
    }

    console.log('开始批量上传，商品数量:', ids.length)
    setIsBatchScraping(true)
    setBatchProgress(0)

    try {
      console.log(`发送批量请求到 /api/scrape/batch，商品数量: ${ids.length}`)

      // 调用新的批量API
      const res = await fetch('/api/scrape/batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ productIds: ids }),
        signal: AbortSignal.timeout(300000) // 5分钟超时（批量处理需要更长时间）
      })

      console.log(`收到批量响应，状态码: ${res.status}`)

      if(res.ok) {
        const result = await res.json()
        console.log('批量处理结果:', result)

        // 从结果中提取统计信息
        const results = result.results || {}
        const successCount = results.success || 0
        const skipCount = results.skipped || 0
        const cancelledCount = results.cancelled || 0
        const partialCount = results.partial || 0
        const errorCount = results.errors || 0

        // 构建结果消息
        let messageParts = []
        if (successCount > 0) messageParts.push(`成功 ${successCount}`)
        if (skipCount > 0) messageParts.push(`跳过 ${skipCount}`)
        if (cancelledCount > 0) messageParts.push(`取消 ${cancelledCount}`)
        if (partialCount > 0) messageParts.push(`部分完成 ${partialCount}`)
        if (errorCount > 0) messageParts.push(`失败 ${errorCount}`)

        const message = messageParts.length > 0 ? messageParts.join(', ') : '无结果'

        toast.success(`批量上传完成: ${message}`)
        console.log('批量上传完成')

        // 显示处理时间
        if (results.duration) {
          console.log(`处理时间: ${results.duration.toFixed(2)} 秒`)
        }
      } else {
        const errorText = await res.text()
        console.error('批量上传失败:', res.status, errorText)
        toast.error(`批量上传失败: ${errorText}`)
      }

      setBatchProgress(100)

      // 强制刷新数据
      fetchProducts()
      fetchProductsCount()

      // 强制刷新抓取状态，确保UI正确更新
      setTimeout(() => fetchScrapeStatus(), 100)

      setBatchIds('')
    } catch(e: any) {
      console.error('批量上传出现错误:', e)
      if (e.name === 'TimeoutError') {
        toast.error("批量上传超时，请减少商品数量或稍后重试")
      } else {
        toast.error("批量上传失败")
      }
    } finally {
      console.log('设置 isBatchScraping 为 false')
      setIsBatchScraping(false)
    }
  }

  const handleJumpPage = () => { /* ... */ }

  // 筛选和分页逻辑（简化版，避免一次性加载过多数据）
  const uniqueShops = Array.from(new Set(products.map(p => p?.shopName || '').filter(name => name && name.trim()))).sort()

  // 简化分页：直接使用当前页的产品数据，不再进行复杂的内存筛选
  // 这样可以显著提升加载速度，但暂时不支持跨页搜索
  const currentProducts = products.filter(p => {
    // 只有在没有搜索条件时才显示当前页数据
    if (!keywordSearch && !shopFilter) {
      return true
    }

    // 有搜索条件时，对当前加载的数据进行筛选
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

  // 计算总页数（基于总数）
  const totalPages = Math.ceil(totalProducts / itemsPerPage)

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
                            {!isShopScraping ? (
                              <Button onClick={handleScrapeShop} disabled={!selectedShopId} className="w-full">
                                抓取店铺
                              </Button>
                            ) : (
                              <Button
                                variant="destructive"
                                size="sm"
                                onClick={() => handleScrapeControl('stop')}
                                className="w-full"
                              >
                                <StopCircle className="w-4 h-4 mr-2" />
                                取消抓取
                              </Button>
                            )}

                            {/* Shop Scrape Status - 显示在抓取过程中的状态信息 */}
                            {isShopScraping && scrapeStatus && (
                              <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                                <div className="flex items-center gap-2 mb-2">
                                  <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
                                  <span className="text-sm font-medium text-amber-800">
                                    {scrapeStatus.message || '正在处理中...'}
                                  </span>
                                </div>
                                <div className="grid grid-cols-2 gap-2 text-xs">
                                  <div className="text-center">
                                    <div className="font-semibold text-green-700">{scrapeStatus.success || 0}</div>
                                    <div className="text-muted-foreground">成功</div>
                                  </div>
                                  <div className="text-center">
                                    <div className="font-semibold text-red-600">{(scrapeStatus.processed || 0) - (scrapeStatus.success || 0)}</div>
                                    <div className="text-muted-foreground">剩余</div>
                                  </div>
                                </div>
                              </div>
                            )}
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

      {/* Progress Bar - 批量抓取进度 */}
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
                          商品库{isShopScraping ? ' - 抓取中...' : ''}
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
                            <Button variant={selectedProducts.length===currentProducts.length && currentProducts.length>0?"secondary":"outline"} size="sm" onClick={handleSelectAll}>
                                {selectedProducts.length===currentProducts.length && currentProducts.length>0 ? <CheckSquare className="mr-2 h-4 w-4"/> : <Square className="mr-2 h-4 w-4"/>} 全选 ({currentProducts.length})
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
                                                                        method: 'DELETE'
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

                          {/* 自定义回复设置 - 当自动回复规则关闭时显示 */}
                          {/* 自定义回复设置 - 当自动回复规则关闭时显示 */}
                          {!editingProduct?.ruleEnabled && (
                            <div className="space-y-4 p-4 border rounded-lg bg-blue-50/30">
                              <div className="space-y-2">
                                <Label className="text-sm font-medium">自定义回复消息</Label>
                                <Textarea
                                  value={editingProduct?.customReplyText || ""}
                                  onChange={(e) => setEditingProduct({...editingProduct, customReplyText: e.target.value})}
                                  placeholder="输入自定义回复消息内容..."
                                  rows={3}
                                />
                                <p className="text-xs text-muted-foreground">如果留空，将只发送选中的图片</p>
                              </div>

                              <div className="space-y-3">
                                <div className="flex justify-between items-center">
                                  <Label className="text-sm font-medium">附带图片回复</Label>
                                  <div className="flex gap-2">
                                    {/* 隐藏的文件输入框 */}
                                    <input
                                      type="file"
                                      multiple
                                      accept="image/*"
                                      className="hidden"
                                      id="edit-upload-input"
                                      onChange={(e) => {
                                        const files = Array.from(e.target.files || []);
                                        if (files.length > 0) {
                                          setEditingProduct({
                                            ...editingProduct,
                                            uploadedImages: files,
                                            selectedImageIndexes: [], // 清空现有图片勾选
                                            customImageUrls: [], // 清空图片链接
                                            imageSource: 'upload' // 设置为上传模式
                                          });
                                        }
                                      }}
                                    />
                                    <Label
                                      htmlFor="edit-upload-input"
                                      className="cursor-pointer text-xs bg-white border px-2 py-1 rounded hover:bg-gray-50 flex items-center"
                                    >
                                      <Upload className="w-3 h-3 mr-1"/> 上传本地图片
                                    </Label>
                                  </div>
                                </div>

                                {/* 选择现有商品图片 */}
                                {(!editingProduct?.imageSource || editingProduct?.imageSource === 'product') && (
                                  <div className="space-y-2">
                                    <Label className="text-xs text-muted-foreground">勾选现有商品图片</Label>
                                    <div className="grid grid-cols-3 md:grid-cols-4 gap-3 max-h-60 overflow-y-auto p-2 border rounded-md bg-white">
                                      {editingProduct?.images?.map((image: string, index: number) => (
                                        <div
                                          key={`prod-${index}`}
                                          className={`relative aspect-square rounded-md overflow-hidden cursor-pointer border-2 transition-all ${
                                            editingProduct?.selectedImageIndexes?.includes(index)
                                              ? 'border-blue-500 ring-2 ring-blue-200'
                                              : 'border-transparent hover:border-gray-200'
                                          }`}
                                          onClick={() => {
                                            const selectedIndexes = editingProduct?.selectedImageIndexes || [];
                                            const newIndexes = selectedIndexes.includes(index)
                                              ? selectedIndexes.filter((i: number) => i !== index)
                                              : [...selectedIndexes, index];
                                            setEditingProduct({
                                              ...editingProduct,
                                              selectedImageIndexes: newIndexes,
                                              imageSource: 'product'
                                            });
                                          }}
                                        >
                                          <img
                                            src={image}
                                            alt={`图片 ${index + 1}`}
                                            className="w-full h-full object-cover"
                                          />
                                          {editingProduct?.selectedImageIndexes?.includes(index) && (
                                            <div className="absolute top-1 right-1 bg-blue-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs shadow-sm">
                                              ✓
                                            </div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                      已选 {editingProduct?.selectedImageIndexes?.length || 0} 张现有图片
                                    </p>
                                  </div>
                                )}

                                {/* 显示上传的本地图片 */}
                                {editingProduct?.imageSource === 'upload' && editingProduct?.uploadedImages?.length > 0 && (
                                  <div className="space-y-2">
                                    <div className="flex justify-between items-center">
                                      <Label className="text-xs text-muted-foreground">已上传的本地图片</Label>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-6 text-xs"
                                        onClick={() => {
                                          setEditingProduct({
                                            ...editingProduct,
                                            uploadedImages: [],
                                            imageSource: 'product'
                                          });
                                        }}
                                      >
                                        清除
                                      </Button>
                                    </div>
                                    <div className="grid grid-cols-3 md:grid-cols-4 gap-3 p-2 border rounded-md bg-white">
                                      {editingProduct.uploadedImages.map((file: File, index: number) => (
                                        <div key={`upload-${index}`} className="relative aspect-square rounded-md overflow-hidden border-2 border-green-500">
                                          <img
                                            src={URL.createObjectURL(file)}
                                            alt="上传图片"
                                            className="w-full h-full object-cover"
                                          />
                                          <div className="absolute top-1 right-1 bg-green-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs">
                                            ✓
                                          </div>
                                          <button
                                            type="button"
                                            className="absolute bottom-1 right-1 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              const newUploads = editingProduct.uploadedImages.filter((_: any, i: number) => i !== index);
                                              setEditingProduct({
                                                ...editingProduct,
                                                uploadedImages: newUploads,
                                                imageSource: newUploads.length > 0 ? 'upload' : 'product'
                                              });
                                            }}
                                          >
                                            <X className="w-3 h-3"/>
                                          </button>
                                        </div>
                                      ))}
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                      共 {editingProduct.uploadedImages.length} 张上传图片（只使用这些图片回复）
                                    </p>
                                  </div>
                                )}

                                {/* 填写图片链接 */}
                                <div className="space-y-2">
                                  <Label className="text-xs text-muted-foreground">或填写图片链接（每行一个）</Label>
                                  <Textarea
                                    value={Array.isArray(editingProduct?.customImageUrls) ? editingProduct.customImageUrls.join('\n') : (editingProduct?.customImageUrls || "")}
                                    onChange={(e) => {
                                      const urls = e.target.value.split('\n').filter(url => url.trim());
                                      setEditingProduct({
                                        ...editingProduct,
                                        customImageUrls: urls,
                                        imageSource: urls.length > 0 ? 'custom' : 'product',
                                        selectedImageIndexes: urls.length > 0 ? [] : editingProduct?.selectedImageIndexes,
                                        uploadedImages: urls.length > 0 ? [] : editingProduct?.uploadedImages
                                      });
                                    }}
                                    placeholder="https://example.com/image1.jpg&#10;https://example.com/image2.jpg"
                                    rows={3}
                                    className="text-xs"
                                  />
                                  <p className="text-xs text-muted-foreground">
                                    {Array.isArray(editingProduct?.customImageUrls) && editingProduct.customImageUrls.length > 0
                                      ? `已填写 ${editingProduct.customImageUrls.length} 个图片链接`
                                      : '填写后将只使用这些链接的图片回复'}
                                  </p>
                                </div>
                              </div>
                            </div>
                          )}
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
                {currentProducts.length > 0 && (
                    <div className="flex flex-col sm:flex-row justify-between items-center gap-4 p-6 border-t bg-muted/5">
              <div className="text-sm text-muted-foreground font-medium">
                            显示第 {(currentPage-1)*itemsPerPage + 1} - {Math.min(currentPage*itemsPerPage, currentProducts.length)} 条，共 {currentProducts.length} 条记录
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