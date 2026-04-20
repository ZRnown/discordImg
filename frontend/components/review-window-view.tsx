"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { getApiErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { CheckCircle2, Inbox, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react"

type ReviewItem = {
  id: number
  website_id: number
  website_name?: string
  website_display_name?: string
  account_names?: string
  sender_name?: string
  guild_name?: string
  channel_name?: string
  position?: string
  content?: string
  source_content?: string
  message_time?: string
  created_at?: string
  payload?: any
}

type ReviewBarkMode = "count" | "interval"

type ReviewBarkSettings = {
  bark_server_url: string
  bark_device_key: string
  review_bark_enabled: boolean
  review_bark_mode: ReviewBarkMode
  review_bark_count_threshold: number
  review_bark_interval_minutes: number
}

const createDefaultReviewBarkSettings = (): ReviewBarkSettings => ({
  bark_server_url: "https://api.day.app",
  bark_device_key: "",
  review_bark_enabled: false,
  review_bark_mode: "count",
  review_bark_count_threshold: 5,
  review_bark_interval_minutes: 60,
})

const toBoolean = (value: unknown) => (
  value === true ||
  value === 1 ||
  value === "1" ||
  value === "true" ||
  value === "True"
)

const normalizePositiveInteger = (value: unknown, fallback: number) => {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback
  }
  return parsed
}

const formatReviewTime = (value: unknown) => {
  if (!value) return "未记录"
  const text = String(value)
  const normalized = text.includes("T") ? text : text.replace(" ", "T")
  const parsed = new Date(normalized)
  if (Number.isNaN(parsed.getTime())) {
    return text
  }
  return parsed.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" })
}

const normalizeReviewAccounts = (value: unknown) => {
  if (Array.isArray(value)) {
    return value.map(item => String(item).trim()).filter(Boolean)
  }
  return String(value || "")
    .split(/[,\n，]+/)
    .map(item => item.trim())
    .filter(Boolean)
}

