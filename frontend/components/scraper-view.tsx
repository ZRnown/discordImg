"use client"

import { useState, useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { useApiCache } from "@/hooks/use-api-cache"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Copy, ChevronLeft, ChevronRight, Trash2, ImageIcon, Edit, X, Download, Loader2, List, Upload, Store, CheckSquare, Square, Search, Pause, Play, StopCircle, AlertCircle } from "lucide-react"
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
import {
  cloneWebsiteReplySetting,
  createInitialWebsiteReplySetting,
  ensurePerWebsiteReplySettings,
  getScopedWebsites,
  getWebsiteReplySetting,
  normalizeImageSource,
  normalizePerWebsiteReplySettings,
  normalizeWebsiteReplySetting,
  parseReplyScopes,
  type WebsiteReplySetting,
} from "@/lib/product-reply-settings"

type FailedDetail = {
  index: number
  url?: string
  reason: string
}

type FailedItem = {
  id: string
  reason: string
  details?: FailedDetail[]
}

function ImageLightbox({
  images,
  initialIndex,
  onClose
}: {
  images: string[]
  initialIndex: number
  onClose: () => void
}) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') {
        setCurrentIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1))
      }
      if (e.key === 'ArrowRight') {
        setCurrentIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [images.length, onClose])

  if (!images.length) {
    return null
  }

  if (typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/90 backdrop-blur-sm"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 text-white/70 hover:text-white p-2"
      >
        <X className="size-8" />
      </button>
      <div className="relative w-full h-full flex items-center justify-center p-4">
        <img
          src={images[currentIndex]}
          alt={`Preview ${currentIndex + 1}`}
          className="max-h-[90vh] max-w-[90vw] object-contain rounded-md shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        />
        {images.length > 1 && (
          <>
            <button
              onClick={(e) => {
                e.stopPropagation()
                setCurrentIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1))
              }}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-3 bg-black/50 text-white rounded-full hover:bg-white/20 transition-colors"
            >
              <ChevronLeft className="size-8" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                setCurrentIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0))
              }}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-3 bg-black/50 text-white rounded-full hover:bg-white/20 transition-colors"
            >
              <ChevronRight className="size-8" />
            </button>
          </>
        )}
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/60 text-white px-4 py-1 rounded-full text-sm font-mono">
          {currentIndex + 1} / {images.length}
        </div>
      </div>
    </div>,
    document.body
  )
}

