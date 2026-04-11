"use client"

import { useEffect, useMemo, useState } from "react"
import { getApiErrorMessage } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { CalendarClock, ImageIcon, Pencil, Plus, Send, Trash2 } from "lucide-react"

type WebsitePostItem = {
  id: number
  title: string
  category: string
  content: string
  image_filenames: string[]
  image_urls: string[]
  is_active: number
}

type WebsitePostSchedule = {
  id: number
  channel_id: string
  category: string
  send_mode: "random" | "sequential"
  interval_minutes: number
  enabled: number
  last_sent_at?: string | null
}

type PostFormState = {
  title: string
  category: string
  content: string
  is_active: boolean
  existingImages: string[]
  newFiles: File[]
}

type ScheduleFormState = {
  channel_id: string
  category: string
  send_mode: "random" | "sequential"
  interval_minutes: string
  enabled: boolean
}

type DeleteTarget =
  | { type: "post"; id: number; label: string }
  | { type: "schedule"; id: number; label: string }

const createEmptyPostForm = (): PostFormState => ({
  title: "",
  category: "",
  content: "",
  is_active: true,
  existingImages: [],
  newFiles: [],
})

const createEmptyScheduleForm = (): ScheduleFormState => ({
  channel_id: "",
  category: "",
  send_mode: "random",
  interval_minutes: "60",
  enabled: true,
})

