"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, Shield, User, Users, Edit, Trash2, Save, Search } from "lucide-react"
import { toast } from "sonner"

interface User {
  id: number
  username: string
  role: string
  shops: string[]
  is_active: boolean
  created_at: string
}

export function UsersView() {
  const [users, setUsers] = useState<User[]>([])
  const [shops, setShops] = useState<any[]>([])
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [newUser, setNewUser] = useState({
    username: "",
    password: "",
    role: "user",
    shops: [] as string[]
  })
  const [loading, setLoading] = useState(true)

  const [resetPasswordUser, setResetPasswordUser] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [deleteUserConfirm, setDeleteUserConfirm] = useState<User | null>(null)

  // Pagination State
  const [page, setPage] = useState(1)
  const itemsPerPage = 10
  const [searchKeyword, setSearchKeyword] = useState('')

  // 过滤用户列表
  const filteredUsers = users.filter(user =>
    user.username?.toLowerCase().includes(searchKeyword.toLowerCase()) ||
    user.role?.toLowerCase().includes(searchKeyword.toLowerCase())
  )

  // 计算分页数据
  const paginatedUsers = filteredUsers.slice((page-1)*itemsPerPage, page*itemsPerPage)
  const totalPages = Math.ceil(filteredUsers.length / itemsPerPage)

  useEffect(() => {
    fetchUsers()
    fetchShops()
  }, [])

  const fetchUsers = async () => {
    try {
      const response = await fetch('/api/users')
      if (response.ok) {
        const data = await response.json()
        setUsers(data.users || [])
      }
    } catch (error) {
      console.error('Failed to fetch users:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchShops = async () => {
    try {
      const response = await fetch('/api/shops')
      if (response.ok) {
        const data = await response.json()
        setShops(data.shops || [])
      }
    } catch (error) {
      console.error('Failed to fetch shops:', error)
    }
  }

  const handleCreateUser = async () => {
    if (!newUser.username || !newUser.password) {
      toast.error("请输入用户名和密码")
      return
    }

    try {
      const response = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newUser)
      })

      if (response.ok) {
        const data = await response.json()
        setUsers([...users, data.user])
        toast.success("用户创建成功")
        setIsDialogOpen(false)
        setNewUser({ username: "", password: "", role: "user", shops: [] })
      } else {
        const error = await response.json()
        toast.error(error.error || "创建用户失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const handleDeleteUser = (user: User) => {
    setDeleteUserConfirm(user)
  }

  const confirmDeleteUser = async () => {
    if (!deleteUserConfirm) return

    try {
      const response = await fetch(`/api/users/${deleteUserConfirm.id}`, {
        method: 'DELETE'
      })

      if (response.ok) {
        setUsers(users.filter(u => u.id !== deleteUserConfirm.id))
        toast.success("用户删除成功")
        setDeleteUserConfirm(null)
      } else {
        const error = await response.json()
        toast.error(error.error || "删除用户失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const handleResetPassword = async () => {
      if (!resetPasswordUser || !newPassword) return
      try {
          const res = await fetch(`/api/users/${resetPasswordUser.id}/password`, {
              method: 'PUT',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ password: newPassword })
          })
          if (res.ok) {
              toast.success("密码修改成功")
              setResetPasswordUser(null)
              setNewPassword("")
          } else {
              toast.error("修改失败")
          }
      } catch(e) { toast.error("网络错误") }
  }

  const handleUpdateUserShops = async (userId: number, shopIds: string[]) => {
    try {
      const response = await fetch(`/api/users/${userId}/shops`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shops: shopIds })
      })

      if (response.ok) {
        setUsers(users.map(u => u.id === userId ? { ...u, shops: shopIds } : u))
        toast.success("权限更新成功")
        setEditingUser(null)
      } else {
        toast.error("权限更新失败")
      }
    } catch (error) {
      toast.error("网络错误，请重试")
    }
  }

  const getShopNames = (shopIds: string[]) => {
    return shopIds.map(id => {
      const shop = shops.find(s => s.shop_id === id)
      return shop ? shop.name : id
    }).join(', ')
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">用户权限管理</h2>
          <p className="text-sm text-muted-foreground mt-1">创建用户并分配店铺管理权限</p>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 size-5" />
              创建用户
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="text-xl">创建新用户</DialogTitle>
              <DialogDescription>设置用户名、密码和权限</DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>用户名</Label>
                <Input
                  value={newUser.username}
                  onChange={(e) => setNewUser({...newUser, username: e.target.value})}
                  placeholder="请输入用户名"
                />
              </div>
              <div className="space-y-2">
                <Label>密码</Label>
                <Input
                  type="password"
                  value={newUser.password}
                  onChange={(e) => setNewUser({...newUser, password: e.target.value})}
                  placeholder="请输入密码"
                />
              </div>
              <div className="space-y-2">
                <Label>角色</Label>
                <Select value={newUser.role} onValueChange={(value) => setNewUser({...newUser, role: value})}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">普通用户</SelectItem>
                    <SelectItem value="admin">管理员</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>管理的店铺</Label>
                <div className="max-h-32 overflow-y-auto border rounded p-2 space-y-2">
                  {shops.map(shop => (
                    <div key={shop.shop_id} className="flex items-center space-x-2">
                      <Checkbox
                        id={shop.shop_id}
                        checked={newUser.shops.includes(shop.shop_id)}
                        onCheckedChange={(checked) => {
                          if (checked) {
                            setNewUser({...newUser, shops: [...newUser.shops, shop.shop_id]})
                          } else {
                            setNewUser({...newUser, shops: newUser.shops.filter(id => id !== shop.shop_id)})
                          }
                        }}
                      />
                      <Label htmlFor={shop.shop_id} className="text-sm">{shop.name}</Label>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setIsDialogOpen(false)}>取消</Button>
              <Button onClick={handleCreateUser}>创建用户</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="py-5 border-b">
          <CardTitle className="text-2xl font-bold">用户列表</CardTitle>
          <CardDescription className="text-sm">
            共 {users.length} 个用户
          </CardDescription>
        </CardHeader>

        {/* 搜索工具栏 */}
        {users.length > 0 && (
          <div className="px-6 py-4 border-b bg-muted/10">
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
              <div className="flex-1">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="搜索用户名或角色..."
                    value={searchKeyword}
                    onChange={(e) => setSearchKeyword(e.target.value)}
                    className="pl-10 h-9 w-full sm:w-[300px]"
                  />
                </div>
              </div>
            </div>

            {/* 搜索结果状态 */}
            {searchKeyword && (
              <div className="mt-3 text-sm text-muted-foreground">
                搜索结果: <span className="font-medium">{filteredUsers.length}</span> 个用户
                <span className="ml-2">关键词: <span className="font-medium">"{searchKeyword}"</span></span>
              </div>
            )}
          </div>
        )}
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50 h-12">
                <TableHead className="text-sm font-bold text-foreground pl-6">用户名</TableHead>
                <TableHead className="text-sm font-bold text-foreground">角色</TableHead>
                <TableHead className="text-sm font-bold text-foreground">管理店铺</TableHead>
                <TableHead className="text-sm font-bold text-foreground">状态</TableHead>
                <TableHead className="text-sm font-bold text-foreground text-right pr-6">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedUsers.map((user) => (
                <TableRow key={user.id} className="h-16 hover:bg-muted/30 transition-colors">
                  <TableCell className="font-medium py-3 pl-6">
                    <div className="flex items-center gap-2">
                      {user.role === 'admin' ? (
                        <Shield className="size-4 text-blue-600" />
                      ) : (
                        <User className="size-4 text-gray-600" />
                      )}
                      <span className="text-base font-semibold">{user.username}</span>
                    </div>
                  </TableCell>
                  <TableCell className="py-3">
                    {user.role === 'admin' ? (
                      <Badge className="bg-blue-600">管理员</Badge>
                    ) : (
                      <Badge variant="secondary">普通用户</Badge>
                    )}
                  </TableCell>
                  <TableCell className="py-3">
                    <div className="text-sm max-w-xs truncate" title={getShopNames(user.shops)}>
                      {user.shops.length > 0 ? getShopNames(user.shops) : "无"}
                    </div>
                  </TableCell>
                  <TableCell className="py-3">
                    {user.is_active ? (
                      <Badge className="bg-green-600">活跃</Badge>
                    ) : (
                      <Badge variant="secondary">禁用</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right pr-6 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setResetPasswordUser(user)}
                      >
                        修改密码
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditingUser(user)}
                      >
                        <Edit className="size-4 mr-1" />
                        权限
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDeleteUser(user)}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="size-4 mr-1" />
                        删除
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 编辑用户权限对话框 */}
      {editingUser && (
        <Dialog open={!!editingUser} onOpenChange={() => setEditingUser(null)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>编辑用户权限 - {editingUser.username}</DialogTitle>
              <DialogDescription>修改用户管理的店铺权限</DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>管理的店铺</Label>
                <div className="max-h-48 overflow-y-auto border rounded p-3 space-y-2">
                  {shops.map(shop => (
                    <div key={shop.shop_id} className="flex items-center space-x-2">
                      <Checkbox
                        id={`edit-${shop.shop_id}`}
                        checked={editingUser.shops.includes(shop.shop_id)}
                        onCheckedChange={(checked) => {
                          const newShops = checked
                            ? [...editingUser.shops, shop.shop_id]
                            : editingUser.shops.filter(id => id !== shop.shop_id)
                          setEditingUser({...editingUser, shops: newShops})
                        }}
                      />
                      <Label htmlFor={`edit-${shop.shop_id}`} className="text-sm">{shop.name}</Label>
                    </div>
                  ))}
                </div>
                {shops.length === 0 && (
                  <p className="text-sm text-muted-foreground">暂无店铺，请先添加店铺</p>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setEditingUser(null)}>取消</Button>
              <Button onClick={() => handleUpdateUserShops(editingUser.id, editingUser.shops)}>
                <Save className="size-4 mr-1" />
                保存权限
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {/* 分页控件 */}
      {totalPages > 1 && (
        <div className="flex flex-col sm:flex-row justify-between items-center gap-4 mt-6 px-6 py-4 border-t bg-muted/5">
          <div className="text-sm text-muted-foreground font-medium">
            显示第 {(page-1)*itemsPerPage + 1} - {Math.min(page*itemsPerPage, filteredUsers.length)} 条，共 {filteredUsers.length} 条记录
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page===1}
                onClick={()=>setPage(p=>p-1)}
                className="h-8 px-3"
              >
                上一页
              </Button>
              <div className="text-sm font-medium bg-primary text-primary-foreground px-3 py-1 rounded">
                {page} / {totalPages}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={page===totalPages}
                onClick={()=>setPage(p=>p+1)}
                className="h-8 px-3"
              >
                下一页
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Reset Password Dialog */}
      <Dialog open={!!resetPasswordUser} onOpenChange={()=>setResetPasswordUser(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重置密码 - {resetPasswordUser?.username}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Label>新密码</Label>
            <Input type="password" value={newPassword} onChange={e=>setNewPassword(e.target.value)} />
          </div>
          <DialogFooter>
            <Button onClick={handleResetPassword}>确认修改</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除用户确认对话框 */}
      <Dialog open={!!deleteUserConfirm} onOpenChange={() => setDeleteUserConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除用户</DialogTitle>
            <DialogDescription>
              确定要删除用户 "{deleteUserConfirm?.username}" 吗？此操作不可恢复！
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteUserConfirm(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDeleteUser}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
