"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Plus, Trash2, Store, Loader2, RefreshCw } from "lucide-react"
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

export function ShopsView() {
  const [shops, setShops] = useState<any[]>([])
  const [newShopId, setNewShopId] = useState('')
  const [isAddingShop, setIsAddingShop] = useState(false)
  const [selectedShopIds, setSelectedShopIds] = useState<string[]>([])
  const [isShopScraping, setIsShopScraping] = useState(false)
  const [shopScrapeProgress, setShopScrapeProgress] = useState(0)

  useEffect(() => {
    fetchShops()
  }, [])

  const fetchShops = async () => {
    try {
      const res = await fetch('/api/shops')
      const data = await res.json()
      setShops(data.shops || [])
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
        body: JSON.stringify({
          shopId: newShopId.trim(),
          name: shopName
        })
      })

      const data = await res.json()

      if (res.ok) {
        toast.success("店铺添加成功")
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
        method: 'DELETE'
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

  const handleScrapeSelectedShops = async () => {
    if (selectedShopIds.length === 0) {
      toast.error("请先选择要抓取的店铺")
      return
    }

    setIsShopScraping(true)
    setShopScrapeProgress(0)

    try {
      for (let i = 0; i < selectedShopIds.length; i++) {
        const shopId = selectedShopIds[i]
        const progress = ((i + 1) / selectedShopIds.length) * 100
        setShopScrapeProgress(progress)

        toast.info(`正在抓取店铺: ${shops.find(s => s.shop_id === shopId)?.name || shopId}`)

        const res = await fetch('/api/scrape/shop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ shopId })
        })

        const data = await res.json()

        if (res.ok) {
          toast.success(`店铺 ${shops.find(s => s.shop_id === shopId)?.name || shopId} 抓取完成，共获取 ${data.total_products} 个商品`)
        } else {
          toast.error(`店铺 ${shopId} 抓取失败: ${data.error || '未知错误'}`)
        }
      }

      toast.success("批量抓取完成")
    } catch (e) {
      toast.error("抓取过程中出错")
    } finally {
      setIsShopScraping(false)
      setShopScrapeProgress(0)
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
    if (selectedShopIds.length === shops.length) {
      setSelectedShopIds([])
    } else {
      setSelectedShopIds(shops.map(shop => shop.shop_id))
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">店铺管理</h2>
        <p className="text-muted-foreground">管理微店店铺，添加新店铺并进行全量抓取</p>
      </div>

      {/* 添加新店铺 */}
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

      {/* 店铺列表 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Store className="h-5 w-5" />
                店铺列表 ({shops.length})
              </CardTitle>
              <CardDescription>
                已添加的店铺，支持批量全量抓取
              </CardDescription>
            </div>
            {shops.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleSelectAllShops}
                disabled={isShopScraping}
              >
                {selectedShopIds.length === shops.length ? "取消全选" : "全选"}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {shops.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Store className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg font-medium">暂无店铺</p>
              <p className="text-sm">请先添加店铺ID</p>
            </div>
          ) : (
            <div className="space-y-3">
              {shops.map((shop) => (
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
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDeleteShop(shop.shop_id)}
                    disabled={isShopScraping}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 批量操作 */}
      {selectedShopIds.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>批量操作</CardTitle>
            <CardDescription>
              已选择 {selectedShopIds.length} 个店铺
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-3">
              <Button
                onClick={handleScrapeSelectedShops}
                disabled={isShopScraping}
                className="flex-1"
              >
                {isShopScraping ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    抓取中... ({Math.round(shopScrapeProgress)}%)
                  </>
                ) : (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    全量抓取选中店铺 ({selectedShopIds.length}个)
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                onClick={() => setSelectedShopIds([])}
                disabled={isShopScraping}
              >
                取消选择
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}