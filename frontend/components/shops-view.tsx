"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Plus, Trash2, Store, Loader2, RefreshCw, Search, CheckSquare, Square } from "lucide-react"
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

export function ShopsView({ currentUser }: { currentUser: any }) {

  const [shops, setShops] = useState<any[]>([])
  const [newShopId, setNewShopId] = useState('')
  const [isAddingShop, setIsAddingShop] = useState(false)
  const [selectedShopIds, setSelectedShopIds] = useState<string[]>([])
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [isBatchDeleting, setIsBatchDeleting] = useState(false)
  const [showBatchDeleteConfirm, setShowBatchDeleteConfirm] = useState(false)

  useEffect(() => {
    fetchShops()
  }, [])

  const fetchShops = async () => {
    try {
      const res = await fetch('/api/shops', {
        credentials: 'include'
      })
      const data = await res.json()
      let allShops = data.shops || []

      // 根据用户权限过滤店铺
      if (currentUser?.role !== 'admin' && currentUser?.shops) {
        // 普通用户只看到分配给他们的店铺
        allShops = allShops.filter((shop: any) => currentUser.shops.includes(shop.shop_id))
      }

      setShops(allShops)
    } catch (e) {
      toast.error("加载店铺列表失败")
    }
  }

  const fetchShopInfo = async (shopId: string) => {
    try {
      const res = await fetch(`/api/shop-info?shopId=${shopId}`)
      const data = await res.json()
      return data.shopName || `店铺 ${shopId}`
    } catch (e) {
      console.error("获取店铺信息失败:", e)
      return `店铺 ${shopId}`
    }
  }

  const handleAddShop = async () => {
    if (!newShopId.trim()) {
      toast.error("请输入店铺ID")
      return
    }

    if (!/^\d+$/.test(newShopId.trim())) {
      toast.error("店铺ID必须是数字")
      return
    }

    setIsAddingShop(true)
    try {
      // 先获取店铺名称
      const shopName = await fetchShopInfo(newShopId.trim())

      const res = await fetch('/api/shops', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          shopId: newShopId.trim(),
          name: shopName
        })
      })

      const data = await res.json()

      if (res.ok) {
        toast.success("店铺添加成功，正在开始抓取商品...")

        // 添加成功后自动开始抓取该店铺的商品
        const shopId = newShopId.trim()
        try {
          await fetch(`/api/scrape/shop?shopId=${shopId}`, {
            method: 'POST'
          })
          toast.success("商品抓取已启动，请查看实时日志")
        } catch (scrapeError) {
          toast.warning("店铺添加成功，但商品抓取启动失败")
        }

        setNewShopId('')
        fetchShops()
      } else {
        toast.error(data.error || "添加店铺失败")
      }
    } catch (e) {
      toast.error("添加店铺失败")
    } finally {
      setIsAddingShop(false)
    }
  }

  const handleDeleteShop = async (shopId: string) => {
    try {
      const res = await fetch(`/api/shops/${shopId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (res.ok) {
        toast.success("店铺删除成功")
        fetchShops()
        // 移除选中状态
        setSelectedShopIds(prev => prev.filter(id => id !== shopId))
      } else {
        toast.error("删除店铺失败")
      }
    } catch (e) {
      toast.error("删除店铺失败")
    }
  }


  const handleSelectShop = (shopId: string) => {
    setSelectedShopIds(prev =>
      prev.includes(shopId)
        ? prev.filter(id => id !== shopId)
        : [...prev, shopId]
    )
  }

  const handleSelectAllShops = () => {
    if (selectedShopIds.length === filteredShops.length) {
      setSelectedShopIds([])
    } else {
      setSelectedShopIds(filteredShops.map(shop => shop.shop_id))
    }
  }

  const handleBatchDeleteShops = () => {
    if (selectedShopIds.length === 0) return
    setShowBatchDeleteConfirm(true)
  }

  const confirmBatchDeleteShops = async () => {
    setShowBatchDeleteConfirm(false)
    setIsBatchDeleting(true)

    let successCount = 0
    let failCount = 0

    try {
      for (const shopId of selectedShopIds) {
        try {
          const res = await fetch(`/api/shops/${shopId}`, {
            method: 'DELETE',
            credentials: 'include'
          })

          if (res.ok) {
            successCount++
          } else {
            failCount++
          }
        } catch (e) {
          failCount++
        }
      }

      if (successCount > 0) {
        toast.success(`批量删除完成：成功 ${successCount} 个${failCount > 0 ? `，失败 ${failCount} 个` : ''}`)
        setSelectedShopIds([])
        fetchShops()
      } else {
        toast.error("批量删除失败")
      }
    } catch (e) {
      toast.error("批量删除过程中发生错误")
    } finally {
      setIsBatchDeleting(false)
    }
  }

  // 过滤店铺列表
  const filteredShops = shops.filter(shop =>
    shop.name?.toLowerCase().includes(searchKeyword.toLowerCase()) ||
    shop.shop_id?.includes(searchKeyword)
  )

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">店铺管理</h2>
        <p className="text-muted-foreground">管理微店店铺，添加新店铺并进行全量抓取</p>
        <div className="flex items-center gap-2 mt-2">
          <span className="text-sm text-muted-foreground">当前用户:</span>
          <span className="font-medium">{currentUser?.username}</span>
          <span className={`text-xs px-2 py-1 rounded ${
            currentUser?.role === 'admin'
              ? 'bg-blue-100 text-blue-700'
              : 'bg-gray-100 text-gray-700'
          }`}>
            {currentUser?.role === 'admin' ? '管理员' : '普通用户'}
          </span>
        </div>
      </div>

      {/* 添加新店铺 - 仅管理员可见 */}
      {currentUser?.role === 'admin' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5" />
              添加新店铺
            </CardTitle>
            <CardDescription>
              输入微店店铺ID，系统会自动获取店铺名称
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-3">
              <div className="flex-1">
                <Input
                  placeholder="输入店铺ID (例如: 1713062461)"
                  value={newShopId}
                  onChange={(e) => setNewShopId(e.target.value)}
                  disabled={isAddingShop}
                  onKeyPress={(e) => e.key === 'Enter' && handleAddShop()}
                />
              </div>
              <Button
                onClick={handleAddShop}
                disabled={!newShopId.trim() || isAddingShop}
              >
                {isAddingShop ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    添加中...
                  </>
                ) : (
                  <>
                    <Plus className="mr-2 h-4 w-4" />
                    添加店铺
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}


      {/* 店铺列表 */}
      <Card>
        <CardHeader className="pb-4">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Store className="h-5 w-5" />
                店铺列表 ({shops.length})
              </CardTitle>
              <CardDescription>
                已添加的店铺，支持批量全量抓取和删除
              </CardDescription>
            </div>
            {selectedShopIds.length > 0 && currentUser?.role === 'admin' && (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleBatchDeleteShops}
                disabled={isBatchDeleting}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                删除选中 ({selectedShopIds.length})
              </Button>
            )}
          </div>
        </CardHeader>

        {/* 搜索和操作工具栏 */}
        {shops.length > 0 && (
          <div className="px-6 pb-4 border-b bg-muted/10">
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
              <div className="flex-1">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="搜索店铺名称或ID..."
                    value={searchKeyword}
                    onChange={(e) => setSearchKeyword(e.target.value)}
                    className="pl-10 h-9 w-full sm:w-[300px]"
                    disabled={isShopScraping}
                  />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Button
                  variant={selectedShopIds.length > 0 && selectedShopIds.length === filteredShops.length ? "secondary" : "outline"}
                  size="sm"
                  onClick={handleSelectAllShops}
                  disabled={isShopScraping || filteredShops.length === 0}
                >
                  {selectedShopIds.length > 0 && selectedShopIds.length === filteredShops.length
                    ? <CheckSquare className="mr-2 h-4 w-4" />
                    : <Square className="mr-2 h-4 w-4" />
                  }
                  {selectedShopIds.length > 0 && selectedShopIds.length === filteredShops.length ? "取消全选" : "全选"}
                </Button>
              </div>
            </div>

            {/* 搜索结果状态 */}
            {searchKeyword && (
              <div className="mt-3 text-sm text-muted-foreground">
                搜索结果: <span className="font-medium">{filteredShops.length}</span> 个店铺
                <span className="ml-2">关键词: <span className="font-medium">"{searchKeyword}"</span></span>
              </div>
            )}

            {/* 选中状态 */}
            {selectedShopIds.length > 0 && (
              <div className="mt-2 text-sm text-blue-700 bg-blue-50 px-3 py-2 rounded-md border border-blue-200">
                已选择 <span className="font-medium">{selectedShopIds.length}</span> 个店铺
              </div>
            )}
          </div>
        )}
        <CardContent>
          {shops.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Store className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg font-medium">暂无店铺</p>
              <p className="text-sm">请先添加店铺ID</p>
            </div>
          ) : filteredShops.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg font-medium">未找到匹配的店铺</p>
              <p className="text-sm">尝试调整搜索关键词</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredShops.map((shop) => (
                <div
                  key={shop.shop_id}
                  className="flex items-center justify-between p-4 border rounded-lg hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1">
                    <input
                      type="checkbox"
                      checked={selectedShopIds.includes(shop.shop_id)}
                      onChange={() => handleSelectShop(shop.shop_id)}
                      disabled={isShopScraping}
                      className="rounded border-gray-300"
                    />
                    <div className="flex-1">
                      <div className="font-medium">{shop.name}</div>
                      <div className="text-sm text-muted-foreground">
                        ID: {shop.shop_id}{shop.product_count > 0 ? ` • 商品数: ${shop.product_count}` : ''}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        添加时间: {(() => {
                          try {
                            const date = new Date(shop.created_at);
                            return isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN');
                          } catch {
                            return '未知时间';
                          }
                        })()}
                      </div>
                    </div>
                  </div>
                  {(currentUser?.role === 'admin' || currentUser?.shops?.includes(shop.shop_id)) && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleDeleteShop(shop.shop_id)}
                      disabled={isShopScraping}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 批量删除确认对话框 */}
      <Dialog open={showBatchDeleteConfirm} onOpenChange={setShowBatchDeleteConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认批量删除</DialogTitle>
            <DialogDescription>
              确定要删除选中的 {selectedShopIds.length} 个店铺吗？此操作不可恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBatchDeleteConfirm(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmBatchDeleteShops} disabled={isBatchDeleting}>
              {isBatchDeleting ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}