export function ScraperView({ currentUser, isActive = true }: { currentUser: any; isActive?: boolean }) {
  const [batchIds, setBatchIds] = useState('')
  const [isBatchScraping, setIsBatchScraping] = useState(false)
  const [batchProgress, setBatchProgress] = useState(0)
  const [batchFailedItems, setBatchFailedItems] = useState<FailedItem[]>([])
  const [shopFailedItems, setShopFailedItems] = useState<FailedItem[]>([])
  const [dismissedShopFailedKey, setDismissedShopFailedKey] = useState<string | null>(null)
  const [dialogFailedItems, setDialogFailedItems] = useState<FailedItem[]>([])
  const [failedDialogTitle, setFailedDialogTitle] = useState('失败商品详情')
  const [showFailedDialog, setShowFailedDialog] = useState(false)
  const [products, setProducts] = useState<any[]>([])
  const [totalProducts, setTotalProducts] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [jumpPage, setJumpPage] = useState("")
  const [itemsPerPage, setItemsPerPage] = useState(50)
  const [editingProduct, setEditingProduct] = useState<any>(null)
  const [selectedProducts, setSelectedProducts] = useState<number[]>([])
  const [selectAllAcrossPages, setSelectAllAcrossPages] = useState(false)
  const [indexedIds, setIndexedIds] = useState<string[]>([])
  const [shopFilter, setShopFilter] = useState('__ALL__')
  const [keywordSearch, setKeywordSearch] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deletingProductId, setDeletingProductId] = useState<number | null>(null)
  // 图片上传 ref
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const productsFetchSeqRef = useRef(0)
  const [isUploadingImg, setIsUploadingImg] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null)
  const [batchUploading, setBatchUploading] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [lightboxImages, setLightboxImages] = useState<string[]>([])
  const [lightboxIndex, setLightboxIndex] = useState(0)
  const [openGalleryId, setOpenGalleryId] = useState<number | null>(null)

  // 使用API缓存hook
  const { cachedFetch, invalidateCache } = useApiCache()

  // 抓取相关状态
  const [shopId, setShopId] = useState('')
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [shopScrapeProgress, setShopScrapeProgress] = useState(0)
  const [scrapeStatus, setScrapeStatus] = useState<any>(null)
  const [availableShops, setAvailableShops] = useState<any[]>([])
  const [availableWebsites, setAvailableWebsites] = useState<any[]>([])
  const [selectedShopId, setSelectedShopId] = useState('')
  const [totalProductsCount, setTotalProductsCount] = useState(0)
  // 搜索类型状态
  const [searchType, setSearchType] = useState<'all' | 'id' | 'keyword' | 'chinese'>('all')
  const isStopping = Boolean(scrapeStatus?.stop_signal && !scrapeStatus?.completed)

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

  const getLinkGridClass = (count: number) => {
    if (count <= 1) return "grid grid-cols-1 gap-2 flex-1 min-w-0"
    if (count === 2) return "grid grid-cols-2 gap-2 flex-1 min-w-0"
    if (count === 3) return "grid grid-cols-3 gap-2 flex-1 min-w-0"
    return "grid grid-cols-4 gap-2 flex-1 min-w-0"
  }

  // 优化：分离不同类型的加载逻辑
  useEffect(() => {
    if (!isActive) return
    fetchIndexedIds()
    fetchAvailableShops()
    fetchWebsites()
    fetchProductsCount()
    fetchScrapeStatus() // 初始化时检查抓取状态，恢复进度显示
  }, [isActive]) // 静态数据只在当前页激活时加载

  // 监听店铺更新事件，实时刷新店铺列表
  useEffect(() => {
    if (!isActive) return
    const handleShopsUpdated = () => {
      // 清除店铺缓存并重新获取
      invalidateCache('/api/shops')
      fetchAvailableShops()
    }
    window.addEventListener('shops-updated', handleShopsUpdated)
    return () => window.removeEventListener('shops-updated', handleShopsUpdated)
  }, [invalidateCache, isActive])

  useEffect(() => {
    if (!isActive) return
    fetchProducts(currentPage)
  }, [currentPage, itemsPerPage, keywordSearch, shopFilter, searchType, isActive]) // 只在相关参数改变时重新加载商品

  useEffect(() => {
    // 当搜索条件改变时，重置到第一页
    if (keywordSearch || shopFilter) {
      setCurrentPage(1)
    }
  }, [keywordSearch, shopFilter, searchType])

  useEffect(() => {
    setSelectAllAcrossPages(false)
    setSelectedProducts([])
  }, [keywordSearch, shopFilter, searchType])

  useEffect(() => {
    if (!selectAllAcrossPages) return
    setSelectedProducts(products.map(p => p.id))
  }, [selectAllAcrossPages, products])

  // 优化轮询机制：使用智能轮询，避免重复请求
  useEffect(() => {
    if (!isActive) return
    let statusInterval: NodeJS.Timeout | null = null

    // 如果没有抓取任务，减少轮询频率到60秒一次
    const shouldPollFast = isShopScraping || isBatchScraping || isStopping

    if (!shouldPollFast) {
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
    if (shouldPollFast) {
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
  }, [isShopScraping, isBatchScraping, isStopping, currentPage, itemsPerPage, keywordSearch, shopFilter, searchType, isActive])

  const fetchProducts = async (page: number = currentPage) => {
    const fetchSeq = ++productsFetchSeqRef.current
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(itemsPerPage)
      })
      if (keywordSearch.trim()) {
        params.set('keyword', keywordSearch.trim())
        params.set('search_type', searchType)
      }
      if (shopFilter && shopFilter !== "__ALL__") {
        params.set('shop_name', shopFilter)
      }

      const res = await fetch(`/api/products?${params.toString()}`)
      const data = await res.json()
      if (fetchSeq !== productsFetchSeqRef.current) return

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
        replyScope: product.replyScope || product.reply_scope || 'all',
        customReplyImages: product.customReplyImages || product.custom_reply_images || [],
        selectedImageIndexes: product.selectedImageIndexes || [],
        customImageUrls: product.customImageUrls || product.custom_image_urls || [],
        imageSource: product.imageSource || product.image_source || (product.custom_image_urls ? 'custom' : 'upload'),
        perWebsiteReplySettings: product.perWebsiteReplySettings || product.per_website_reply_settings || {},
        uploadedImages: [],
        existingUploadedImageUrls: product.uploadedImages || []
      }))

      setProducts(processedProducts)
      setSelectedProducts([])
      setTotalProducts(data.total || 0)
    } catch (e) {
      if (fetchSeq !== productsFetchSeqRef.current) return
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

  const fetchWebsites = async () => {
    try {
      const data = await cachedFetch('/api/websites', { credentials: 'include' })
      setAvailableWebsites(data.websites || [])
    } catch (e) {
      console.error('获取网站列表失败:', e)
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
          if (status.is_scraping) {
            setShopFailedItems([])
          } else if (status.completed) {
            const rawFailedItems = Array.isArray(status.failed_items) ? status.failed_items : []
            const formatted = rawFailedItems
              .map((item: any) => ({
                id: String(item?.id || item?.item_id || ''),
                reason: item?.reason || item?.message || '未知错误',
                details: Array.isArray(item?.details)
                  ? item.details
                  : Array.isArray(item?.failed_details)
                    ? item.failed_details
                    : []
              }))
              .filter((item: any) => item.id)
            const failedKey = `${status.updated_at || ''}:${formatted.map((item: FailedItem) => item.id).join(',')}`
            if (formatted.length > 0 && failedKey !== dismissedShopFailedKey) {
              setDismissedShopFailedKey(null)
            }
            setShopFailedItems(formatted)
          }
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

  const currentShopFailedKey = scrapeStatus?.completed && !scrapeStatus?.is_scraping
    ? `${scrapeStatus?.updated_at || ''}:${shopFailedItems.map(item => item.id).join(',')}`
    : ''

  const updateWebsiteReplySetting = (
    websiteId: string | number,
    updater: (current: WebsiteReplySetting) => WebsiteReplySetting
  ) => {
    if (!editingProduct) return
    const key = String(websiteId)
    const currentSettings = {
      ...ensurePerWebsiteReplySettings(editingProduct),
    }
    const currentSetting = currentSettings[key]
      ? cloneWebsiteReplySetting(currentSettings[key])
      : getWebsiteReplySetting(editingProduct, key, availableWebsites)

    currentSettings[key] = normalizeWebsiteReplySetting(updater(currentSetting))
    setEditingProduct({
      ...editingProduct,
      perWebsiteReplySettings: currentSettings,
    })
  }

  const serializePerWebsiteReplySettings = (product: any) => {
    const normalized = normalizePerWebsiteReplySettings(product?.perWebsiteReplySettings)
    return Object.fromEntries(
      Object.entries(normalized).map(([websiteId, setting]) => [
        websiteId,
        {
          customReplyText: setting.customReplyText || '',
          imageSource: normalizeImageSource(setting.imageSource),
          selectedImageIndexes: [...(setting.selectedImageIndexes || [])],
          customImageUrls: [...(setting.customImageUrls || [])],
          existingUploadedImageUrls: [...(setting.existingUploadedImageUrls || [])],
        },
      ])
    )
  }

  const handleScopeChange = (websiteName: string, checked: boolean) => {
    if (!editingProduct) return
    let currentScopes = parseReplyScopes(editingProduct.replyScope)
    currentScopes = currentScopes.filter(scope => scope && scope !== 'all')

    if (checked) {
      if (!currentScopes.includes(websiteName)) {
        currentScopes.push(websiteName)
      }
    } else {
      currentScopes = currentScopes.filter(scope => scope !== websiteName)
    }

    const nextSettings = {
      ...ensurePerWebsiteReplySettings(editingProduct),
    }
    const website = availableWebsites.find(site => site.name === websiteName)
    if (checked && website && !nextSettings[String(website.id)]) {
      nextSettings[String(website.id)] = createInitialWebsiteReplySetting(editingProduct, {
        useLegacyFallback: true,
      })
    }

    setEditingProduct({
      ...editingProduct,
      replyScope: JSON.stringify(currentScopes),
      perWebsiteReplySettings: nextSettings,
    })
  }

  const isScopeSelected = (websiteName: string) => {
    if (!editingProduct || editingProduct.replyScope === 'all') return false
    const scopes = parseReplyScopes(editingProduct.replyScope)
    return scopes.includes(websiteName)
  }

  // === 链接生成逻辑 ===

  const getProductLinks = (product: any) => {
    const dynamicLinks = Array.isArray(product.websiteUrls) ? product.websiteUrls : []
    const weidianId = product.weidianId || getWeidianIdFromUrl(product.weidianUrl || product.product_url)
    const mergedLinks = mergeWebsiteLinks(dynamicLinks, weidianId)
    if (mergedLinks.length > 0) {
      return mergedLinks
    }

    return [
      { name: 'weidian', display_name: '微店', url: product.weidianUrl, badge_color: resolveBadgeColor('gray') },
      { name: 'cnfans', display_name: 'CNFans', url: product.cnfansUrl, badge_color: resolveBadgeColor('blue') },
      { name: 'acbuy', display_name: 'AcBuy', url: product.acbuyUrl, badge_color: resolveBadgeColor('orange') }
    ].filter(link => link.url && link.url.trim() !== '')
  }

  // ... (保留 handleBatchDelete, confirmBatchDelete, handleUploadImage, handleBatchUploadImages) ...

  const handleBatchDelete = async () => {
    const selectedCount = selectAllAcrossPages ? totalProducts : selectedProducts.length
    console.log('批量删除按钮被点击，选中商品数量:', selectedCount)
    if (selectedCount === 0) {
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
      let res: Response
      if (selectAllAcrossPages) {
        const params = new URLSearchParams()
        if (keywordSearch.trim()) params.set('keyword', keywordSearch.trim())
        params.set('search_type', searchType)
        if (shopFilter && shopFilter !== '__ALL__') params.set('shop_name', shopFilter)
        const query = params.toString()
        res = await fetch(`/api/products/batch-delete-all${query ? `?${query}` : ''}`, {
          method: 'DELETE',
          credentials: 'include'
        })
      } else {
        res = await fetch(`/api/products/batch`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ ids: selectedProducts })
        })
      }

      if (res.ok) {
        toast.success("批量删除成功")
        setSelectedProducts([])
        setSelectAllAcrossPages(false)
        if (selectAllAcrossPages) setCurrentPage(1)
        fetchProducts()
        fetchProductsCount()
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
    if (selectAllAcrossPages) {
      setSelectAllAcrossPages(false)
      setSelectedProducts([])
      return
    }
    if (totalProducts === 0) return
    setSelectAllAcrossPages(true)
    setSelectedProducts(currentProducts.map(p => p.id))
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
      let res

      const hasNewUploads = updatedProduct.uploadedImages && updatedProduct.uploadedImages.length > 0
      const hasExistingUploads = updatedProduct.existingUploadedImageUrls && updatedProduct.existingUploadedImageUrls.length > 0
      const perWebsiteReplySettings = normalizePerWebsiteReplySettings(updatedProduct.perWebsiteReplySettings)
      const serializedPerWebsiteReplySettings = serializePerWebsiteReplySettings({
        perWebsiteReplySettings,
      })
      const hasPerWebsiteNewUploads = Object.values(perWebsiteReplySettings).some(
        (setting: any) => Array.isArray(setting.uploadedImages) && setting.uploadedImages.length > 0
      )
      const hasPerWebsiteExistingUploads = Object.values(perWebsiteReplySettings).some(
        (setting: any) => Array.isArray(setting.existingUploadedImageUrls) && setting.existingUploadedImageUrls.length > 0
      )

      if (hasNewUploads || hasExistingUploads || hasPerWebsiteNewUploads || hasPerWebsiteExistingUploads) {
        const formData = new FormData()

        formData.append('id', updatedProduct.id.toString())
        if (updatedProduct.title) formData.append('title', updatedProduct.title)
        if (updatedProduct.englishTitle) formData.append('englishTitle', updatedProduct.englishTitle)
        if (updatedProduct.ruleEnabled !== undefined) formData.append('ruleEnabled', updatedProduct.ruleEnabled.toString())
        if (updatedProduct.customReplyText) formData.append('customReplyText', updatedProduct.customReplyText)
        if (updatedProduct.imageSource) formData.append('imageSource', updatedProduct.imageSource)
        if (updatedProduct.replyScope) formData.append('replyScope', updatedProduct.replyScope)
        formData.append('perWebsiteReplySettings', JSON.stringify(serializedPerWebsiteReplySettings))

        if (updatedProduct.selectedImageIndexes) {
          formData.append('selectedImageIndexes', JSON.stringify(updatedProduct.selectedImageIndexes))
        }
        if (updatedProduct.customImageUrls) {
          formData.append('customImageUrls', JSON.stringify(updatedProduct.customImageUrls))
        }

        if (hasExistingUploads) {
          formData.append('existingUploadedImageUrls', JSON.stringify(updatedProduct.existingUploadedImageUrls))
        }

        if (hasNewUploads) {
          updatedProduct.uploadedImages.forEach((file: File) => {
            formData.append('uploadedImages', file)
          })
        }

        Object.entries(perWebsiteReplySettings).forEach(([websiteId, setting]: [string, any]) => {
          if (Array.isArray(setting.uploadedImages) && setting.uploadedImages.length > 0) {
            setting.uploadedImages.forEach((file: File) => {
              formData.append(`perWebsiteUploadedImages:${websiteId}`, file)
            })
          }
        })

        res = await fetch('/api/products', {
          method: 'PUT',
          credentials: 'include',
          body: formData,
        })
      } else {
        res = await fetch('/api/products', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            ...updatedProduct,
            perWebsiteReplySettings: serializedPerWebsiteReplySettings,
          })
        });
      }

      if (res.ok) {
        const data = await res.json()

        // 转换后端返回的数据格式，将 uploadedImages (URL数组) 转换为 existingUploadedImageUrls
        const transformedProduct = {
          ...data.product,
          uploadedImages: [], // 新上传的File对象（清空）
          existingUploadedImageUrls: data.product.uploadedImages || [], // 已保存的图片URL
          perWebsiteReplySettings: normalizePerWebsiteReplySettings(data.product.perWebsiteReplySettings),
        }

        setProducts(products.map(p => p.id === data.product.id ? transformedProduct : p))
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
    setShopFailedItems([])
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

  const startBatchScrape = async (ids: string[]) => {
    if (ids.length === 0) {
      toast.error("请输入有效的商品ID")
      return
    }
    if (isBatchScraping) {
      return
    }

    console.log('开始批量上传，商品数量:', ids.length)
    setIsBatchScraping(true)
    setBatchProgress(0)
    setBatchFailedItems([])
    setDialogFailedItems([])
    setShowFailedDialog(false)

    try {
      console.log(`发送批量请求到 /api/scrape/batch，商品数量: ${ids.length}`)

      const res = await fetch('/api/scrape/batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ productIds: ids }),
        signal: AbortSignal.timeout(300000)
      })

      console.log(`收到批量响应，状态码: ${res.status}`)

      if(res.ok) {
        const result = await res.json()
        console.log('批量处理结果:', result)

        const results = result.results || {}
        const details = result.details || []
        const successCount = results.success || 0
        const skipCount = results.skipped || 0
        const cancelledCount = results.cancelled || 0
        const partialCount = results.partial || 0
        const errorCount = results.errors || 0

        let messageParts = []
        if (successCount > 0) messageParts.push(`成功 ${successCount}`)
        if (skipCount > 0) messageParts.push(`跳过 ${skipCount}`)
        if (cancelledCount > 0) messageParts.push(`取消 ${cancelledCount}`)
        if (partialCount > 0) messageParts.push(`部分完成 ${partialCount}`)
        if (errorCount > 0) messageParts.push(`失败 ${errorCount}`)

        const message = messageParts.length > 0 ? messageParts.join(', ') : '无结果'

        toast.success(`批量上传完成: ${message}`)
        console.log('批量上传完成')

        if (results.duration) {
          console.log(`处理时间: ${results.duration.toFixed(2)} 秒`)
        }

        if (details.length > 0) {
          const failures = details
            .filter((item: any) => item.status === 'failed' || item.status === 'error')
            .map((item: any) => ({
              id: String(item.id),
              reason: item.message || '未知错误',
              details: Array.isArray(item.failed_details)
                ? item.failed_details
                : Array.isArray(item.failedDetails)
                  ? item.failedDetails
                  : []
            }))
          setBatchFailedItems(failures)
        }
      } else {
        const errorText = await res.text()
        console.error('批量上传失败:', res.status, errorText)
        toast.error(`批量上传失败: ${errorText}`)
      }

      setBatchProgress(100)
      fetchProducts()
      fetchProductsCount()
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

  const handleBatchScrape = async () => {
    const ids = batchIds.split('\n').map(id => id.trim()).filter(id => id && id.match(/^\d+$/))
    if (ids.length === 0) {
      toast.error("请输入有效的商品ID")
      return
    }
    await startBatchScrape(ids)
  }

  const handleJumpPage = () => { /* ... */ }

  const openLightbox = (images: string[], index: number) => {
    if (!images || images.length === 0) return
    setLightboxImages(images)
    setLightboxIndex(index)
    setLightboxOpen(true)
  }

  // 筛选和分页逻辑：纯服务端分页，前端不再二次过滤
  const uniqueShops = Array.from(
    new Set(availableShops.map((shop) => shop?.name || '').filter((name) => name && name.trim()))
  ).sort()
  const currentProducts = products
  const selectedCount = selectAllAcrossPages ? totalProducts : selectedProducts.length
  const isAllOnPageSelected = currentProducts.length > 0 && currentProducts.every(p => selectedProducts.includes(p.id))
  const isAllSelected = (selectAllAcrossPages && totalProducts > 0) || isAllOnPageSelected

  // 计算总页数（基于总数，至少为1）
  const totalPages = Math.max(1, Math.ceil(totalProducts / itemsPerPage))
  const hasNextPage = totalProducts > 0 ? currentPage < totalPages : currentProducts.length === itemsPerPage

  return (
    <div className="space-y-8 overflow-x-hidden" data-tutorial="scraper-main">
      {lightboxOpen && (
        <ImageLightbox
          images={lightboxImages}
          initialIndex={lightboxIndex}
          onClose={() => setLightboxOpen(false)}
        />
      )}
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
                                <div className="grid grid-cols-1 gap-2 text-xs">
                                  <div className="text-center">
                                    <div className="font-semibold text-green-700">{scrapeStatus.success || 0}</div>
                                    <div className="text-muted-foreground">成功</div>
                                  </div>
                                </div>
                                {((scrapeStatus.failed || 0) > 0 ||
                                  (scrapeStatus.image_failed || 0) > 0 ||
                                  (scrapeStatus.index_failed || 0) > 0) && (
                                  <div className="mt-2 text-[11px] text-muted-foreground flex items-center justify-between">
                                    <span>失败: {scrapeStatus.failed || 0}</span>
                                    <span>图片失败: {scrapeStatus.image_failed || 0}</span>
                                    <span>索引失败: {scrapeStatus.index_failed || 0}</span>
                                  </div>
                                )}
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

      {batchFailedItems.length > 0 && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between">
          <div className="flex items-center text-red-700">
            <AlertCircle className="w-5 h-5 mr-2" />
            <span>批量上传失败 {batchFailedItems.length} 个商品</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="border-red-200 text-red-700 hover:bg-red-100"
            onClick={() => {
              setDialogFailedItems(batchFailedItems)
              setFailedDialogTitle('批量上传失败商品详情')
              setShowFailedDialog(true)
            }}
          >
            查看详情
          </Button>
        </div>
      )}

      {shopFailedItems.length > 0 && scrapeStatus?.completed && !scrapeStatus?.is_scraping && dismissedShopFailedKey !== currentShopFailedKey && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between gap-3">
          <div className="flex items-center text-red-700">
            <AlertCircle className="w-5 h-5 mr-2" />
            <span>店铺抓取失败 {shopFailedItems.length} 个商品</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="border-red-200 text-red-700 hover:bg-red-100"
              onClick={() => {
                setDialogFailedItems(shopFailedItems)
                setFailedDialogTitle('店铺抓取失败商品详情')
                setShowFailedDialog(true)
              }}
            >
              查看详情
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-red-700 hover:bg-red-100 hover:text-red-800"
              onClick={() => setDismissedShopFailedKey(currentShopFailedKey)}
              aria-label="关闭店铺抓取失败提示"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}


      {/* Product List */}
      <div className="space-y-4">
        <Card className="shadow-sm overflow-x-hidden">
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
                            <Button variant={isAllSelected ? "secondary" : "outline"} size="sm" onClick={handleSelectAll}>
                                {isAllSelected ? <CheckSquare className="mr-2 h-4 w-4"/> : <Square className="mr-2 h-4 w-4"/>} 全选 (全部 {totalProducts})
            </Button>
                            {selectedCount > 0 && (
                                <Button variant="destructive" size="sm" onClick={handleBatchDelete} disabled={isDeleting}>
                                    <Trash2 className="mr-2 h-4 w-4" /> 删除 ({selectedCount})
                                </Button>
                            )}
          </div>
              </div>
            </div>
            </CardHeader>
            <CardContent className="p-0">
                {/* 列表 */}
          <div className="divide-y overflow-x-hidden">
                    {currentProducts.map((product) => {
                        const links = getProductLinks(product);
                        const displayedLinks = links.slice(0, 12)
                        return (
              <div key={product.id} className="flex flex-col lg:flex-row lg:items-center justify-between p-2 hover:bg-muted/20 transition-colors gap-3 min-w-0">
                <div className="flex gap-3 items-center">
                                <Checkbox checked={selectAllAcrossPages || selectedProducts.includes(product.id)} onCheckedChange={(checked)=>{
                                    if (!checked && selectAllAcrossPages) {
                                      setSelectAllAcrossPages(false)
                                    }
                                    if (checked) {
                                      setSelectedProducts(Array.from(new Set([...selectedProducts, product.id])))
                                    } else {
                                      setSelectedProducts(selectedProducts.filter(id=>id!==product.id))
                                    }
                                }}/>
                </div>

                            {/* 图片与基本信息 */}
                <div className="flex gap-3 items-center flex-1">
                                {/* 图片弹窗 (保持原逻辑) */}
                  <Dialog
                    modal={false}
                    open={openGalleryId === product.id}
                    onOpenChange={(open) => {
                      if (open) {
                        setOpenGalleryId(product.id)
                        return
                      }
                      if (!lightboxOpen) {
                        setOpenGalleryId(null)
                      }
                    }}
                  >
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
                              <img
                                src={img}
                                alt={`Img ${idx}`}
                                className="object-cover w-full h-full transition-transform group-hover:scale-110 cursor-zoom-in"
                                onClick={() => openLightbox(product.images || [], idx)}
                              />
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
                                        <h4 className="font-bold text-base truncate max-w-[200px] sm:max-w-[400px]">{product.title}</h4>
                                        {/* 已删除这里原本的小编辑按钮 */}
                                        {indexedIds.includes(product.weidianId) && <Badge className="bg-blue-600 text-[10px] h-4 px-2">已索引</Badge>}
                                        {product.ruleEnabled && <Badge className="bg-purple-600 text-[10px] h-4 px-2">规则启用</Badge>}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                                        <p className="text-sm font-bold text-blue-600 truncate max-w-[240px] sm:max-w-[500px]">{product.englishTitle || "No English Title"}</p>
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
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  <div className={getLinkGridClass(displayedLinks.length)}>
                    {displayedLinks.map((link) => (
                      <div
                        key={link.name || link.url}
                        className="flex items-center gap-1 min-w-0 bg-muted/40 p-1 rounded border border-transparent hover:border-border transition-colors"
                      >
                        <Badge
                          className="text-[9px] px-1.5 py-0.5 h-5 border-none justify-center shrink-0 text-white font-normal w-14"
                          style={{ backgroundColor: link.badge_color || '#6b7280' }}
                        >
                          {link.display_name}
                        </Badge>
                        <div className="flex-1 min-w-0 flex items-center justify-between">
                          <a
                            href={link.url}
                            target="_blank"
                            className="text-[10px] truncate hover:underline text-foreground/80 px-1"
                            title={link.url}
                          >
                            {link.url}
                          </a>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 shrink-0 opacity-50 hover:opacity-100"
                            onClick={(event) => {
                              event.preventDefault()
                              event.stopPropagation()
                              copyToClipboard(link.url)
                            }}
                          >
                            <Copy className="h-3 w-3"/>
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                                {/* 操作按钮组 */}
                                <div className="flex items-center gap-1 ml-auto shrink-0">
                                    {/* 编辑按钮 */}
                                    <Dialog open={editingProduct?.id === product.id} onOpenChange={(open)=>!open && setEditingProduct(null)}>
                      <DialogTrigger asChild>
                                            <Button
                                              variant="outline"
                                              size="icon"
                                              className="h-8 w-8"
                                              onClick={() => setEditingProduct({
                                                ...product,
                                                perWebsiteReplySettings: ensurePerWebsiteReplySettings(product),
                                              })}
                                            >
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
                                <Label className="text-sm font-medium">应用范围 (多选)</Label>
                                <div className="border rounded-md p-3 space-y-2 max-h-40 overflow-y-auto bg-white">
                                  <div className="flex items-center space-x-2">
                                    <Checkbox
                                      id="scope-all"
                                      checked={editingProduct?.replyScope === 'all'}
                                      onCheckedChange={(checked) => {
                                        if (!editingProduct) return
                                        if (checked === true) {
                                          const currentSettings = {
                                            ...ensurePerWebsiteReplySettings(editingProduct),
                                          }
                                          availableWebsites.forEach(site => {
                                            if (!currentSettings[String(site.id)]) {
                                              currentSettings[String(site.id)] = createInitialWebsiteReplySetting(editingProduct)
                                            }
                                          })
                                          setEditingProduct({
                                            ...editingProduct,
                                            replyScope: 'all',
                                            perWebsiteReplySettings: currentSettings,
                                          })
                                        } else {
                                          setEditingProduct({
                                            ...editingProduct,
                                            replyScope: JSON.stringify([]),
                                            perWebsiteReplySettings: ensurePerWebsiteReplySettings(editingProduct),
                                          })
                                        }
                                      }}
                                    />
                                    <label htmlFor="scope-all" className="text-sm cursor-pointer font-bold">所有网站 (All)</label>
                                  </div>
                                  {availableWebsites.map(site => (
                                    <div key={site.id} className="flex items-center space-x-2">
                                      <Checkbox
                                        id={`scope-${site.name}`}
                                        checked={editingProduct?.replyScope !== 'all' && isScopeSelected(site.name)}
                                        onCheckedChange={(checked) => handleScopeChange(site.name, checked === true)}
                                      />
                                      <label htmlFor={`scope-${site.name}`} className="text-sm cursor-pointer">
                                        {site.display_name} ({site.name})
                                      </label>
                                    </div>
                                  ))}
                                  {!availableWebsites.length && (
                                    <p className="text-xs text-muted-foreground">暂无网站配置</p>
                                  )}
                                </div>
                                <p className="text-xs text-muted-foreground">
                                  勾选 "所有网站" 将覆盖其他选择。如果不勾选 "所有网站"，则仅在勾选的特定网站频道回复。
                                </p>
                              </div>
                              <div className="space-y-2">
                                <Label className="text-sm font-medium">网站独立回复设置</Label>
                                <p className="text-xs text-muted-foreground">
                                  每个网站单独设置回复内容和图片。新选网站默认空白，不会自动沿用其他网站刚填写的内容。
                                </p>
                              </div>

                              {getScopedWebsites(editingProduct, availableWebsites).length > 0 ? (
                                <div className="space-y-4">
                                  {getScopedWebsites(editingProduct, availableWebsites).map(site => {
                                    const websiteSetting = getWebsiteReplySetting(editingProduct, site.id, availableWebsites)
                                    const uploadInputId = `edit-upload-input-${site.id}`

                                    return (
                                      <div key={site.id} className="space-y-4 rounded-lg border bg-white p-4">
                                        <div className="flex items-center justify-between">
                                          <div className="space-y-1">
                                            <Label className="text-sm font-semibold">
                                              {site.display_name} ({site.name})
                                            </Label>
                                            <p className="text-xs text-muted-foreground">
                                              这个网站命中时只用这里的文案和图片
                                            </p>
                                          </div>
                                          <Badge variant="secondary">{site.name}</Badge>
                                        </div>

                                        <div className="space-y-2">
                                          <Label className="text-sm font-medium">自定义回复消息</Label>
                                          <Textarea
                                            value={websiteSetting.customReplyText || ""}
                                            onChange={(e) => updateWebsiteReplySetting(site.id, current => ({
                                              ...current,
                                              customReplyText: e.target.value,
                                            }))}
                                            placeholder="输入这个网站的自定义回复内容..."
                                            rows={3}
                                          />
                                          <p className="text-xs text-muted-foreground">
                                            支持 <span className="font-mono">{`{url}`}</span> 占位符；留空将只发送下面选中的图片
                                          </p>
                                        </div>

                                        <div className="space-y-3">
                                          <Label className="text-sm font-medium">附带图片回复</Label>

                                          <div className="space-y-2 rounded-md border bg-gray-50 p-3">
                                            <Label className="text-xs font-medium text-gray-700">选择图片来源</Label>
                                            <div className="flex flex-wrap gap-4">
                                              <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                  type="radio"
                                                  name={`imageSource-${site.id}`}
                                                  value="product"
                                                  checked={websiteSetting.imageSource === 'product'}
                                                  onChange={() => updateWebsiteReplySetting(site.id, current => ({
                                                    ...current,
                                                    imageSource: 'product',
                                                    uploadedImages: [],
                                                    existingUploadedImageUrls: [],
                                                    customImageUrls: [],
                                                  }))}
                                                  className="w-4 h-4"
                                                />
                                                <span className="text-sm">使用商品图片</span>
                                              </label>
                                              <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                  type="radio"
                                                  name={`imageSource-${site.id}`}
                                                  value="upload"
                                                  checked={websiteSetting.imageSource === 'upload'}
                                                  onChange={() => updateWebsiteReplySetting(site.id, current => ({
                                                    ...current,
                                                    imageSource: 'upload',
                                                    selectedImageIndexes: [],
                                                    customImageUrls: [],
                                                  }))}
                                                  className="w-4 h-4"
                                                />
                                                <span className="text-sm">上传本地图片</span>
                                              </label>
                                              <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                  type="radio"
                                                  name={`imageSource-${site.id}`}
                                                  value="custom"
                                                  checked={websiteSetting.imageSource === 'custom'}
                                                  onChange={() => updateWebsiteReplySetting(site.id, current => ({
                                                    ...current,
                                                    imageSource: 'custom',
                                                    selectedImageIndexes: [],
                                                    uploadedImages: [],
                                                    existingUploadedImageUrls: [],
                                                  }))}
                                                  className="w-4 h-4"
                                                />
                                                <span className="text-sm">使用图片链接</span>
                                              </label>
                                            </div>
                                          </div>

                                          {websiteSetting.imageSource === 'product' && (
                                            <div className="space-y-2">
                                              <Label className="text-xs text-muted-foreground">勾选现有商品图片</Label>
                                              <div className="grid grid-cols-3 md:grid-cols-4 gap-3 max-h-60 overflow-y-auto p-2 border rounded-md bg-white">
                                                {editingProduct?.images?.map((image: string, index: number) => (
                                                  <div
                                                    key={`${site.id}-prod-${index}`}
                                                    className={`relative aspect-square rounded-md overflow-hidden cursor-pointer border-2 transition-all ${
                                                      websiteSetting.selectedImageIndexes.includes(index)
                                                        ? 'border-blue-500 ring-2 ring-blue-200'
                                                        : 'border-transparent hover:border-gray-200'
                                                    }`}
                                                    onClick={() => {
                                                      const selectedIndexes = websiteSetting.selectedImageIndexes.includes(index)
                                                        ? websiteSetting.selectedImageIndexes.filter((item: number) => item !== index)
                                                        : [...websiteSetting.selectedImageIndexes, index]
                                                      updateWebsiteReplySetting(site.id, current => ({
                                                        ...current,
                                                        imageSource: 'product',
                                                        selectedImageIndexes: selectedIndexes,
                                                      }))
                                                    }}
                                                  >
                                                    <img
                                                      src={image}
                                                      alt={`图片 ${index + 1}`}
                                                      className="w-full h-full object-cover"
                                                    />
                                                    {websiteSetting.selectedImageIndexes.includes(index) && (
                                                      <div className="absolute top-1 right-1 bg-blue-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs shadow-sm">
                                                        ✓
                                                      </div>
                                                    )}
                                                  </div>
                                                ))}
                                              </div>
                                              <p className="text-xs text-muted-foreground">
                                                已选 {websiteSetting.selectedImageIndexes.length} 张现有图片
                                              </p>
                                            </div>
                                          )}

                                          {websiteSetting.imageSource === 'upload' && (
                                            <div className="space-y-2">
                                              <input
                                                type="file"
                                                multiple
                                                accept="image/*"
                                                className="hidden"
                                                id={uploadInputId}
                                                onChange={(e) => {
                                                  const files = Array.from(e.target.files || [])
                                                  if (files.length > 0) {
                                                    updateWebsiteReplySetting(site.id, current => ({
                                                      ...current,
                                                      imageSource: 'upload',
                                                      uploadedImages: [...(current.uploadedImages || []), ...files],
                                                    }))
                                                  }
                                                }}
                                              />
                                              <div className="flex justify-between items-center">
                                                <Label className="text-xs text-muted-foreground">上传本地图片</Label>
                                                <Label
                                                  htmlFor={uploadInputId}
                                                  className="cursor-pointer text-xs bg-blue-500 text-white px-3 py-1 rounded hover:bg-blue-600 flex items-center"
                                                >
                                                  <Upload className="w-3 h-3 mr-1"/> 选择文件
                                                </Label>
                                              </div>

                                              {(websiteSetting.existingUploadedImageUrls.length > 0 || websiteSetting.uploadedImages.length > 0) && (
                                                <>
                                                  <div className="grid grid-cols-3 md:grid-cols-4 gap-3 p-2 border rounded-md bg-white">
                                                    {websiteSetting.existingUploadedImageUrls.map((url: string, index: number) => (
                                                      <div key={`${site.id}-existing-${index}`} className="relative aspect-square rounded-md overflow-hidden border-2 border-blue-500">
                                                        <img
                                                          src={url}
                                                          alt="已保存图片"
                                                          className="w-full h-full object-cover"
                                                        />
                                                        <div className="absolute top-1 right-1 bg-blue-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs">
                                                          ✓
                                                        </div>
                                                        <button
                                                          type="button"
                                                          className="absolute bottom-1 right-1 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center"
                                                          onClick={(e) => {
                                                            e.stopPropagation()
                                                            updateWebsiteReplySetting(site.id, current => ({
                                                              ...current,
                                                              existingUploadedImageUrls: current.existingUploadedImageUrls.filter((_: any, i: number) => i !== index),
                                                            }))
                                                          }}
                                                        >
                                                          <X className="w-3 h-3"/>
                                                        </button>
                                                      </div>
                                                    ))}

                                                    {websiteSetting.uploadedImages.map((file: File, index: number) => (
                                                      <div key={`${site.id}-new-${index}`} className="relative aspect-square rounded-md overflow-hidden border-2 border-green-500">
                                                        <img
                                                          src={URL.createObjectURL(file)}
                                                          alt="新上传图片"
                                                          className="w-full h-full object-cover"
                                                        />
                                                        <div className="absolute top-1 right-1 bg-green-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs">
                                                          新
                                                        </div>
                                                        <button
                                                          type="button"
                                                          className="absolute bottom-1 right-1 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center"
                                                          onClick={(e) => {
                                                            e.stopPropagation()
                                                            updateWebsiteReplySetting(site.id, current => ({
                                                              ...current,
                                                              uploadedImages: current.uploadedImages.filter((_: any, i: number) => i !== index),
                                                            }))
                                                          }}
                                                        >
                                                          <X className="w-3 h-3"/>
                                                        </button>
                                                      </div>
                                                    ))}
                                                  </div>
                                                  <p className="text-xs text-muted-foreground">
                                                    已保存: {websiteSetting.existingUploadedImageUrls.length} 张 | 新上传: {websiteSetting.uploadedImages.length} 张
                                                  </p>
                                                </>
                                              )}
                                            </div>
                                          )}

                                          {websiteSetting.imageSource === 'custom' && (
                                            <div className="space-y-2">
                                              <Label className="text-xs text-muted-foreground">填写图片链接（每行一个）</Label>
                                              <Textarea
                                                value={websiteSetting.customImageUrls.join('\n')}
                                                onChange={(e) => {
                                                  const urls = e.target.value.split('\n').map(url => url.trim()).filter(Boolean)
                                                  updateWebsiteReplySetting(site.id, current => ({
                                                    ...current,
                                                    imageSource: 'custom',
                                                    customImageUrls: urls,
                                                  }))
                                                }}
                                                placeholder="https://example.com/image1.jpg&#10;https://example.com/image2.jpg"
                                                rows={4}
                                                className="text-xs"
                                              />
                                              <p className="text-xs text-muted-foreground">
                                                {websiteSetting.customImageUrls.length > 0
                                                  ? `已填写 ${websiteSetting.customImageUrls.length} 个图片链接`
                                                  : '填写后将使用这些链接的图片回复'}
                                              </p>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    )
                                  })}
                                </div>
                              ) : (
                                <p className="text-xs text-muted-foreground">
                                  先在上面勾选要生效的网站，下面才会出现对应的网站独立配置。
                                </p>
                              )}
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
                            显示第 {(currentPage-1)*itemsPerPage + 1} - {Math.min(currentPage*itemsPerPage, totalProducts)} 条，共 {totalProducts} 条记录
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
                                disabled={!hasNextPage}
                                className="h-8 px-3"
                  >
                                下一页 <ChevronRight className="h-4 w-4 ml-1"/>
                  </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 失败商品详情 */}
      <Dialog open={showFailedDialog} onOpenChange={setShowFailedDialog}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{failedDialogTitle}</DialogTitle>
            <DialogDescription>以下商品抓取失败，请检查原因</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {dialogFailedItems.map((item) => (
              <div key={item.id} className="p-3 bg-muted rounded border space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-mono text-sm">{item.id}</div>
                  <div className="text-sm text-red-600 text-right">{item.reason}</div>
                </div>
                {item.details && item.details.length > 0 && (
                  <div className="text-xs text-muted-foreground space-y-1">
                    {item.details.map((detail, index) => (
                      <div key={`${item.id}-${detail.index}-${index}`} className="flex flex-wrap gap-2">
                        <span className="font-mono">#{detail.index}</span>
                        <span>{detail.reason}</span>
                        {detail.url && (
                          <span className="truncate max-w-[420px] text-[10px] text-muted-foreground/80">
                            {detail.url}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {dialogFailedItems.length === 0 && (
              <div className="text-center text-sm text-muted-foreground">暂无失败记录</div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowFailedDialog(false)
              }}
            >
              关闭
            </Button>
            <Button
              onClick={() => {
                const retryIds = dialogFailedItems
                  .map(item => item.id)
                  .filter(id => id && id.match(/^\d+$/))
                if (retryIds.length > 0) {
                  setBatchIds(retryIds.join('\n'))
                  startBatchScrape(retryIds)
                }
                setShowFailedDialog(false)
              }}
              disabled={dialogFailedItems.length === 0}
            >
              重试所有失败项
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
              {selectAllAcrossPages
                ? `确定要删除全部 ${totalProducts} 个商品吗？此操作不可恢复。`
                : `确定要删除选中的 ${selectedCount} 个商品吗？此操作不可恢复。`}
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
