"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Store, Package, ImageIcon, Users, Megaphone, Plus, Edit, Trash2 } from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

interface SystemStats {
  shop_count: number
  product_count: number
  image_count: number
  user_count: number
}

interface Announcement {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
}

export function DashboardView({ currentUser }: { currentUser: any }) {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [announcements, setAnnouncements] = useState<Announcement[]>([])
  const [showAddAnnouncement, setShowAddAnnouncement] = useState(false)
  const [editingAnnouncement, setEditingAnnouncement] = useState<Announcement | null>(null)
  const [newAnnouncement, setNewAnnouncement] = useState({
    title: '',
    content: ''
  })

  useEffect(() => {
    fetchStats()
    if (currentUser?.role === 'admin') {
      fetchAnnouncements()
    }

    // 每10秒自动刷新统计数据
    const statsInterval = setInterval(() => {
      fetchStats()
    }, 10000)

    return () => {
      clearInterval(statsInterval)
    }
  }, [currentUser])

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/system/stats')
      if (res.ok) {
        const data = await res.json()
        console.log('统计数据:', data)
        setStats(data)
      } else {
        console.error('获取统计信息失败:', res.status, res.statusText)
      }
    } catch (e) {
      console.error('获取统计信息失败:', e)
    }
  }

  const fetchAnnouncements = async () => {
    try {
      const res = await fetch('/api/announcements')
      if (res.ok) {
        const data = await res.json()
        setAnnouncements(data.announcements || [])
      }
    } catch (e) {
      console.error('获取公告失败:', e)
    }
  }

  const handleAddAnnouncement = async () => {
    try {
      const res = await fetch('/api/announcements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAnnouncement)
      })
      if (res.ok) {
        toast.success('公告添加成功')
        setShowAddAnnouncement(false)
        setNewAnnouncement({ title: '', content: '' })
        fetchAnnouncements()
      } else {
        toast.error('添加失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleUpdateAnnouncement = async () => {
    if (!editingAnnouncement) return
    try {
      const res = await fetch(`/api/announcements/${editingAnnouncement.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editingAnnouncement.title,
          content: editingAnnouncement.content,
          is_active: true
        })
      })
      if (res.ok) {
        toast.success('公告更新成功')
        setEditingAnnouncement(null)
        fetchAnnouncements()
      } else {
        toast.error('更新失败')
      }
    } catch (e) {
      toast.error('网络错误')
    }
  }

  const handleDeleteAnnouncement = async (announcement: Announcement) => {
    if (!confirm(`确定要删除公告 "${announcement.title}" 吗？`)) return
    try {
      const res = await fetch(`/api/announcements/${announcement.id}`, { method: 'DELETE' })
      if (res.ok) {
        toast.success('公告删除成功')
        fetchAnnouncements()
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
        <h2 className="text-4xl font-bold tracking-tight">仪表盘</h2>
        <p className="text-muted-foreground mt-2">系统概览和公告管理</p>
      </div>

      {/* 统计信息 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">店铺数量</CardTitle>
            <Store className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.shop_count ?? 0}</div>
            <p className="text-xs text-muted-foreground">已收录的店铺</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">商品数量</CardTitle>
            <Package className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.product_count ?? 0}</div>
            <p className="text-xs text-muted-foreground">已抓取的商品</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">图片数量</CardTitle>
            <ImageIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.image_count ?? 0}</div>
            <p className="text-xs text-muted-foreground">已索引的图片</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">用户数量</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.user_count ?? 0}</div>
            <p className="text-xs text-muted-foreground">活跃用户</p>
          </CardContent>
        </Card>
      </div>

      {/* 公告管理 - 所有用户可见，但只有管理员可修改 */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle className="flex items-center">
                <Megaphone className="w-5 h-5 mr-2" />
                系统公告
              </CardTitle>
              <CardDescription>查看最新系统通知</CardDescription>
            </div>
            {currentUser?.role === 'admin' && (
              <Dialog open={showAddAnnouncement} onOpenChange={setShowAddAnnouncement}>
                <DialogTrigger asChild>
                  <Button size="sm">
                    <Plus className="w-4 h-4 mr-2" />
                    添加公告
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>添加系统公告</DialogTitle>
                    <DialogDescription>创建新的系统公告</DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div>
                      <Label>公告标题</Label>
                      <Input
                        value={newAnnouncement.title}
                        onChange={e => setNewAnnouncement(prev => ({ ...prev, title: e.target.value }))}
                        placeholder="请输入公告标题"
                      />
                    </div>
                    <div>
                      <Label>公告内容</Label>
                      <Textarea
                        value={newAnnouncement.content}
                        onChange={e => setNewAnnouncement(prev => ({ ...prev, content: e.target.value }))}
                        placeholder="请输入公告内容"
                        rows={4}
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={() => setShowAddAnnouncement(false)}>取消</Button>
                    <Button onClick={handleAddAnnouncement}>添加公告</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {announcements.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                暂无公告
              </div>
            ) : (
              announcements.map((announcement) => (
                <div key={announcement.id} className="border rounded-lg p-4">
                  <div className="flex justify-between items-start mb-2">
                    <h4 className="font-semibold">{announcement.title}</h4>
                    {currentUser?.role === 'admin' && (
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setEditingAnnouncement(announcement)}
                        >
                          <Edit className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDeleteAnnouncement(announcement)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mb-2">{announcement.content}</p>
                  <div className="text-xs text-muted-foreground">
                    更新时间: {new Date(announcement.updated_at).toLocaleString('zh-CN')}
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>

      {/* 编辑公告对话框 */}
      {editingAnnouncement && (
        <Dialog open={!!editingAnnouncement} onOpenChange={() => setEditingAnnouncement(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>编辑公告</DialogTitle>
              <DialogDescription>修改公告内容</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label>公告标题</Label>
                <Input
                  value={editingAnnouncement.title}
                  onChange={e => setEditingAnnouncement(prev => ({ ...prev, title: e.target.value }))}
                />
              </div>
              <div>
                <Label>公告内容</Label>
                <Textarea
                  value={editingAnnouncement.content}
                  onChange={e => setEditingAnnouncement(prev => ({ ...prev, content: e.target.value }))}
                  rows={4}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setEditingAnnouncement(null)}>取消</Button>
              <Button onClick={handleUpdateAnnouncement}>保存修改</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