export function WebsitePostingPanel({
  website,
  onChanged,
}: {
  website: any
  onChanged?: () => Promise<void> | void
}) {
  const [loading, setLoading] = useState(true)
  const [posts, setPosts] = useState<WebsitePostItem[]>([])
  const [schedules, setSchedules] = useState<WebsitePostSchedule[]>([])
  const [categories, setCategories] = useState<string[]>(website?.post_categories || [])
  const [postDialogOpen, setPostDialogOpen] = useState(false)
  const [editingPost, setEditingPost] = useState<WebsitePostItem | null>(null)
  const [postForm, setPostForm] = useState<PostFormState>(createEmptyPostForm())
  const [scheduleEditorOpen, setScheduleEditorOpen] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<WebsitePostSchedule | null>(null)
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(createEmptyScheduleForm())
  const [savingPost, setSavingPost] = useState(false)
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null)
  const [deleting, setDeleting] = useState(false)

  const postCountLabel = useMemo(() => {
    if (loading) return "加载中"
    return `${posts.length} 条`
  }, [loading, posts.length])

  const scheduleCountLabel = useMemo(() => {
    if (loading) return "加载中"
    return `${schedules.length} 条`
  }, [loading, schedules.length])

  const notifyChanged = async (fallbackMessage = "刷新网站统计失败") => {
    if (!onChanged) return
    try {
      await onChanged()
    } catch (error) {
      toast.error(getApiErrorMessage(error, fallbackMessage))
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const [postRes, scheduleRes] = await Promise.all([
        fetch(`/api/websites/${website.id}/post-library`, {
          credentials: "include",
          cache: "no-store",
        }),
        fetch(`/api/websites/${website.id}/post-schedules`, {
          credentials: "include",
          cache: "no-store",
        }),
      ])

      const postData = await postRes.json().catch(() => ({}))
      const scheduleData = await scheduleRes.json().catch(() => ({}))

      if (!postRes.ok) {
        throw new Error(getApiErrorMessage(postData, "获取帖子库失败"))
      }
      if (!scheduleRes.ok) {
        throw new Error(getApiErrorMessage(scheduleData, "获取发帖方式失败"))
      }

      const nextPosts = postData.posts || []
      const nextSchedules = scheduleData.schedules || []
      setPosts(nextPosts)
      setSchedules(nextSchedules)
      const nextCategories = Array.from(new Set([
        ...(postData.categories || []),
        ...(scheduleData.categories || []),
        ...nextSchedules.map((item: WebsitePostSchedule) => item.category).filter(Boolean),
      ]))
      setCategories(nextCategories)
    } catch (error) {
      toast.error(getApiErrorMessage(error, "加载网站发帖配置失败"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [website.id])

  const resetPostDialog = () => {
    setEditingPost(null)
    setPostForm(createEmptyPostForm())
    setPostDialogOpen(false)
  }

  const resetScheduleEditor = () => {
    setEditingSchedule(null)
    setScheduleForm(createEmptyScheduleForm())
    setScheduleEditorOpen(false)
  }

  const closeDeleteDialog = () => {
    if (deleting) return
    setDeleteDialogOpen(false)
    setDeleteTarget(null)
  }

  const openCreatePostDialog = () => {
    setEditingPost(null)
    setPostForm(createEmptyPostForm())
    setPostDialogOpen(true)
  }

  const openEditPostDialog = (post: WebsitePostItem) => {
    setEditingPost(post)
    setPostForm({
      title: post.title || "",
      category: post.category || "",
      content: post.content || "",
      is_active: !!post.is_active,
      existingImages: [...(post.image_filenames || [])],
      newFiles: [],
    })
    setPostDialogOpen(true)
  }

  const openCreateScheduleEditor = () => {
    setEditingSchedule(null)
    setScheduleForm(createEmptyScheduleForm())
    setScheduleEditorOpen(true)
  }

  const openEditScheduleEditor = (schedule: WebsitePostSchedule) => {
    setEditingSchedule(schedule)
    setScheduleForm({
      channel_id: schedule.channel_id || "",
      category: schedule.category || "",
      send_mode: schedule.send_mode || "random",
      interval_minutes: String(schedule.interval_minutes || 60),
      enabled: !!schedule.enabled,
    })
    setScheduleEditorOpen(true)
  }

  const requestDeletePost = (post: WebsitePostItem) => {
    setDeleteTarget({
      type: "post",
      id: post.id,
      label: post.title || `帖子 ${post.id}`,
    })
    setDeleteDialogOpen(true)
  }

  const requestDeleteSchedule = (schedule: WebsitePostSchedule) => {
    setDeleteTarget({
      type: "schedule",
      id: schedule.id,
      label: schedule.channel_id || `发送方式 ${schedule.id}`,
    })
    setDeleteDialogOpen(true)
  }

  const deletePostById = async (postId: number) => {
    const response = await fetch(`/api/websites/${website.id}/post-library/${postId}`, {
      method: "DELETE",
      credentials: "include",
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(getApiErrorMessage(data, "删除帖子失败"))
    }
  }

  const deleteScheduleById = async (scheduleId: number) => {
    const response = await fetch(`/api/websites/${website.id}/post-schedules/${scheduleId}`, {
      method: "DELETE",
      credentials: "include",
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(getApiErrorMessage(data, "删除发送方式失败"))
    }
  }

  const confirmDeleteTarget = async () => {
    if (!deleteTarget) return

    setDeleting(true)
    try {
      if (deleteTarget.type === "post") {
        await deletePostById(deleteTarget.id)
        toast.success("帖子已删除")
      } else {
        await deleteScheduleById(deleteTarget.id)
        if (editingSchedule?.id === deleteTarget.id) {
          resetScheduleEditor()
        }
        toast.success("发送方式已删除")
      }
      closeDeleteDialog()
      await loadData()
      await notifyChanged()
    } catch (error) {
      toast.error(getApiErrorMessage(error, deleteTarget.type === "post" ? "删除帖子失败" : "删除发送方式失败"))
    } finally {
      setDeleting(false)
    }
  }

  const handleSavePost = async () => {
    if (!postForm.title.trim()) {
      toast.error("帖子名称不能为空")
      return
    }

    setSavingPost(true)
    try {
      const formData = new FormData()
      formData.append("title", postForm.title.trim())
      formData.append("category", postForm.category.trim())
      formData.append("content", postForm.content)
      formData.append("is_active", postForm.is_active ? "1" : "0")
      formData.append("existing_images", JSON.stringify(postForm.existingImages))
      postForm.newFiles.forEach(file => {
        formData.append("images", file)
      })

      const isEditing = !!editingPost
      const endpoint = isEditing
        ? `/api/websites/${website.id}/post-library/${editingPost!.id}`
        : `/api/websites/${website.id}/post-library`
      const method = isEditing ? "PUT" : "POST"

      const response = await fetch(endpoint, {
        method,
        credentials: "include",
        body: formData,
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, isEditing ? "更新帖子失败" : "添加帖子失败"))
      }

      toast.success(isEditing ? "帖子已更新" : "帖子已添加")
      resetPostDialog()
      await loadData()
      await notifyChanged()
    } catch (error) {
      toast.error(getApiErrorMessage(error, editingPost ? "更新帖子失败" : "添加帖子失败"))
    } finally {
      setSavingPost(false)
    }
  }

  const handleSaveSchedule = async () => {
    if (!scheduleForm.channel_id.trim()) {
      toast.error("频道 ID 不能为空")
      return
    }

    setSavingSchedule(true)
    try {
      const payload = {
        channel_id: scheduleForm.channel_id.trim(),
        category: scheduleForm.category.trim(),
        send_mode: scheduleForm.send_mode,
        interval_minutes: Number(scheduleForm.interval_minutes || 0),
        enabled: scheduleForm.enabled ? 1 : 0,
      }

      const isEditing = !!editingSchedule
      const endpoint = isEditing
        ? `/api/websites/${website.id}/post-schedules/${editingSchedule!.id}`
        : `/api/websites/${website.id}/post-schedules`
      const method = isEditing ? "PUT" : "POST"

      const response = await fetch(endpoint, {
        method,
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, isEditing ? "更新发送方式失败" : "添加发送方式失败"))
      }

      toast.success(isEditing ? "发送方式已更新" : "发送方式已添加")
      resetScheduleEditor()
      await loadData()
      await notifyChanged()
    } catch (error) {
      toast.error(getApiErrorMessage(error, editingSchedule ? "更新发送方式失败" : "添加发送方式失败"))
    } finally {
      setSavingSchedule(false)
    }
  }

  const showScheduleEditor = !loading && (scheduleEditorOpen || schedules.length === 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <ImageIcon className="w-4 h-4" />
            <span className="text-sm font-medium">帖子内容</span>
            <Badge variant="secondary">{postCountLabel}</Badge>
            <Badge variant="outline">发送方式 {scheduleCountLabel}</Badge>
          </div>
          <div className="text-xs text-muted-foreground">
            先维护帖子，再设置这些帖子要往哪里发、按随机还是顺序发、多久发一次。
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={openCreatePostDialog}>
            <Plus className="w-3 h-3 mr-1" />
            添加帖子
          </Button>
          <Button size="sm" variant="outline" onClick={openCreateScheduleEditor}>
            <CalendarClock className="w-3 h-3 mr-1" />
            {schedules.length > 0 ? "新增发送方式" : "设置发送方式"}
          </Button>
        </div>
      </div>

      {categories.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {categories.map(category => (
            <Badge key={category} variant="secondary">{category}</Badge>
          ))}
        </div>
      ) : null}

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <ImageIcon className="w-4 h-4" />
          <span className="text-sm font-medium">帖子内容</span>
          <Badge variant="secondary">{postCountLabel}</Badge>
        </div>

        {loading ? (
          <div className="text-sm text-muted-foreground">正在加载帖子库...</div>
        ) : posts.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            还没有帖子。先添加几条帖子，再设置这些帖子怎么发送。
          </div>
        ) : (
          <div className="space-y-2">
            {posts.map(post => (
              <div key={post.id} className="rounded-md border p-3 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{post.title}</span>
                      {post.category ? <Badge variant="outline">{post.category}</Badge> : null}
                      <Badge variant={post.is_active ? "default" : "secondary"}>
                        {post.is_active ? "启用" : "停用"}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground line-clamp-3 whitespace-pre-wrap break-words">
                      {post.content || "仅图片帖子"}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      图片 {post.image_filenames?.length || 0} 张
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button variant="outline" size="sm" onClick={() => openEditPostDialog(post)}>
                      <Pencil className="w-3 h-3" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => requestDeletePost(post)}>
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                </div>

                {post.image_urls?.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {post.image_urls.slice(0, 4).map((url, index) => (
                      <img
                        key={`${post.id}-${index}`}
                        src={url}
                        alt={`${post.title}-${index}`}
                        className="h-16 w-16 rounded border object-cover"
                      />
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-4 rounded-lg border border-dashed p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Send className="w-4 h-4" />
              <span className="text-sm font-medium">这些帖子怎么发送</span>
              <Badge variant="secondary">{scheduleCountLabel}</Badge>
            </div>
            <div className="text-xs text-muted-foreground">
              这里设置频道、分类、发送顺序和间隔时间。分类为空时会从全部帖子里选。
            </div>
          </div>

          {schedules.length > 0 && !showScheduleEditor ? (
            <Button size="sm" variant="outline" onClick={openCreateScheduleEditor}>
              <Plus className="w-3 h-3 mr-1" />
              新增发送方式
            </Button>
          ) : null}
        </div>

        {loading ? (
          <div className="text-sm text-muted-foreground">正在加载发送方式...</div>
        ) : schedules.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            还没有发送方式。添加一条后，系统才会开始自动发帖。
          </div>
        ) : (
          <div className="space-y-2">
            {schedules.map(schedule => (
              <div key={schedule.id} className="rounded-md border p-3 space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium font-mono">{schedule.channel_id}</span>
                      {schedule.category ? <Badge variant="outline">{schedule.category}</Badge> : <Badge variant="outline">全部分类</Badge>}
                      <Badge variant="secondary">
                        {schedule.send_mode === "sequential" ? "顺序" : "随机"}
                      </Badge>
                      <Badge variant={schedule.enabled ? "default" : "secondary"}>
                        {schedule.enabled ? "启用" : "停用"}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      每 {schedule.interval_minutes} 分钟发一次
                    </div>
                    <div className="text-xs text-muted-foreground">
                      上次发送: {schedule.last_sent_at || "还没有发送过"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button variant="outline" size="sm" onClick={() => openEditScheduleEditor(schedule)}>
                      <Pencil className="w-3 h-3" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => requestDeleteSchedule(schedule)}>
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {showScheduleEditor ? (
          <div className="rounded-md border bg-muted/20 p-4 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="text-sm font-medium">
                  {editingSchedule ? "编辑发送方式" : "设置这些帖子怎么发送"}
                </div>
                <div className="text-xs text-muted-foreground">
                  这里直接设置频道、分类、发送方式和间隔时间，不再单独弹出一个发送设置窗口。
                </div>
              </div>
              {editingSchedule || schedules.length > 0 ? (
                <Button variant="ghost" size="sm" onClick={resetScheduleEditor}>
                  取消
                </Button>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label>频道 ID</Label>
              <Input
                value={scheduleForm.channel_id}
                onChange={event => setScheduleForm(prev => ({ ...prev, channel_id: event.target.value }))}
                placeholder="例如：1234567890123456789"
              />
            </div>

            <div className="space-y-2">
              <Label>分类</Label>
              <Select
                value={scheduleForm.category || "__all__"}
                onValueChange={value => {
                  setScheduleForm(prev => ({ ...prev, category: value === "__all__" ? "" : value }))
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择分类" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部分类</SelectItem>
                  {categories.map(category => (
                    <SelectItem key={category} value={category}>{category}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {categories.length === 0 ? (
                <div className="text-xs text-muted-foreground">
                  还没有可选分类，先添加帖子时填上分类，之后这里就能直接选。
                </div>
              ) : null}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>发送方式</Label>
                <Select
                  value={scheduleForm.send_mode}
                  onValueChange={value => setScheduleForm(prev => ({
                    ...prev,
                    send_mode: value as "random" | "sequential",
                  }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">随机发送</SelectItem>
                    <SelectItem value="sequential">顺序发送</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>间隔分钟</Label>
                <Input
                  type="number"
                  min="1"
                  value={scheduleForm.interval_minutes}
                  onChange={event => setScheduleForm(prev => ({
                    ...prev,
                    interval_minutes: event.target.value,
                  }))}
                />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <div>
                <div className="text-sm font-medium">启用这条发送方式</div>
                <div className="text-xs text-muted-foreground">
                  关闭后不会继续自动发帖
                </div>
              </div>
              <Switch
                checked={scheduleForm.enabled}
                onCheckedChange={checked => setScheduleForm(prev => ({ ...prev, enabled: checked }))}
              />
            </div>

            <div className="flex justify-end gap-2">
              {(editingSchedule || schedules.length > 0) ? (
                <Button variant="outline" onClick={resetScheduleEditor}>
                  取消
                </Button>
              ) : null}
              <Button onClick={handleSaveSchedule} disabled={savingSchedule}>
                {savingSchedule ? "保存中..." : (editingSchedule ? "更新发送方式" : "保存发送方式")}
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      <Dialog open={postDialogOpen} onOpenChange={(open) => {
        if (!open) {
          resetPostDialog()
          return
        }
        setPostDialogOpen(true)
      }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingPost ? "编辑帖子" : "添加帖子"}</DialogTitle>
            <DialogDescription>
              分类可以为空。后面设置发送方式时，如果选中了某个分类，就只会从这个分类的帖子里发送。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>帖子名称</Label>
                <Input
                  value={postForm.title}
                  onChange={event => setPostForm(prev => ({ ...prev, title: event.target.value }))}
                  placeholder="例如：衣服日常 1"
                />
              </div>
              <div className="space-y-2">
                <Label>分类</Label>
                <Input
                  value={postForm.category}
                  onChange={event => setPostForm(prev => ({ ...prev, category: event.target.value }))}
                  placeholder="例如：衣服"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>帖子内容</Label>
              <Textarea
                rows={5}
                value={postForm.content}
                onChange={event => setPostForm(prev => ({ ...prev, content: event.target.value }))}
                placeholder="输入帖子文字内容"
              />
            </div>

            <div className="space-y-2">
              <Label>图片</Label>
              <Input
                type="file"
                multiple
                accept="image/*"
                onChange={event => {
                  const files = Array.from(event.target.files || [])
                  setPostForm(prev => ({ ...prev, newFiles: files }))
                }}
              />
              {postForm.existingImages.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-xs text-muted-foreground">已保存图片</div>
                  <div className="flex flex-wrap gap-2">
                    {postForm.existingImages.map(filename => {
                      const url = editingPost?.image_urls?.[editingPost.image_filenames.indexOf(filename)]
                      return (
                        <div key={filename} className="relative rounded-md border bg-muted/20 p-1">
                          {url ? (
                            <img
                              src={url}
                              alt={filename}
                              className="h-16 w-16 rounded object-cover"
                            />
                          ) : (
                            <div className="flex h-16 w-16 items-center justify-center text-[10px] text-muted-foreground">
                              {filename}
                            </div>
                          )}
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            className="absolute -right-2 -top-2 h-6 w-6 rounded-full p-0"
                            onClick={() => {
                              setPostForm(prev => ({
                                ...prev,
                                existingImages: prev.existingImages.filter(item => item !== filename),
                              }))
                            }}
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : null}
              {postForm.newFiles.length > 0 ? (
                <div className="text-xs text-muted-foreground">
                  本次新选中 {postForm.newFiles.length} 张图片
                </div>
              ) : null}
            </div>

            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <div>
                <div className="text-sm font-medium">启用这条帖子</div>
                <div className="text-xs text-muted-foreground">
                  关闭后不会进入自动发送候选
                </div>
              </div>
              <Switch
                checked={postForm.is_active}
                onCheckedChange={checked => setPostForm(prev => ({ ...prev, is_active: checked }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={resetPostDialog}>取消</Button>
            <Button onClick={handleSavePost} disabled={savingPost}>
              {savingPost ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={open => {
        if (!open) {
          closeDeleteDialog()
          return
        }
        setDeleteDialogOpen(true)
      }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `确认删除“${deleteTarget.label}”吗？删除后无法恢复。`
                : "确认删除这条内容吗？"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={closeDeleteDialog} disabled={deleting}>
              取消
            </Button>
            <Button variant="destructive" onClick={() => void confirmDeleteTarget()} disabled={deleting}>
              {deleting ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