export function ReviewWindowView({ isActive = true }: { isActive?: boolean }) {
  const [websites, setWebsites] = useState<any[]>([])
  const [items, setItems] = useState<ReviewItem[]>([])
  const [loadingWebsites, setLoadingWebsites] = useState(false)
  const [loadingItems, setLoadingItems] = useState(true)
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string>("all")
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [actionInFlight, setActionInFlight] = useState<"approved" | "rejected" | null>(null)
  const [reviewBarkSettings, setReviewBarkSettings] = useState<ReviewBarkSettings>(() => createDefaultReviewBarkSettings())
  const [loadingReviewBarkSettings, setLoadingReviewBarkSettings] = useState(false)
  const [savingReviewBarkSettings, setSavingReviewBarkSettings] = useState(false)
  const [testingReviewBark, setTestingReviewBark] = useState(false)

  const websiteOptions = useMemo(
    () =>
      websites.map((website) => ({
        id: String(website.id),
        label: website.display_name || website.name || `网站 ${website.id}`,
      })),
    [websites],
  )

  const selectedCount = selectedIds.length
  const allSelected = items.length > 0 && selectedCount === items.length

  const fetchWebsites = useCallback(async () => {
    setLoadingWebsites(true)
    try {
      const response = await fetch("/api/websites", {
        credentials: "include",
        cache: "no-store",
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "获取网站列表失败"))
      }
      setWebsites(data.websites || [])
    } catch (error) {
      toast.error(getApiErrorMessage(error, "获取网站列表失败"))
    } finally {
      setLoadingWebsites(false)
    }
  }, [])

  const fetchReviewBarkSettings = useCallback(async () => {
    setLoadingReviewBarkSettings(true)
    try {
      const response = await fetch("/api/user/settings", {
        credentials: "include",
        cache: "no-store",
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "获取审核 Bark 设置失败"))
      }

      setReviewBarkSettings({
        bark_server_url: String(data.bark_server_url || "https://api.day.app").trim() || "https://api.day.app",
        bark_device_key: String(data.bark_device_key || ""),
        review_bark_enabled: toBoolean(data.review_bark_enabled),
        review_bark_mode: String(data.review_bark_mode || "count").trim().toLowerCase() === "interval" ? "interval" : "count",
        review_bark_count_threshold: normalizePositiveInteger(data.review_bark_count_threshold, 5),
        review_bark_interval_minutes: normalizePositiveInteger(data.review_bark_interval_minutes, 60),
      })
    } catch (error) {
      toast.error(getApiErrorMessage(error, "获取审核 Bark 设置失败"))
    } finally {
      setLoadingReviewBarkSettings(false)
    }
  }, [])

  const fetchItems = useCallback(async (options?: { preserveSelection?: boolean; silent?: boolean }) => {
    setLoadingItems(true)
    try {
      const params = new URLSearchParams()
      params.set("status", "pending")
      if (selectedWebsiteId !== "all") {
        params.set("website_id", selectedWebsiteId)
      }
      const response = await fetch(`/api/keyword-review-items?${params.toString()}`, {
        credentials: "include",
        cache: "no-store",
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "获取审核队列失败"))
      }
      const nextItems: ReviewItem[] = data.items || []
      setItems(nextItems)
      setSelectedIds(prev => {
        if (!options?.preserveSelection) {
          return []
        }
        const nextIds = new Set(nextItems.map(item => item.id))
        return prev.filter(id => nextIds.has(id))
      })
    } catch (error) {
      if (!options?.silent) {
        toast.error(getApiErrorMessage(error, "获取审核队列失败"))
      }
    } finally {
      setLoadingItems(false)
    }
  }, [selectedWebsiteId])

  useEffect(() => {
    if (!isActive) return
    void fetchWebsites()
    void fetchReviewBarkSettings()
  }, [isActive, fetchReviewBarkSettings, fetchWebsites])

  useEffect(() => {
    if (!isActive) return
    void fetchItems()
  }, [isActive, fetchItems])

  useEffect(() => {
    if (!isActive) return
    const timer = setInterval(() => {
      void fetchItems({ preserveSelection: true, silent: true })
    }, 15000)
    return () => clearInterval(timer)
  }, [isActive, fetchItems])

  const toggleSelected = (itemId: number, checked: boolean) => {
    setSelectedIds(prev => {
      if (checked) {
        if (prev.includes(itemId)) return prev
        return [...prev, itemId]
      }
      return prev.filter(id => id !== itemId)
    })
  }

  const toggleAll = (checked: boolean) => {
    if (!checked) {
      setSelectedIds([])
      return
    }
    setSelectedIds(items.map(item => item.id))
  }

  const submitAction = async (action: "approved" | "rejected", ids: number[]) => {
    if (!ids.length) {
      toast.error("请先选择要审核的消息")
      return
    }

    setActionInFlight(action)
    try {
      const response = await fetch("/api/keyword-review-items/bulk-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ item_ids: ids, action }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "审核失败"))
      }

      if (data.success === false) {
        toast.error(data.message || "部分消息审核失败")
      } else {
        toast.success(data.message || "审核完成")
      }
      setSelectedIds([])
      await fetchItems()
    } catch (error) {
      toast.error(getApiErrorMessage(error, "审核失败"))
    } finally {
      setActionInFlight(null)
    }
  }

  const saveReviewBarkSettings = async () => {
    if (reviewBarkSettings.review_bark_enabled && !reviewBarkSettings.bark_device_key.trim()) {
      toast.error("启用审核 Bark 通知前，请先填写 Bark 设备 Key")
      return
    }

    setSavingReviewBarkSettings(true)
    try {
      const response = await fetch("/api/user/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          bark_server_url: reviewBarkSettings.bark_server_url.trim() || "https://api.day.app",
          bark_device_key: reviewBarkSettings.bark_device_key.trim(),
          review_bark_enabled: reviewBarkSettings.review_bark_enabled,
          review_bark_mode: reviewBarkSettings.review_bark_mode,
          review_bark_count_threshold: normalizePositiveInteger(reviewBarkSettings.review_bark_count_threshold, 5),
          review_bark_interval_minutes: normalizePositiveInteger(reviewBarkSettings.review_bark_interval_minutes, 60),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "保存审核 Bark 设置失败"))
      }
      toast.success(data.message || "审核 Bark 设置已保存")
      await fetchReviewBarkSettings()
    } catch (error) {
      toast.error(getApiErrorMessage(error, "保存审核 Bark 设置失败"))
    } finally {
      setSavingReviewBarkSettings(false)
    }
  }

  const testReviewBarkNotification = async () => {
    if (!reviewBarkSettings.bark_device_key.trim()) {
      toast.error("请先填写 Bark 设备 Key")
      return
    }

    setTestingReviewBark(true)
    try {
      const response = await fetch("/internal-api/bark-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          bark_server_url: reviewBarkSettings.bark_server_url.trim() || "https://api.day.app",
          bark_device_key: reviewBarkSettings.bark_device_key.trim(),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "发送测试推送失败"))
      }
      toast.success(data.message || "测试推送已发送")
    } catch (error) {
      toast.error(getApiErrorMessage(error, "发送测试推送失败"))
    } finally {
      setTestingReviewBark(false)
    }
  }

  const visibleSelectedItems = items.filter(item => selectedIds.includes(item.id))

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden border shadow-sm">
        <div className="border-b bg-muted/20 px-6 py-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/10 bg-primary/5 px-3 py-1 text-xs font-medium text-primary">
                <ShieldCheck className="size-3.5" />
                人工审核窗口
              </div>
              <div>
                <h2 className="text-2xl font-semibold tracking-tight">待审关键词消息</h2>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                  通过后会继续走网站配置的发送逻辑，保留自定义内容、图片和当前账号调度规则。
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border bg-background px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">待审</div>
                <div className="mt-1 text-2xl font-semibold">{items.length}</div>
              </div>
              <div className="rounded-lg border bg-background px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">已选</div>
                <div className="mt-1 text-2xl font-semibold">{selectedCount}</div>
              </div>
              <div className="rounded-lg border bg-background px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">网站</div>
                <div className="mt-1 text-2xl font-semibold">{websites.length}</div>
              </div>
              <div className="rounded-lg border bg-background px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">刷新</div>
                <div className="mt-1 text-sm text-foreground">15 秒轮询</div>
              </div>
            </div>
          </div>
        </div>

        <CardContent className="space-y-5 p-6">
          <div className="rounded-lg border bg-background p-4">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="text-sm font-medium">审核 Bark 通知</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    放在人工审核页管理。可按待审数量触发，也可按时间间隔汇总当前待审条数。
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Label htmlFor="review-bark-enabled" className="text-sm">启用</Label>
                  <Switch
                    id="review-bark-enabled"
                    checked={reviewBarkSettings.review_bark_enabled}
                    onCheckedChange={(checked) => {
                      setReviewBarkSettings(prev => ({ ...prev, review_bark_enabled: checked }))
                    }}
                  />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="review-bark-server-url" className="text-sm">Bark 服务地址</Label>
                  <Input
                    id="review-bark-server-url"
                    value={reviewBarkSettings.bark_server_url}
                    onChange={(event) => {
                      const value = event.target.value
                      setReviewBarkSettings(prev => ({ ...prev, bark_server_url: value }))
                    }}
                    placeholder="https://api.day.app"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="review-bark-device-key" className="text-sm">Bark 设备 Key</Label>
                  <Input
                    id="review-bark-device-key"
                    type="password"
                    value={reviewBarkSettings.bark_device_key}
                    onChange={(event) => {
                      const value = event.target.value
                      setReviewBarkSettings(prev => ({ ...prev, bark_device_key: value }))
                    }}
                    placeholder="从 Bark App 复制"
                  />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
                <div className="space-y-1">
                  <Label className="text-sm">通知类型</Label>
                  <Select
                    value={reviewBarkSettings.review_bark_mode}
                    onValueChange={(value) => {
                      const nextMode: ReviewBarkMode = value === "interval" ? "interval" : "count"
                      setReviewBarkSettings(prev => ({ ...prev, review_bark_mode: nextMode }))
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="count">待审数量通知</SelectItem>
                      <SelectItem value="interval">时间通知</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {reviewBarkSettings.review_bark_mode === "count" ? (
                  <div className="space-y-1">
                    <Label htmlFor="review-bark-count-threshold" className="text-sm">待审达到</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        id="review-bark-count-threshold"
                        type="number"
                        min={1}
                        value={reviewBarkSettings.review_bark_count_threshold}
                        onChange={(event) => {
                          const value = normalizePositiveInteger(event.target.value, 1)
                          setReviewBarkSettings(prev => ({ ...prev, review_bark_count_threshold: value }))
                        }}
                        className="w-28"
                      />
                      <span className="text-xs text-muted-foreground">条时推送一次</span>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <Label htmlFor="review-bark-interval-minutes" className="text-sm">通知间隔</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        id="review-bark-interval-minutes"
                        type="number"
                        min={1}
                        value={reviewBarkSettings.review_bark_interval_minutes}
                        onChange={(event) => {
                          const value = normalizePositiveInteger(event.target.value, 1)
                          setReviewBarkSettings(prev => ({ ...prev, review_bark_interval_minutes: value }))
                        }}
                        className="w-28"
                      />
                      <span className="text-xs text-muted-foreground">分钟汇总一次当前待审条数</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="text-xs text-muted-foreground">
                  {loadingReviewBarkSettings
                    ? "正在加载审核 Bark 设置..."
                    : savingReviewBarkSettings
                      ? "审核 Bark 设置保存中..."
                      : "审核 Bark 通知会复用当前账号的 Bark 服务地址和设备 Key"}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void testReviewBarkNotification()}
                    disabled={testingReviewBark}
                  >
                    {testingReviewBark ? "测试推送中..." : "发送测试推送"}
                  </Button>
                  <Button
                    type="button"
                    onClick={() => void saveReviewBarkSettings()}
                    disabled={savingReviewBarkSettings}
                  >
                    {savingReviewBarkSettings ? "保存中..." : "保存通知设置"}
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-4 rounded-lg border bg-muted/20 p-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="grid gap-3 sm:grid-cols-[240px_auto] sm:items-end">
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">筛选网站</div>
                <Select value={selectedWebsiteId} onValueChange={setSelectedWebsiteId}>
                  <SelectTrigger className="w-[240px]">
                    <SelectValue placeholder="全部网站" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部网站</SelectItem>
                    {websiteOptions.map(option => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-end gap-2">
                <Button variant="outline" size="sm" onClick={() => void fetchItems({ preserveSelection: true })} disabled={loadingItems}>
                  {loadingItems ? <Loader2 className="mr-2 size-4 animate-spin" /> : <RefreshCw className="mr-2 size-4" />}
                  刷新
                </Button>
                <div className="text-xs text-muted-foreground">
                  {loadingWebsites ? "正在加载网站..." : selectedWebsiteId === "all" ? "显示全部待审消息" : "仅显示当前网站"}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void submitAction("rejected", selectedIds)}
                disabled={!selectedIds.length || actionInFlight !== null}
              >
                {actionInFlight === "rejected" ? <Loader2 className="mr-2 size-4 animate-spin" /> : <XCircle className="mr-2 size-4" />}
                拒绝选中
              </Button>
              <Button
                size="sm"
                onClick={() => void submitAction("approved", selectedIds)}
                disabled={!selectedIds.length || actionInFlight !== null}
              >
                {actionInFlight === "approved" ? <Loader2 className="mr-2 size-4 animate-spin" /> : <CheckCircle2 className="mr-2 size-4" />}
                通过选中
              </Button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border bg-background">
            <div className="flex items-center justify-between gap-3 border-b bg-muted/10 px-4 py-3">
              <label className="flex items-center gap-3 text-sm font-medium">
                <Checkbox checked={allSelected} onCheckedChange={toggleAll} />
                全选当前结果
              </label>
              <div className="text-xs text-muted-foreground">
                {selectedCount > 0 ? `已选择 ${selectedCount} 条` : "未选择任何消息"}
              </div>
            </div>

            <div className="divide-y">
              {loadingItems && items.length === 0 ? (
                <div className="flex min-h-[320px] flex-col items-center justify-center px-6 py-14 text-center">
                  <Loader2 className="size-8 animate-spin text-muted-foreground" />
                  <p className="mt-3 text-sm text-muted-foreground">正在加载待审消息...</p>
                </div>
              ) : null}
              {!loadingItems && items.length === 0 ? (
                <div className="flex min-h-[320px] flex-col items-center justify-center px-6 py-14 text-center">
                  <Inbox className="size-12 text-muted-foreground/60" />
                  <h3 className="mt-4 text-lg font-medium">没有待审消息</h3>
                  <p className="mt-1 max-w-md text-sm text-muted-foreground">
                    当前筛选条件下没有需要人工审核的关键词回复。
                  </p>
                </div>
              ) : null}

              {items.map((item) => {
                const accountNames = normalizeReviewAccounts(item.account_names)
                const selected = selectedIds.includes(item.id)
                const content = String(item.content || "").trim() || "（无文本内容）"
                const sourceContent = String(item.source_content || "").trim()
                const websiteLabel = item.website_display_name || item.website_name || `网站 ${item.website_id}`

                return (
                  <div
                    key={item.id}
                    className="grid gap-4 px-4 py-4 transition-colors hover:bg-muted/20 lg:grid-cols-[auto_minmax(0,1fr)_auto]"
                  >
                    <div className="pt-1">
                      <Checkbox checked={selected} onCheckedChange={(checked) => toggleSelected(item.id, Boolean(checked))} />
                    </div>

                    <div className="space-y-3">
                      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                        <div className="rounded-lg border bg-muted/20 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">网站</div>
                          <div className="mt-1 text-sm font-medium">{websiteLabel}</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">发送者</div>
                          <div className="mt-1 text-sm font-medium">{item.sender_name || "未记录"}</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">发送账号</div>
                          <div className="mt-1 text-sm font-medium">{accountNames.join(" / ") || "未记录"}</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">来源</div>
                          <div className="mt-1 text-sm font-medium">{item.guild_name || "服务器"} / #{item.channel_name || "频道"}</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">时间</div>
                          <div className="mt-1 text-sm font-medium">{formatReviewTime(item.message_time || item.created_at)}</div>
                        </div>
                      </div>

                      {sourceContent ? (
                        <div className="rounded-lg border border-dashed bg-background px-3 py-2">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">原始消息</div>
                          <div className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words text-sm text-muted-foreground">
                            {sourceContent}
                          </div>
                        </div>
                      ) : null}

                      <div className="rounded-lg border bg-muted/10 px-4 py-3">
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">发送内容</div>
                        <div className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-words text-sm leading-6">
                          {content}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-start gap-2 lg:flex-col lg:items-stretch">
                      <Button
                        size="sm"
                        onClick={() => void submitAction("approved", [item.id])}
                        disabled={actionInFlight !== null}
                      >
                        <CheckCircle2 className="mr-2 size-4" />
                        通过
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void submitAction("rejected", [item.id])}
                        disabled={actionInFlight !== null}
                      >
                        <XCircle className="mr-2 size-4" />
                        拒绝
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <Separator />

          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <div>选中消息将按当前网站配置重新调度发送。</div>
            <div>{visibleSelectedItems.length > 0 ? `当前选中 ${visibleSelectedItems.length} 条` : "可直接批量处理"}</div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
