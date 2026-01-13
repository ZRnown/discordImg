"use client"

import { useState, useEffect } from "react"
import { useApiCache } from "@/hooks/use-api-cache"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { Plus, Settings, Save, Trash2, Globe, Link, Hash, X, Edit } from "lucide-react"

export function AccountsView() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [newAccount, setNewAccount] = useState({
    token: ""
  })
  const [settings, setSettings] = useState({
    discord_similarity_threshold: 0.6,
    global_reply_min_delay: 3.0,
    global_reply_max_delay: 8.0,
  })
  const [settingsLoading, setSettingsLoading] = useState(false)

  // 新增：当前用户信息状态
  const [currentUser, setCurrentUser] = useState<any>(null)
  const [deleteAccountConfirm, setDeleteAccountConfirm] = useState<any>(null)

  // 使用API缓存hook
  const { cachedFetch } = useApiCache()

  // 网站配置相关状态
  const [websites, setWebsites] = useState<any[]>([])
  const [showAddWebsite, setShowAddWebsite] = useState(false)
  const [editingWebsite, setEditingWebsite] = useState<any>(null)
  const [newWebsite, setNewWebsite] = useState({
    name: '',
    display_name: '',
    url_template: '',
    id_pattern: '',
    badge_color: 'blue'
  })
  const [websiteChannels, setWebsiteChannels] = useState<{[key: number]: string[]}>({})
  const [channelInputs, setChannelInputs] = useState<{[key: number]: string}>({})
  const [rotationEnabled, setRotationEnabled] = useState<{[key: number]: boolean}>({})
  const [rotationIntervals, setRotationIntervals] = useState<{[key: number]: number}>({})

  // 网站账号绑定相关状态
  const [websiteAccounts, setWebsiteAccounts] = useState<{[key: number]: any[]}>({})
  const [showBindAccount, setShowBindAccount] = useState<number | null>(null)
  const [newAccountBinding, setNewAccountBinding] = useState({
    account_id: '',
    role: 'both'
  })

  // 网站过滤规则相关状态
  const [websiteFilters, setWebsiteFilters] = useState<{[key: number]: any[]}>({})
  const [showAddWebsiteFilter, setShowAddWebsiteFilter] = useState<number | null>(null)

  // 消息过滤相关状态
  const [messageFilters, setMessageFilters] = useState<any[]>([])
  const [showAddFilter, setShowAddFilter] = useState(false)
  const [editingFilter, setEditingFilter] = useState<any>(null)
  const [newFilter, setNewFilter] = useState({
    filter_type: 'contains',
    filter_value: ''
  })


  const fetchWebsites = async () => {
    try {
      const data = await cachedFetch('/api/websites', { credentials: 'include' })
      const websites = data.websites || []

      // 后端已包含channels和accounts信息
        const channels: {[key: number]: string[]} = {}
      const accounts: {[key: number]: any[]} = {}
      const filters: {[key: number]: any[]} = {}

      // 并行获取所有网站的过滤规则
      const filterPromises = websites.map(async (website: any) => {
        try {
          const res = await fetch(`/api/websites/${website.id}/filters`, { credentials: 'include' })
          if (res.ok) {
            const data = await res.json()
            filters[website.id] = data.filters || []
          } else {
            filters[website.id] = []
          }
        } catch (e) {
          filters[website.id] = []
        }
      })

      websites.forEach((website: any) => {
        channels[website.id] = website.channels || []
        accounts[website.id] = website.accounts || []
      })

      // 等待所有过滤规则获取完成
      await Promise.all(filterPromises)

      setWebsites(websites)
        setWebsiteChannels(channels)
      setWebsiteAccounts(accounts)
      setWebsiteFilters(filters)
    } catch (e) {
      console.error('获取网站配置失败:', e)
    }
  }

  const fetchMessageFilters = async () => {
    try {
      const res = await fetch('/api/message-filters', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setMessageFilters(data.filters || [])
      }
    } catch (e) {
      console.error('获取消息过滤规则失败:', e)
    }
  }


  useEffect(() => {
    // 先获取当前用户，再决定是否获取用户列表
    const init = async () => {
        const userRes = await fetch('/api/auth/me', { credentials: 'include' });
        if (userRes.ok) {
            const userData = await userRes.json();
            setCurrentUser(userData.user);

            // 并行获取数据
            fetchAccounts(); // 所有人都能获取账号(自己的)

            // 只有管理员才获取用户列表
            if (userData.user.role === 'admin') {
                fetchUsers();
            }
        }
    };
    init();
    fetchSettings();
    fetchWebsites();
    fetchMessageFilters();
  }, [])

  const fetchSettings = async (usePreload: boolean = true) => {
    try {
      // 首先检查是否有预加载数据
      if (usePreload) {
        const preloadData = sessionStorage.getItem('preload_settings')
        if (preloadData) {
          try {
            console.log('使用预加载设置数据')
            const data = JSON.parse(preloadData)
            setSettings({
              discord_similarity_threshold: data.discord_similarity_threshold || 0.6,
              global_reply_min_delay: data.global_reply_min_delay || 3.0,
              global_reply_max_delay: data.global_reply_max_delay || 8.0,
            })

            // 清除预加载数据，避免重复使用
            sessionStorage.removeItem('preload_settings')

            // 在后台获取最新数据，但不显示加载状态
            setTimeout(() => fetchSettings(false), 500)
            return
          } catch (e) {
            console.error('预加载设置数据解析失败:', e)
            // 预加载数据损坏，清除并重新获取
            sessionStorage.removeItem('preload_settings')
          }
        } else {
          // 如果没有预加载数据，等待一下再试
          setTimeout(() => {
            const retryPreload = sessionStorage.getItem('preload_settings')
            if (retryPreload) {
              fetchSettings(true)
            } else {
              fetchSettings(false)
            }
          }, 200)
          return
        }
      }

      console.log('从API获取设置数据')
      const response = await fetch('/api/user/settings', {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setSettings({
          discord_similarity_threshold: data.discord_similarity_threshold || 0.6,
          global_reply_min_delay: data.global_reply_min_delay || 3.0,
          global_reply_max_delay: data.global_reply_max_delay || 8.0,
        })
      }
    } catch (error) {
      console.error('Failed to fetch settings:', error)
    }
  }

  const handleSaveSettings = async () => {
    setSettingsLoading(true)
    try {
      const response = await fetch('/api/user/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(settings)
      })

      if (response.ok) {
        toast.success("设置已保存")
      } else {
        toast.error("保存设置失败")
      }
    } catch (error) {
      toast.error("保存设置失败")
    } finally {
      setSettingsLoading(false)
    }
  }

  const fetchAccounts = async () => {
          try {
      console.log('获取账号列表...')
      const data = await cachedFetch('/api/accounts', { credentials: 'include' })
            setAccounts(data.accounts || [])
    } catch (error) {
      console.error('获取账号列表出错:', error)
      setAccounts([])
    } finally {
      setLoading(false)
    }
  }

  const fetchUsers = async () => {
    try {
      const response = await fetch('/api/users') // Next.js 会自动带上浏览器 Cookie
      if (response.ok) {
        const data = await response.json()
        setUsers(data.users || [])
      } else {
        // 不再抛出 toast 错误，而是静默失败或仅记录日志
        // 因为如果是权限不足，上面的逻辑应该已经拦截了，这里是兜底
        console.log('User fetch skipped or failed', response.status)
        setUsers([])
      }
    } catch (error) {
      setUsers([])
    }
  }

  const getUserDisplayName = (userId: number) => {
    const user = users.find(u => u.id === userId)
    return user ? user.username : `用户${userId}`
  }

  const handleAddAccount = async () => {
    if (!newAccount.token) {
      toast.error("请输入 Discord Token")
      return
    }

    try {
      const response = await fetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token: newAccount.token })
      })

      if (response.ok) {
        toast.success("账号添加成功")
        setNewAccount({ token: "" })
        setShowAddDialog(false)
        fetchAccounts()
      } else {
        const error = await response.json()
        toast.error(error.error || "添加账号失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const handleDeleteAccount = (account: any) => {
    setDeleteAccountConfirm(account)
  }

  const confirmDeleteAccount = async () => {
    if (!deleteAccountConfirm) return

    try {
      const response = await fetch(`/api/accounts/${deleteAccountConfirm.id}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        toast.success("账号删除成功")
        fetchAccounts()
        setDeleteAccountConfirm(null)
      } else {
        const error = await response.json()
        toast.error(error.error || "删除账号失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  // 网站配置处理函数
  const handleAddWebsite = async () => {
    try {
      const res = await fetch('/api/websites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newWebsite)
      })
      if (res.ok) {
        toast.success('网站配置已添加')
        setShowAddWebsite(false)
        setNewWebsite({ name: '', display_name: '', url_template: '', id_pattern: '', badge_color: 'blue' })
        fetchWebsites()
      } else {
        toast.error('添加失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleUpdateWebsite = async () => {
    if (!editingWebsite) return
    try {
      const res = await fetch(`/api/websites/${editingWebsite.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(editingWebsite)
      })
      if (res.ok) {
        toast.success('网站配置已更新')
        setEditingWebsite(null)
        fetchWebsites()
      } else {
        toast.error('更新失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleDeleteWebsite = async (website: any) => {
    if (!confirm(`确定要删除网站配置 "${website.display_name}" 吗？`)) return
    try {
      const res = await fetch(`/api/websites/${website.id}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        toast.success('网站配置已删除')
        fetchWebsites()
      } else {
        toast.error('删除失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleAddChannel = async (websiteId: number, channelId: string) => {
    if (!channelId.trim()) return
    try {
      const res = await fetch(`/api/websites/${websiteId}/channels`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ channel_id: channelId.trim() })
      })
      if (res.ok) {
        toast.success('频道绑定已添加')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteChannels(prev => ({
          ...prev,
          [websiteId]: [...(prev[websiteId] || []), channelId.trim()]
        }))
      } else {
        toast.error('添加失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleRemoveChannel = async (websiteId: number, channelId: string) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/channels/${channelId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        toast.success('频道绑定已移除')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteChannels(prev => ({
          ...prev,
          [websiteId]: prev[websiteId]?.filter(id => id !== channelId) || []
        }))
      } else {
        toast.error('移除失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  // 账号绑定处理函数
  const handleBindAccount = async (websiteId: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/accounts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newAccountBinding)
      })
      if (res.ok) {
        toast.success('账号绑定成功')
        setShowBindAccount(null)

        // 获取绑定的账号信息
        const boundAccount = accounts.find(acc => acc.id.toString() === newAccountBinding.account_id)
        if (boundAccount) {
          // 立即更新前端状态，而不是重新获取所有数据
          setWebsiteAccounts(prev => ({
            ...prev,
            [websiteId]: [...(prev[websiteId] || []), {
              id: Date.now(), // 临时ID，后端会返回真实ID
              account_id: parseInt(newAccountBinding.account_id),
              username: boundAccount.username,
              role: newAccountBinding.role
            }]
          }))
        }

        setNewAccountBinding({ account_id: '', role: 'both' })
      } else {
        const error = await res.json()
        toast.error(error.error || '绑定失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleUnbindAccount = async (websiteId: number, accountId: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/accounts/${accountId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        toast.success('账号解绑成功')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteAccounts(prev => ({
          ...prev,
          [websiteId]: prev[websiteId]?.filter(binding => binding.account_id !== accountId) || []
        }))
      } else {
        toast.error('解绑失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  // 轮换间隔设置
  const handleUpdateRotation = async (websiteId: number, rotationInterval: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/rotation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ rotation_interval: rotationInterval })
      })
      if (res.ok) {
        toast.success('轮换间隔已更新')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsites(prev => prev.map(website =>
          website.id === websiteId
            ? { ...website, rotation_interval: rotationInterval }
            : website
        ))
        // 同步更新本地输入框状态
        setRotationIntervals(prev => ({ ...prev, [websiteId]: rotationInterval }))
      } else {
        toast.error('更新失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  // 网站过滤规则管理
  const handleAddFilter = async (websiteId: number) => {
    try {
      // 首先获取当前网站的过滤规则
      const res = await fetch(`/api/websites/${websiteId}/filters`, { credentials: 'include' })
      if (!res.ok) {
        toast.error('获取当前过滤规则失败')
        return
      }

      const currentData = await res.json()
      const currentFilters = currentData.filters || []

      // 添加新规则
      const newFilters = [...currentFilters, {
        filter_type: newFilter.filter_type,
        filter_value: newFilter.filter_value
      }]

      // 更新过滤规则
      const updateRes = await fetch(`/api/websites/${websiteId}/filters`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ filters: newFilters })
      })

      if (updateRes.ok) {
        toast.success('过滤规则已添加')
        setNewFilter({ filter_type: 'contains', filter_value: '' })
        setShowAddWebsiteFilter(null)

        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteFilters(prev => ({
          ...prev,
          [websiteId]: newFilters
        }))
      } else {
        toast.error('添加过滤规则失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleRemoveWebsiteFilter = async (websiteId: number, filterIndex: number) => {
    try {
      // 获取当前网站的过滤规则
      const currentFilters = websiteFilters[websiteId] || []

      // 移除指定索引的规则
      const newFilters = currentFilters.filter((_, index) => index !== filterIndex)

      // 更新过滤规则
      const updateRes = await fetch(`/api/websites/${websiteId}/filters`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ filters: newFilters })
      })

      if (updateRes.ok) {
        toast.success('过滤规则已删除')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteFilters(prev => ({
          ...prev,
          [websiteId]: newFilters
        }))
      } else {
        toast.error('删除过滤规则失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  // 消息过滤处理函数
  const handleAddMessageFilter = async () => {
    try {
      const res = await fetch('/api/message-filters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newFilter)
      })
      if (res.ok) {
        toast.success('过滤规则添加成功')
        setShowAddFilter(false)
        setNewFilter({ filter_type: 'contains', filter_value: '' })
        fetchMessageFilters()
      } else {
        toast.error('添加失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleUpdateMessageFilter = async () => {
    if (!editingFilter) return
    try {
      const res = await fetch(`/api/message-filters/${editingFilter.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          filter_type: editingFilter.filter_type,
          filter_value: editingFilter.filter_value,
          is_active: editingFilter.is_active
        })
      })
      if (res.ok) {
        toast.success('过滤规则更新成功')
        setEditingFilter(null)
        fetchMessageFilters()
      } else {
        toast.error('更新失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleDeleteMessageFilter = async (filterId: number) => {
    if (!confirm('确定要删除这个过滤规则吗？')) return
    try {
      const res = await fetch(`/api/message-filters/${filterId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        toast.success('过滤规则删除成功')
        fetchMessageFilters()
      } else {
        toast.error('删除失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }


  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-4xl font-extrabold tracking-tight">账号管理</h2>
        <p className="text-sm text-muted-foreground mt-1">管理 Discord 账号</p>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="text-xl font-bold">账号列表</h3>
            <p className="text-sm text-gray-600 mt-1">
              共 {accounts.length} 个账号
            </p>
          </div>
          <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="w-4 h-4 mr-2" />
                添加账号
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>添加 Discord 账号</DialogTitle>
                <DialogDescription>
                  输入 Discord Token，系统将自动验证并获取用户名
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="token">Discord Token</Label>
                  <Input
                    id="token"
                    type="password"
                    value={newAccount.token}
                    onChange={(e) => setNewAccount(prev => ({ ...prev, token: e.target.value }))}
                    placeholder="输入 Discord Token"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Token 将被安全存储，系统会自动验证有效性
                  </p>
                </div>
              </div>
              <DialogFooter>
                <Button onClick={handleAddAccount}>添加账号</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>

        <div className="space-y-2">
          {accounts.map((account) => (
            <div key={account.id} className="flex justify-between items-center p-4 border rounded">
              <div className="flex-1">
                <div className="font-semibold">{account.username}</div>
                <div className="text-sm text-gray-500">
                  {account.user_id ? `所属用户: ${getUserDisplayName(account.user_id)}` : '未分配用户'}
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  {account.token && typeof account.token === 'string' ? `${account.token.substring(0, 20)}...` : 'Token 无效'}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className={`px-2 py-1 rounded text-sm ${
                  account.status === 'online' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                }`}>
                  {account.status === 'online' ? '在线' : '离线'}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDeleteAccount(account)}
                  className="text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>


      {/* 设置区域 */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h3 className="text-xl font-bold flex items-center">
              <Settings className="w-5 h-5 mr-2" />
              个人设置
            </h3>
            <p className="text-sm text-gray-600 mt-1">配置您的个性化运行参数</p>
          </div>
          <Button onClick={handleSaveSettings} disabled={settingsLoading}>
            <Save className="w-4 h-4 mr-2" />
            {settingsLoading ? "保存中..." : "保存设置"}
          </Button>
        </div>

        {/* 系统参数设置 - 合并相似度和延迟设置 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">系统参数</CardTitle>
            <CardDescription>配置图片匹配和回复延迟参数</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* 相似度和延迟设置 - 紧凑布局 */}
            <div className="flex flex-col sm:flex-row gap-6">
              {/* 相似度设置 */}
              <div className="flex-1 space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="similarity-threshold" className="text-sm font-medium">相似度阈值</Label>
                  <span className="text-sm font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded">
                    {(settings.discord_similarity_threshold * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="space-y-1">
                  <Input
                    id="similarity-threshold"
                    type="number"
                    step="0.1"
                    min="0.1"
                    max="1.0"
                    value={settings.discord_similarity_threshold}
                    onChange={(e) => setSettings(prev => ({ ...prev, discord_similarity_threshold: parseFloat(e.target.value) }))}
                    className="h-9"
                  />
                  <p className="text-xs text-muted-foreground">
                    阈值越低匹配越宽松，建议范围 0.3-0.8
                  </p>
                </div>
              </div>

              {/* 回复延迟设置 */}
              <div className="flex-1 space-y-2">
                <Label className="text-sm font-medium">回复延迟</Label>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1">
                      <Input
                        id="min-delay"
                        type="number"
                        step="0.1"
                        min="0.1"
                        max="30"
                        value={settings.global_reply_min_delay}
                        onChange={(e) => setSettings(prev => ({ ...prev, global_reply_min_delay: parseFloat(e.target.value) }))}
                        className="w-16 h-9 text-center"
                      />
                      <span className="text-sm text-muted-foreground">-</span>
                      <Input
                        id="max-delay"
                        type="number"
                        step="0.5"
                        min="1"
                        max="60"
                        value={settings.global_reply_max_delay}
                        onChange={(e) => setSettings(prev => ({ ...prev, global_reply_max_delay: parseFloat(e.target.value) }))}
                        className="w-16 h-9 text-center"
                      />
                    </div>
                    <span className="text-xs text-muted-foreground">秒</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    每次回复随机延迟 {settings.global_reply_min_delay}-{settings.global_reply_max_delay} 秒
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>


        {/* 编辑网站对话框 */}
        {editingWebsite && (
          <Dialog open={!!editingWebsite} onOpenChange={() => setEditingWebsite(null)}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>编辑网站配置</DialogTitle>
                <DialogDescription>修改网站配置信息</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label>网站标识</Label>
                  <Input
                    value={editingWebsite.name}
                    onChange={e => setEditingWebsite(prev => ({ ...prev, name: e.target.value }))}
                  />
                </div>
                <div>
                  <Label>显示名称</Label>
                  <Input
                    value={editingWebsite.display_name}
                    onChange={e => setEditingWebsite(prev => ({ ...prev, display_name: e.target.value }))}
                  />
                </div>
                <div>
                  <Label>URL模板</Label>
                  <Input
                    value={editingWebsite.url_template}
                    onChange={e => setEditingWebsite(prev => ({ ...prev, url_template: e.target.value }))}
                  />
                </div>
                <div>
                  <Label>ID提取模式</Label>
                  <Input
                    value={editingWebsite.id_pattern}
                    onChange={e => setEditingWebsite(prev => ({ ...prev, id_pattern: e.target.value }))}
                  />
                </div>
                <div>
                  <Label>徽章颜色</Label>
                  <Select value={editingWebsite?.badge_color || 'blue'} onValueChange={value => setEditingWebsite(prev => ({ ...prev, badge_color: value }))}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="blue">蓝色</SelectItem>
                      <SelectItem value="green">绿色</SelectItem>
                      <SelectItem value="orange">橙色</SelectItem>
                      <SelectItem value="red">红色</SelectItem>
                      <SelectItem value="purple">紫色</SelectItem>
                      <SelectItem value="gray">灰色</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditingWebsite(null)}>取消</Button>
                <Button onClick={handleUpdateWebsite}>保存</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}

        {/* 消息过滤设置 */}
        {currentUser?.role === 'admin' && (
          <Card className="mt-6">
            <CardHeader>
              <div className="flex justify-between items-center">
                <div>
                  <CardTitle className="text-lg">消息过滤</CardTitle>
                  <CardDescription>设置账号不回复的消息内容规则</CardDescription>
                </div>
                <Dialog open={showAddFilter} onOpenChange={setShowAddFilter}>
                  <DialogTrigger asChild>
                    <Button size="sm">
                      <Plus className="w-4 h-4 mr-2" />
                      添加过滤规则
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>添加消息过滤规则</DialogTitle>
                      <DialogDescription>设置账号忽略的消息类型</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div>
                        <Label>过滤类型</Label>
                        <Select value={newFilter.filter_type} onValueChange={value => setNewFilter(prev => ({ ...prev, filter_type: value }))}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="contains">包含文本</SelectItem>
                            <SelectItem value="starts_with">开头是</SelectItem>
                            <SelectItem value="ends_with">结尾是</SelectItem>
                            <SelectItem value="regex">正则表达式</SelectItem>
                            <SelectItem value="user_id">用户ID</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>过滤值</Label>
                        <Input
                          value={newFilter.filter_value}
                          onChange={e => setNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                          placeholder={
                            newFilter.filter_type === 'user_id'
                              ? "输入用户ID，多个用逗号分隔"
                              : "输入要过滤的内容"
                          }
                        />
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setShowAddFilter(false)}>取消</Button>
                      <Button onClick={handleAddMessageFilter}>添加规则</Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {messageFilters.map((filter: any) => (
                  <div key={filter.id} className="flex items-center justify-between p-3 border rounded">
                    <div>
                      <div className="font-medium">{filter.filter_type} "{filter.filter_value}"</div>
                      <div className="text-sm text-muted-foreground">
                        创建时间: {new Date(filter.created_at).toLocaleString('zh-CN')}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditingFilter(filter)}
                      >
                        <Edit className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDeleteMessageFilter(filter.id)}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                {messageFilters.length === 0 && (
                  <div className="text-center py-4 text-muted-foreground">
                    暂无过滤规则
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 网站配置区域 - 移除最外层的 admin 检查，改为内部细粒度控制 */}
        <Card className="mt-6">
          <CardHeader>
            <div className="flex justify-between items-center">
              <div>
                <CardTitle className="text-lg flex items-center">
                  <Globe className="w-5 h-5 mr-2" />
                  网站配置
                </CardTitle>
                <CardDescription>管理支持的购物网站和频道绑定</CardDescription>
              </div>
              {/* 只有管理员可以添加新网站 */}
              {currentUser?.role === 'admin' && (
                <Dialog open={showAddWebsite} onOpenChange={setShowAddWebsite}>
                  <DialogTrigger asChild>
                    <Button size="sm">
                      <Plus className="w-4 h-4 mr-2" />
                      添加网站
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>添加网站配置</DialogTitle>
                      <DialogDescription>配置新的购物网站支持</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div>
                        <Label>网站标识</Label>
                        <Input
                          value={newWebsite.name}
                          onChange={e => setNewWebsite(prev => ({ ...prev, name: e.target.value }))}
                          placeholder="例如: kakobuy"
                        />
                      </div>
                      <div>
                        <Label>显示名称</Label>
                        <Input
                          value={newWebsite.display_name}
                          onChange={e => setNewWebsite(prev => ({ ...prev, display_name: e.target.value }))}
                          placeholder="例如: Kakobuy"
                        />
                      </div>
                      <div>
                        <Label>URL模板</Label>
                        <Input
                          value={newWebsite.url_template}
                          onChange={e => setNewWebsite(prev => ({ ...prev, url_template: e.target.value }))}
                          placeholder="https://www.kakobuy.com/item/details?url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}&id={id}&source=WD"
                        />
                      </div>
                      <div>
                        <Label>ID提取模式</Label>
                        <Input
                          value={newWebsite.id_pattern}
                          onChange={e => setNewWebsite(prev => ({ ...prev, id_pattern: e.target.value }))}
                          placeholder="{id}"
                        />
                      </div>
                      <div>
                        <Label>徽章颜色</Label>
                        <Select value={newWebsite.badge_color} onValueChange={value => setNewWebsite(prev => ({ ...prev, badge_color: value }))}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="blue">蓝色</SelectItem>
                            <SelectItem value="green">绿色</SelectItem>
                            <SelectItem value="orange">橙色</SelectItem>
                            <SelectItem value="red">红色</SelectItem>
                            <SelectItem value="purple">紫色</SelectItem>
                            <SelectItem value="gray">灰色</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setShowAddWebsite(false)}>取消</Button>
                      <Button onClick={handleAddWebsite}>添加</Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              )}
            </div>
          </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {websites.map((website: any) => (
                  <div key={website.id} className="border rounded-lg p-4">
                    <div className="flex justify-between items-start mb-3">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center rounded-md border font-medium w-fit whitespace-nowrap text-[9px] px-1 py-0 h-4 border-none shrink-0 text-white ${
                          website.badge_color === 'blue' ? 'bg-blue-600' :
                          website.badge_color === 'green' ? 'bg-green-600' :
                          website.badge_color === 'orange' ? 'bg-orange-600' :
                          website.badge_color === 'red' ? 'bg-red-600' :
                          website.badge_color === 'purple' ? 'bg-purple-600' :
                          'bg-gray-600'
                        }`}>
                          {website.display_name}
                        </span>
                        <span className="text-sm font-medium">{website.name}</span>
                      </div>
                      {/* 只有管理员可以编辑/删除网站定义 */}
                      {currentUser?.role === 'admin' && (
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setEditingWebsite(website)}
                          >
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDeleteWebsite(website)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      )}
                    </div>

                    <div className="text-xs text-muted-foreground mb-3">
                      <div>URL模板: {website.url_template}</div>
                      <div>ID模式: {website.id_pattern}</div>
                    </div>

                    {/* 频道绑定 */}
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Hash className="w-4 h-4" />
                        <span className="text-sm font-medium">绑定频道</span>
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <Plus className="w-3 h-3 mr-1" />
                              添加频道
                            </Button>
                          </DialogTrigger>
                          <DialogContent>
                            <DialogHeader>
                              <DialogTitle>添加频道绑定</DialogTitle>
                              <DialogDescription>输入Discord频道ID</DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4">
                              <div>
                                <Label>频道ID</Label>
                                <Input
                                  placeholder="例如: 1234567890123456789"
                                  value={channelInputs[website.id] || ''}
                                  onChange={(e) => setChannelInputs(prev => ({ ...prev, [website.id]: e.target.value }))}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' && channelInputs[website.id]?.trim()) {
                                      handleAddChannel(website.id, channelInputs[website.id].trim())
                                      setChannelInputs(prev => ({ ...prev, [website.id]: '' }))
                                    }
                                  }}
                                />
                              </div>
                            </div>
                            <DialogFooter>
                              <Button variant="outline" onClick={() => setChannelInputs(prev => ({ ...prev, [website.id]: '' }))}>取消</Button>
                              <Button onClick={() => {
                                if (channelInputs[website.id]?.trim()) {
                                  handleAddChannel(website.id, channelInputs[website.id].trim())
                                  setChannelInputs(prev => ({ ...prev, [website.id]: '' }))
                                }
                              }} disabled={!channelInputs[website.id]?.trim()}>添加</Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(websiteChannels[website.id] || []).map((channelId: string) => (
                          <div key={channelId} className="flex items-center gap-1 bg-muted rounded px-2 py-1">
                            <Hash className="w-3 h-3" />
                            <span className="text-xs font-mono">{channelId}</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-4 w-4 p-0"
                              onClick={() => handleRemoveChannel(website.id, channelId)}
                            >
                              <X className="w-3 h-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 账号绑定 */}
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Settings className="w-4 h-4" />
                        <span className="text-sm font-medium">绑定账号</span>
                        <Dialog open={showBindAccount === website.id} onOpenChange={(open) => {
                          setShowBindAccount(open ? website.id : null)
                          if (!open) setNewAccountBinding({ account_id: '', role: 'both' })
                        }}>
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <Plus className="w-3 h-3 mr-1" />
                              绑定账号
                            </Button>
                          </DialogTrigger>
                          <DialogContent>
                            <DialogHeader>
                              <DialogTitle>绑定Discord账号</DialogTitle>
                              <DialogDescription>选择账号并设置角色</DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4">
                              <div>
                                <Label>选择账号</Label>
                                <Select value={newAccountBinding.account_id} onValueChange={value => setNewAccountBinding(prev => ({ ...prev, account_id: value }))}>
                                  <SelectTrigger>
                                    <SelectValue placeholder="选择Discord账号" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {accounts.filter(account => !websiteAccounts[website.id]?.some(binding => binding.account_id === account.id)).map((account: any) => (
                                      <SelectItem key={account.id} value={account.id.toString()}>
                                        {account.username} ({account.status})
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                              <div>
                                <Label>账号角色</Label>
                                <Select value={newAccountBinding.role} onValueChange={value => setNewAccountBinding(prev => ({ ...prev, role: value }))}>
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="listener">监听 (只接收消息)</SelectItem>
                                    <SelectItem value="sender">发送 (只发送回复)</SelectItem>
                                    <SelectItem value="both">两者 (监听+发送)</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                            </div>
                            <DialogFooter>
                              <Button variant="outline" onClick={() => setShowBindAccount(null)}>取消</Button>
                              <Button onClick={() => handleBindAccount(website.id)} disabled={!newAccountBinding.account_id}>
                                绑定
                              </Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(websiteAccounts[website.id] || []).map((binding: any) => (
                          <div key={binding.id} className="flex items-center gap-1 bg-muted rounded px-2 py-1">
                            <span className="text-xs">{binding.username}</span>
                            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">
                              {binding.role === 'listener' ? '监听' : binding.role === 'sender' ? '发送' : '两者'}
                            </Badge>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-4 w-4 p-0"
                              onClick={() => handleUnbindAccount(website.id, binding.account_id)}
                            >
                              <X className="w-3 h-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 账号轮换设置 - 建议仅允许管理员修改全局策略，或者如果这属于用户级配置，需要数据库支持。
                        根据需求"普通用户不能更改网站的设置"，这里应该隐藏或禁用 */}
                    {currentUser?.role === 'admin' && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Settings className="w-4 h-4" />
                          <span className="text-sm font-medium">轮换设置 (全局)</span>
                        </div>

                        {/* 轮换启用开关 */}
                        <div className="flex items-center gap-2">
                          <Label className="text-xs">启用轮换:</Label>
                          <Switch
                            checked={rotationEnabled[website.id] ?? (website.rotation_enabled !== 0)}
                            onCheckedChange={(checked) => {
                              setRotationEnabled(prev => ({ ...prev, [website.id]: checked }))
                              // 发送API请求更新轮换启用状态
                              fetch(`/api/websites/${website.id}/rotation`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                credentials: 'include',
                                body: JSON.stringify({ rotation_enabled: checked ? 1 : 0 })
                              }).then(response => {
                                if (response.ok) {
                                  toast.success(`轮换功能已${checked ? '启用' : '禁用'}`)
                                } else {
                                  toast.error('更新失败')
                                  // 恢复开关状态
                                  setRotationEnabled(prev => ({ ...prev, [website.id]: !checked }))
                                }
                              }).catch(() => {
                                toast.error('网络错误')
                                // 恢复开关状态
                                setRotationEnabled(prev => ({ ...prev, [website.id]: !checked }))
                              })
                            }}
                          />
                        </div>

                        {/* 轮换间隔设置 */}
                        <div className="flex items-center gap-2">
                          <Label className="text-xs">轮换间隔(秒):</Label>
                          <Input
                            type="number"
                            value={rotationIntervals[website.id] ?? website.rotation_interval ?? 180}
                            className="w-20 h-7 text-xs"
                            disabled={!(rotationEnabled[website.id] ?? (website.rotation_enabled !== 0))}
                            onChange={(e) => {
                              const value = parseInt(e.target.value) || 180
                              setRotationIntervals(prev => ({ ...prev, [website.id]: value }))
                            }}
                            onBlur={(e) => {
                              const value = rotationIntervals[website.id] ?? website.rotation_interval ?? 180
                              if (value > 0 && value !== website.rotation_interval) {
                                handleUpdateRotation(website.id, value)
                              } else if (value <= 0) {
                                toast.error('轮换间隔必须大于0秒')
                                setRotationIntervals(prev => ({ ...prev, [website.id]: website.rotation_interval ?? 180 }))
                              }
                            }}
                          />
                          <span className="text-xs text-muted-foreground">
                            ({Math.floor((rotationIntervals[website.id] ?? website.rotation_interval ?? 180) / 60)}分{(rotationIntervals[website.id] ?? website.rotation_interval ?? 180) % 60}秒)
                          </span>
                        </div>

                        {/* 状态说明 */}
                        <div className="text-xs text-muted-foreground">
                          {(rotationEnabled[website.id] ?? (website.rotation_enabled !== 0))
                            ? '轮换已启用，将在账号间自动切换'
                            : '轮换已禁用，将使用固定账号发送'
                          }
                        </div>
                      </div>
                    )}

                    {/* 消息过滤规则 */}
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Settings className="w-4 h-4" />
                        <span className="text-sm font-medium">消息过滤</span>
                        <Dialog open={showAddWebsiteFilter === website.id} onOpenChange={(open) => {
                          setShowAddWebsiteFilter(open ? website.id : null)
                          if (!open) setNewFilter({ filter_type: 'contains', filter_value: '' })
                        }}>
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <Plus className="w-3 h-3 mr-1" />
                              添加规则
                            </Button>
                          </DialogTrigger>
                          <DialogContent>
                            <DialogHeader>
                              <DialogTitle>添加过滤规则</DialogTitle>
                              <DialogDescription>为网站设置特定的消息过滤规则</DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4">
                              <div>
                                <Label>过滤类型</Label>
                                <Select value={newFilter.filter_type} onValueChange={value => setNewFilter(prev => ({ ...prev, filter_type: value }))}>
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="contains">包含文本</SelectItem>
                                    <SelectItem value="starts_with">开头是</SelectItem>
                                    <SelectItem value="ends_with">结尾是</SelectItem>
                                    <SelectItem value="regex">正则表达式</SelectItem>
                                    <SelectItem value="user_id">用户ID</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                              <div>
                                <Label>过滤值</Label>
                                <Input
                                  value={newFilter.filter_value}
                                  onChange={e => setNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                                  placeholder="输入过滤条件"
                                />
                              </div>
                            </div>
                            <DialogFooter>
                              <Button variant="outline" onClick={() => setShowAddWebsiteFilter(null)}>取消</Button>
                              <Button onClick={() => handleAddFilter(website.id)}>添加</Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(websiteFilters[website.id] || []).map((filter: any, index: number) => (
                          <div key={index} className="flex items-center gap-1 bg-muted rounded px-2 py-1">
                            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">
                              {filter.filter_type === 'contains' ? '包含' :
                               filter.filter_type === 'starts_with' ? '开头' :
                               filter.filter_type === 'ends_with' ? '结尾' :
                               filter.filter_type === 'regex' ? '正则' : '用户ID'}
                            </Badge>
                            <span className="text-xs truncate max-w-20" title={filter.filter_value}>
                              {filter.filter_value}
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-4 w-4 p-0"
                              onClick={() => handleRemoveWebsiteFilter(website.id, index)}
                            >
                              <X className="w-3 h-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        网站特定的过滤规则 (独立于全局规则)
                      </div>
                    </div>

                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

        {/* 编辑消息过滤对话框 */}
        {editingFilter && (
          <Dialog open={!!editingFilter} onOpenChange={() => setEditingFilter(null)}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>编辑过滤规则</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label>过滤类型</Label>
                  <Select value={editingFilter.filter_type} onValueChange={value => setEditingFilter(prev => ({ ...prev, filter_type: value }))}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="contains">包含文本</SelectItem>
                      <SelectItem value="starts_with">开头是</SelectItem>
                      <SelectItem value="ends_with">结尾是</SelectItem>
                      <SelectItem value="regex">正则表达式</SelectItem>
                      <SelectItem value="user_id">用户ID</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>过滤值</Label>
                  <Input
                    value={editingFilter.filter_value}
                    onChange={e => setEditingFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditingFilter(null)}>取消</Button>
                <Button onClick={handleUpdateMessageFilter}>保存修改</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}


        {/* 删除账号确认对话框 */}
        <Dialog open={!!deleteAccountConfirm} onOpenChange={() => setDeleteAccountConfirm(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除账号</DialogTitle>
              <DialogDescription>
                确定要删除Discord账号 "{deleteAccountConfirm?.username}" 吗？此操作不可恢复。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteAccountConfirm(null)}>
                取消
              </Button>
              <Button variant="destructive" onClick={confirmDeleteAccount}>
                确认删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}
