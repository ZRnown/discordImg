"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { toast } from "sonner"
import { Settings, Save } from "lucide-react"

interface User {
  id: number
  username: string
  role: string
  shops: string[]
}

interface UserSettings {
  discord_similarity_threshold: number
  global_reply_min_delay: number
  global_reply_max_delay: number
}

export function SettingsView() {
  const [settings, setSettings] = useState<UserSettings>({
    discord_similarity_threshold: 0.6,
    global_reply_min_delay: 3.0,
    global_reply_max_delay: 8.0,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [passwordData, setPasswordData] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  })
  const [changingPassword, setChangingPassword] = useState(false)

  useEffect(() => {
    fetchSettings()
  }, [])

  const fetchSettings = async () => {
    try {
      // 获取用户个性化设置
      const response = await fetch('/api/user/settings')
      if (response.ok) {
        const data = await response.json()
        setSettings({
          discord_similarity_threshold: data.discord_similarity_threshold ?? 0.6,
          global_reply_min_delay: data.global_reply_min_delay ?? 3.0,
          global_reply_max_delay: data.global_reply_max_delay ?? 8.0,
        })
      } else {
        toast.error("获取设置失败")
      }
    } catch (error) {
      console.error('Failed to fetch settings:', error)
      toast.error("获取设置失败")
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      // 验证回复延迟设置
      if (settings.global_reply_min_delay >= settings.global_reply_max_delay) {
        toast.error("最小延迟必须小于最大延迟")
        setSaving(false)
        return
      }

      if (settings.global_reply_min_delay < 0 || settings.global_reply_max_delay < 0) {
        toast.error("延迟时间不能为负数")
        setSaving(false)
        return
      }

      // 保存用户个性化设置
      const response = await fetch('/api/user/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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
      setSaving(false)
    }
  }

  const handleChangePassword = async () => {
    if (!passwordData.currentPassword || !passwordData.newPassword || !passwordData.confirmPassword) {
      toast.error("请填写所有密码字段")
      return
    }

    if (passwordData.newPassword !== passwordData.confirmPassword) {
      toast.error("新密码和确认密码不一致")
      return
    }

    if (passwordData.newPassword.length < 6) {
      toast.error("新密码长度至少6位")
      return
    }

    setChangingPassword(true)
    try {
      const response = await fetch('/api/user/change-password', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          current_password: passwordData.currentPassword,
          new_password: passwordData.newPassword
        })
      })

      if (response.ok) {
        toast.success("密码修改成功")
        setPasswordData({
          currentPassword: '',
          newPassword: '',
          confirmPassword: ''
        })
      } else {
        const error = await response.json()
        toast.error(error.error || "密码修改失败")
      }
    } catch (error) {
      toast.error("密码修改失败")
    } finally {
      setChangingPassword(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-8">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">系统设置</h2>
          <p className="text-sm text-muted-foreground mt-1">正在加载设置...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">个人设置</h2>
          <p className="text-sm text-muted-foreground mt-1">配置您的个性化运行参数</p>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          <Save className="w-4 h-4 mr-2" />
          {saving ? "保存中..." : "保存设置"}
        </Button>
      </div>

      {/* 密码修改 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">修改密码</CardTitle>
          <CardDescription>修改您的账号密码</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="current-password">当前密码</Label>
            <Input
              id="current-password"
              type="password"
              value={passwordData.currentPassword}
              onChange={(e) => setPasswordData(prev => ({ ...prev, currentPassword: e.target.value }))}
              placeholder="请输入当前密码"
            />
          </div>
          <div>
            <Label htmlFor="new-password">新密码</Label>
            <Input
              id="new-password"
              type="password"
              value={passwordData.newPassword}
              onChange={(e) => setPasswordData(prev => ({ ...prev, newPassword: e.target.value }))}
              placeholder="请输入新密码"
            />
          </div>
          <div>
            <Label htmlFor="confirm-password">确认新密码</Label>
            <Input
              id="confirm-password"
              type="password"
              value={passwordData.confirmPassword}
              onChange={(e) => setPasswordData(prev => ({ ...prev, confirmPassword: e.target.value }))}
              placeholder="请再次输入新密码"
            />
          </div>
          <Button
            onClick={handleChangePassword}
            disabled={changingPassword}
            className="w-full"
          >
            {changingPassword ? "修改中..." : "修改密码"}
          </Button>
        </CardContent>
      </Card>

      {/* 系统参数设置 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">系统参数</CardTitle>
          <CardDescription>配置图片匹配和回复延迟参数</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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

        {/* 系统信息 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">系统信息</CardTitle>
            <CardDescription>当前系统状态</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">状态:</span>
                <span className="text-green-600">运行正常</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">版本:</span>
                <span>v1.0.0</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
