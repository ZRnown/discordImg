"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, RefreshCw, Trash2, MessageCircle, Save, Play, Square, Shield, Users, Settings, Bot } from "lucide-react"
import { toast } from "sonner"

export function AccountsView() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [newToken, setNewToken] = useState("")
  const [rotationEnabled, setRotationEnabled] = useState(false)
  const [rotationInterval, setRotationInterval] = useState(10)
  const [discordThreshold, setDiscordThreshold] = useState(0.6)  // 默认0.6
  const [globalMinDelay, setGlobalMinDelay] = useState(3)
  const [globalMaxDelay, setGlobalMaxDelay] = useState(8)
  const [downloadThreads, setDownloadThreads] = useState(4)
  const [featureExtractThreads, setFeatureExtractThreads] = useState(4)
  const [discordChannelId, setDiscordChannelId] = useState('')
  const [cnfansChannelId, setCnfansChannelId] = useState('')
  const [acbuyChannelId, setAcbuyChannelId] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchAccounts()
    fetchRotationConfig()
    fetchGlobalDelay()
    fetchDiscordThreshold()
    fetchThreadConfig()
    fetchDiscordChannel()
  }, [])

  const fetchAccounts = async () => {
    try {
      const response = await fetch('/api/accounts')
      if (response.ok) {
        const data = await response.json()
        setAccounts(data.accounts || [])
      }
    } catch (error) {
      console.error('Failed to fetch accounts:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchRotationConfig = async () => {
    try {
      const response = await fetch('/api/accounts/rotation')
      if (response.ok) {
        const data = await response.json()
        setRotationEnabled(data.enabled)
        setRotationInterval(data.rotationInterval)
      }
    } catch (error) {
      console.error('Failed to fetch rotation config:', error)
    }
  }

  const fetchGlobalDelay = async () => {
    try {
      const response = await fetch('/api/config/global-reply-delay')
      if (response.ok) {
        const data = await response.json()
        setGlobalMinDelay(data.min_delay)
        setGlobalMaxDelay(data.max_delay)
      }
    } catch (error) {
      console.error('Failed to fetch global delay:', error)
    }
  }

  const fetchDiscordThreshold = async () => {
    try {
      const response = await fetch('/api/config/discord-threshold')
      if (response.ok) {
        const data = await response.json()
        setDiscordThreshold(data.threshold)
      }
    } catch (error) {
      console.error('Failed to fetch Discord threshold:', error)
    }
  }

  const fetchThreadConfig = async () => {
    try {
      const response = await fetch('/api/config/threads')
      if (response.ok) {
        const data = await response.json()
        setDownloadThreads(data.download_threads)
        setFeatureExtractThreads(data.feature_extract_threads)
      }
    } catch (error) {
      console.error('Failed to fetch thread config:', error)
    }
  }

  const fetchDiscordChannel = async () => {
    try {
      const response = await fetch('/api/config/discord-channel')
      if (response.ok) {
        const data = await response.json()
        setDiscordChannelId(data.channel_id)
        setCnfansChannelId(data.cnfans_channel_id || '')
        setAcbuyChannelId(data.acbuy_channel_id || '')
      }
    } catch (error) {
      console.error('Failed to fetch Discord channel config:', error)
    }
  }

  const handleAddAccount = async () => {
    if (!newToken.trim()) {
      toast.error("请输入有效的 Token")
      return
    }

    try {
      const response = await fetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: newToken.trim() })
      })

      if (response.ok) {
        const newAccount = await response.json()
        setAccounts([...accounts, newAccount])
        toast.success("账号添加成功")
        setIsDialogOpen(false)
        setNewToken("")
      } else {
        const error = await response.json()
        toast.error(error.error || "添加账号失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const handleDeleteAccount = async (id: number) => {
    try {
      const response = await fetch(`/api/accounts/${id}`, {
        method: 'DELETE'
      })

      if (response.ok) {
        setAccounts(accounts.filter(a => a.id !== id))
        toast.success("账号已移除")
      } else {
        toast.error("删除账号失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const toggleAccountStatus = async (id: number, currentStatus: string) => {
    const newStatus = currentStatus === "online" ? "offline" : "online"

    try {
      const response = await fetch(`/api/accounts/${id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      })

      if (response.ok) {
        setAccounts((prev) =>
          prev.map((acc) => (acc.id === id ? { ...acc, status: newStatus } : acc)),
        )
      } else {
        toast.error("更新状态失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">账号与规则管理</h2>
          <p className="text-sm text-muted-foreground mt-1">管理 Discord 机器人账号、轮换设置及自动回复规则</p>
        </div>
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={async () => {
              try {
                toast.info("正在验证所有账号...")
                const response = await fetch('/api/accounts/verify-all', {
                  method: 'POST'
                })

                if (response.ok) {
                  const data = await response.json()
                  if (data.success) {
                    toast.success(`验证完成！${data.verified}个有效，${data.invalid}个无效`)
                    // 重新加载账号列表
                    fetchAccounts()
                  } else {
                    toast.error("验证失败")
                  }
                } else {
                  toast.error("验证请求失败")
                }
              } catch (error) {
                toast.error("网络错误，请重试")
              }
            }}
          >
            <Shield className="mr-2 size-5" />
            重新验证所有
          </Button>

          {accounts.length > 0 && (
            <>
              <Button
                variant="default"
                className="bg-green-600 hover:bg-green-700"
                onClick={async () => {
                  try {
                    const response = await fetch('/api/accounts/bulk-status', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ status: 'online' })
                    })

                    if (response.ok) {
                      const data = await response.json()
                      toast.success(`已开启 ${data.updated_count} 个账号`)
                      fetchAccounts()
                    } else {
                      toast.error("批量开启失败")
                    }
                  } catch (error) {
                    toast.error("网络错误，请重试")
                  }
                }}
              >
                <Play className="mr-2 size-5" />
                开启所有账号
              </Button>

              <Button
                variant="destructive"
                onClick={async () => {
                  try {
                    const response = await fetch('/api/accounts/bulk-status', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ status: 'offline' })
                    })

                    if (response.ok) {
                      const data = await response.json()
                      toast.success(`已停止 ${data.updated_count} 个账号`)
                      fetchAccounts()
                    } else {
                      toast.error("批量停止失败")
                    }
                  } catch (error) {
                    toast.error("网络错误，请重试")
                  }
                }}
              >
                <Square className="mr-2 size-5" />
                停止所有账号
              </Button>
            </>
          )}
          <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 size-5" />
                添加账号
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle className="text-xl">添加新账号</DialogTitle>
                <DialogDescription>输入 Discord 账号的 Token 以添加到系统</DialogDescription>
              </DialogHeader>
              <div className="space-y-5 py-4">
                <div className="space-y-2">
                  <Label htmlFor="token" className="text-sm font-bold">Discord Token</Label>
                  <Input
                    id="token"
                    placeholder="MTIzNDU2Nzg5MDEyMzQ1Njc4OQ..."
                    value={newToken}
                    onChange={(e) => setNewToken(e.target.value)}
                    className="h-10"
                  />
                  <p className="text-xs text-muted-foreground italic">支持使用 User Token 或 Bot Token</p>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                  取消
                </Button>
                <Button onClick={handleAddAccount}>确认添加</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-8">
        <Card className="shadow-sm">
          <CardHeader className="py-5 border-b">
            <CardTitle className="text-2xl font-bold">账号列表</CardTitle>
            <CardDescription className="text-sm">
              共 {accounts.length} 个账号，{accounts.filter((a) => a.status === "online").length} 个在线
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50 h-12">
                  <TableHead className="text-sm font-bold text-foreground pl-6">用户名</TableHead>
                  <TableHead className="text-sm font-bold text-foreground">状态</TableHead>
                  <TableHead className="text-sm font-bold text-foreground">最后活跃</TableHead>
                  <TableHead className="text-sm font-bold text-foreground text-right pr-6">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {accounts.map((account) => (
                  <TableRow key={account.id} className="h-16 hover:bg-muted/30 transition-colors">
                    <TableCell className="font-medium py-3 pl-6">
                      <div className="flex flex-col gap-1">
                        <span className="text-base font-semibold">{account.username}</span>
                        <span className="text-xs text-muted-foreground font-mono">
                          {account.token && typeof account.token === 'string' ? `${account.token.substring(0, 20)}...` : 'Token 无效'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="py-3">
                      {account.status === "online" ? (
                        <Badge className="bg-green-600 hover:bg-green-700 text-xs px-2 h-6">
                          在线
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs px-2 h-6">
                          离线
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground py-3">{account.lastActive}</TableCell>
                    <TableCell className="text-right pr-6 py-3">
                      <div className="flex items-center justify-end gap-3">
                        <Switch
                          className="scale-90"
                          checked={account.status === "online"}
                          onCheckedChange={() => toggleAccountStatus(account.id, account.status)}
                        />
                        <Button variant="ghost" size="icon" className="h-9 w-9 hover:bg-red-50 hover:text-red-600 transition-colors" onClick={() => handleDeleteAccount(account.id)}>
                          <Trash2 className="size-5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {/* 综合设置 - 全局轮换 + 系统配置 */}
            <div className="border-t">
              <div className="p-6 space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-bold">系统设置</h3>
                    <p className="text-sm text-muted-foreground">账号轮换、多线程、Discord配置</p>
                  </div>
                  <Button
                    variant="default"
                    size="sm"
                    onClick={async () => {
                      try {
                        // 保存账号轮换
                        const rotationRes = await fetch('/api/accounts/rotation', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            enabled: rotationEnabled,
                            rotationInterval: rotationInterval
                          })
                        })

                        // 保存多线程配置
                        const threadRes = await fetch('/api/config/threads', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            download_threads: downloadThreads,
                            feature_extract_threads: featureExtractThreads
                          })
                        })

                        // 保存Discord阈值
                        const thresholdRes = await fetch('/api/config/discord-threshold', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            threshold: discordThreshold
                          })
                        })

                        // 保存全局延迟
                        const delayRes = await fetch('/api/config/global-reply-delay', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            min_delay: globalMinDelay,
                            max_delay: globalMaxDelay
                          })
                        })

                        // 保存Discord频道ID
                        const channelRes = await fetch('/api/config/discord-channel', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            channel_id: discordChannelId,
                            cnfans_channel_id: cnfansChannelId,
                            acbuy_channel_id: acbuyChannelId
                          })
                        })

                        if (rotationRes.ok && threadRes.ok && thresholdRes.ok && delayRes.ok && channelRes.ok) {
                          toast.success("所有配置已保存")
                        } else {
                          toast.error("保存失败")
                        }
                      } catch (error) {
                        toast.error("网络错误，请重试")
                      }
                    }}
                  >
                    <Save className="mr-2 size-4" />
                    保存设置
                  </Button>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* 账号管理设置 */}
                  <Card>
                    <CardHeader className="pb-4">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Users className="h-4 w-4" />
                        账号管理
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <Label className="text-sm font-medium">启用账号轮换</Label>
                          <Switch
                            checked={rotationEnabled}
                            onCheckedChange={setRotationEnabled}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">轮换间隔 (秒)</Label>
                          <Input
                            type="number"
                            value={rotationInterval}
                            onChange={(e) => setRotationInterval(parseInt(e.target.value) || 0)}
                            disabled={!rotationEnabled}
                            min={1}
                            className="h-9"
                          />
                          <p className="text-xs text-muted-foreground">
                            {rotationEnabled ? `每 ${rotationInterval} 秒轮换一个账号` : '账号轮换已禁用'}
                          </p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* 系统性能设置 */}
                  <Card>
                    <CardHeader className="pb-4">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Settings className="h-4 w-4" />
                        系统性能
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">下载线程数</Label>
                          <Input
                            type="number"
                            min="1"
                            max="8"
                            value={downloadThreads}
                            onChange={(e) => setDownloadThreads(parseInt(e.target.value) || 4)}
                            className="h-9"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">特征提取线程数</Label>
                          <Input
                            type="number"
                            min="1"
                            max="8"
                            value={featureExtractThreads}
                            onChange={(e) => setFeatureExtractThreads(parseInt(e.target.value) || 4)}
                            className="h-9"
                          />
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        推荐配置: 下载 4 线程，特征提取 4 线程
                      </p>
                    </CardContent>
                  </Card>

                  {/* Discord 频道配置 */}
                  <Card className="lg:col-span-2">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Bot className="h-4 w-4" />
                        Discord 配置
                      </CardTitle>
                      <CardDescription className="text-sm">
                        配置机器人监听和回复行为
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      {/* 监听配置 */}
                      <div className="space-y-4">
                        <h4 className="text-sm font-medium">监听设置</h4>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">监听频道ID</Label>
                            <Input
                              type="text"
                              value={discordChannelId}
                              onChange={(e) => setDiscordChannelId(e.target.value)}
                              placeholder="留空监听所有频道"
                              className="h-9"
                            />
                            <p className="text-xs text-muted-foreground">
                              {discordChannelId ? "只监听指定频道" : "监听所有频道"}
                            </p>
                          </div>
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">相似度阈值</Label>
                            <Input
                              type="number"
                              min="0"
                              max="1"
                              step="0.05"
                              value={discordThreshold}
                              onChange={(e) => setDiscordThreshold(parseFloat(e.target.value) || 0.4)}
                              className="h-9"
                            />
                            <p className="text-xs text-muted-foreground">
                              相似度高于 {discordThreshold * 100}% 时才回复
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* 回复设置 */}
                      <div className="space-y-4">
                        <h4 className="text-sm font-medium">回复设置</h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">回复延迟范围</Label>
                            <div className="grid grid-cols-2 gap-2">
                              <Input
                                type="number"
                                min="0"
                                max="300"
                                step="0.1"
                                value={globalMinDelay}
                                onChange={(e) => setGlobalMinDelay(parseFloat(e.target.value) || 0)}
                                placeholder="最小延迟"
                                className="h-9"
                              />
                              <Input
                                type="number"
                                min="0"
                                max="300"
                                step="0.1"
                                value={globalMaxDelay}
                                onChange={(e) => setGlobalMaxDelay(parseFloat(e.target.value) || 0)}
                                placeholder="最大延迟"
                                className="h-9"
                              />
                            </div>
                            <p className="text-xs text-muted-foreground">
                              回复前随机延迟 {globalMinDelay}-{globalMaxDelay} 秒
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* 频道设置 */}
                      <div className="space-y-4">
                        <h4 className="text-sm font-medium">频道设置</h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">CNFans 频道ID</Label>
                            <Input
                              type="text"
                              value={cnfansChannelId}
                              onChange={(e) => setCnfansChannelId(e.target.value)}
                              placeholder="发送CNFans链接的频道ID"
                              className="h-9"
                            />
                            <p className="text-xs text-muted-foreground">
                              留空在所有频道发送CNFans链接
                            </p>
                          </div>
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">AcBuy 频道ID</Label>
                            <Input
                              type="text"
                              value={acbuyChannelId}
                              onChange={(e) => setAcbuyChannelId(e.target.value)}
                              placeholder="发送AcBuy链接的频道ID"
                              className="h-9"
                            />
                            <p className="text-xs text-muted-foreground">
                              留空在所有频道发送AcBuy链接
                            </p>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>


      </div>

    </div>
  )
}

