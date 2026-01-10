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
import { Plus, RefreshCw, Trash2, MessageCircle, Save } from "lucide-react"
import { toast } from "sonner"

export function AccountsView() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [newToken, setNewToken] = useState("")
  const [rotationEnabled, setRotationEnabled] = useState(false)
  const [rotationInterval, setRotationInterval] = useState(10)
  const [discordThreshold, setDiscordThreshold] = useState(0.4)
  const [globalMinDelay, setGlobalMinDelay] = useState(3)
  const [globalMaxDelay, setGlobalMaxDelay] = useState(8)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchAccounts()
    fetchRotationConfig()
    fetchGlobalDelay()
    fetchDiscordThreshold()
  }, [])

  const fetchAccounts = async () => {
    try {
      const response = await fetch('/api/accounts')
      if (response.ok) {
        const data = await response.json()
        setAccounts(data)
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
          <Button variant="outline" onClick={() => toast.info("正在验证所有 Token...")}>
            <RefreshCw className="mr-2 size-5" />
            重新验证所有
          </Button>
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <Card className="lg:col-span-2 shadow-sm">
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
                        <span className="text-xs text-muted-foreground font-mono">{account.token.substring(0, 20)}...</span>
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
          </CardContent>
        </Card>

        <Card className="shadow-sm border-2 border-primary/10">
          <CardHeader className="py-5 border-b bg-primary/5">
            <CardTitle className="text-2xl font-bold">全局轮换设置</CardTitle>
            <CardDescription className="text-sm">配置多账号自动切换逻辑</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 pt-6">
            <div className="flex items-center justify-between space-x-2 border-b pb-5">
              <div className="space-y-1">
                <Label className="text-base font-bold">启用账号轮换</Label>
                <p className="text-xs text-muted-foreground">
                  触发频率限制时自动切换账号
                </p>
              </div>
              <Switch
                className="scale-110"
                checked={rotationEnabled}
                onCheckedChange={setRotationEnabled}
              />
            </div>
            
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <Label className="text-sm font-bold">轮换间隔 (秒)</Label>
                <span className="text-sm font-mono font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded">{rotationInterval}s</span>
              </div>
              <Input 
                type="number" 
                value={rotationInterval} 
                onChange={(e) => setRotationInterval(parseInt(e.target.value) || 0)}
                disabled={!rotationEnabled}
                min={1}
                className="h-10 text-base"
              />
            </div>

            <div className="pt-2">
              <div className="bg-muted p-4 rounded-xl border">
                <div className="text-xs space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground font-medium">活跃轮换池:</span>
                    <span className="font-bold text-sm">{accounts.filter(a => a.status === 'online').length} 个</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground font-medium">轮换模式:</span>
                    <span className={`font-bold text-sm ${rotationEnabled ? "text-green-600" : "text-gray-400"}`}>
                      {rotationEnabled ? "已激活运行" : "未开启"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            
            <Button className="w-full h-11 text-sm font-bold shadow-sm" variant="default" onClick={async () => {
              try {
                const response = await fetch('/api/accounts/rotation', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    enabled: rotationEnabled,
                    rotationInterval: rotationInterval
                  })
                })

                if (response.ok) {
                  toast.success("全局配置已保存");
                } else {
                  toast.error("保存配置失败");
                }
              } catch (error) {
                toast.error("网络错误，请重试");
              }
            }}>
              保存设置并应用
            </Button>
          </CardContent>
        </Card>

        <Card className="shadow-sm border-2 border-purple-200/50">
          <CardHeader className="py-5 border-b bg-purple-50/50">
            <CardTitle className="text-2xl font-bold flex items-center gap-2">
              <MessageCircle className="size-6 text-purple-600" />
              Discord 机器人配置
            </CardTitle>
            <CardDescription className="text-sm">Discord自动回复参数和全局延迟设置</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 pt-6">
            {/* 主要配置区域 */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Discord阈值设置 */}
              <div className="space-y-3">
                <Label className="text-sm font-bold flex items-center gap-2">
                  🎯 相似度阈值
                  <Badge className="bg-purple-600 hover:bg-purple-700 text-xs">
                    {(discordThreshold * 100).toFixed(0)}%
                  </Badge>
                </Label>
                <div className="space-y-2">
                  <Input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={discordThreshold}
                    onChange={(e) => setDiscordThreshold(parseFloat(e.target.value) || 0.4)}
                    className="h-10"
                    placeholder="0.4"
                  />
                  <p className="text-xs text-muted-foreground">
                    只有相似度超过此值的图片才会触发自动回复
                  </p>
                </div>
              </div>

              {/* 全局延迟设置 */}
              <div className="space-y-3">
                <Label className="text-sm font-bold flex items-center gap-2">
                  ⏱️ 全局回复延迟
                  <Badge className="bg-green-600 hover:bg-green-700 text-xs">
                    {globalMinDelay}-{globalMaxDelay}秒
                  </Badge>
                </Label>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs text-gray-600">最小</Label>
                    <Input
                      type="number"
                      min="0"
                      max="300"
                      value={globalMinDelay}
                      onChange={(e) => setGlobalMinDelay(parseInt(e.target.value) || 0)}
                      className="h-8 text-sm"
                      placeholder="3"
                    />
                  </div>
                  <div>
                    <Label className="text-xs text-gray-600">最大</Label>
                    <Input
                      type="number"
                      min="0"
                      max="300"
                      value={globalMaxDelay}
                      onChange={(e) => setGlobalMaxDelay(parseInt(e.target.value) || 0)}
                      className="h-8 text-sm"
                      placeholder="8"
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  自动回复将在此范围内随机延迟，避免被检测
                </p>
              </div>
            </div>


            {/* 保存按钮 */}
            <div className="flex gap-3">
              <Button
                className="flex-1 h-11 text-sm font-bold shadow-sm"
                variant="default"
                onClick={async () => {
                  try {
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

                    if (thresholdRes.ok && delayRes.ok) {
                      toast.success("Discord配置已保存")
                    } else {
                      toast.error("保存失败")
                    }
                  } catch (error) {
                    toast.error("网络错误，请重试")
                  }
                }}
              >
                <Save className="mr-2 size-4" />
                保存所有设置
              </Button>
            </div>
          </CardContent>
        </Card>

      </div>

    </div>
  )
}

