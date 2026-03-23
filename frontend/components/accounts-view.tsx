"use client"

import { startTransition, useEffect, useRef, useState } from "react"
import { useApiCache } from "@/hooks/use-api-cache"
import {
  getApiErrorMessage,
  getDisplayedReplyMode,
  getKeywordBatchDispatchModeLabel,
  getReplyModeLabel,
  getReplyModeSettingsSection,
  getReplyModeSwitchError,
  isReplyModeOptionDisabled,
} from "@/lib/utils"
import {
  getMinimumReplyMaxDelay,
  normalizeReplyDelayRange,
  REPLY_DELAY_MAX,
  REPLY_DELAY_MIN,
  REPLY_DELAY_STEP,
} from "@/lib/reply-delay"
import {
  BUILTIN_WEBSITE_TEMPLATES,
  buildUniqueWebsiteInternalName,
  createEmptyWebsiteConfig,
  createWebsiteConfigFromTemplateKey,
  CUSTOM_WEBSITE_TEMPLATE_KEY,
  DEFAULT_WEBSITE_TEMPLATE_KEY,
  getWebsiteTemplateByKey,
} from "@/lib/website-templates"
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
import { Plus, Settings, Save, Trash2, Globe, Link, Hash, X, Edit, Clock } from "lucide-react"

type NumericRangeFilterValue = {
  keyword: string
  min: string
  max: string
}

const parseNumericRangeFilterValue = (value: string): NumericRangeFilterValue => {
  if (!value) {
    return { keyword: '', min: '', max: '' }
  }
  try {
    const parsed = JSON.parse(value)
    return {
      keyword: String(parsed?.keyword || ''),
      min: parsed?.min === null || parsed?.min === undefined ? '' : String(parsed.min),
      max: parsed?.max === null || parsed?.max === undefined ? '' : String(parsed.max)
    }
  } catch {
    const parts = value.split(/[|,]/).map(part => part.trim())
    if (parts.length >= 3) {
      return { keyword: parts[0] || '', min: parts[1] || '', max: parts[2] || '' }
    }
    return { keyword: '', min: '', max: '' }
  }
}

const buildNumericRangeFilterValue = (value: NumericRangeFilterValue) => {
  const keyword = value.keyword.trim()
  const min = value.min === '' ? null : Number(value.min)
  const max = value.max === '' ? null : Number(value.max)
  return JSON.stringify({ keyword, min, max })
}

const formatMessageFilterLabel = (filter: any) => {
  if (filter.filter_type === 'numeric_range') {
    const fields = parseNumericRangeFilterValue(filter.filter_value || '')
    const keyword = fields.keyword || '未设置关键词'
    const minLabel = fields.min !== '' ? fields.min : '不限'
    const maxLabel = fields.max !== '' ? fields.max : '不限'
    return `数字范围: ${keyword} (${minLabel}-${maxLabel})`
  }
  if (filter.filter_type === 'image_similarity') {
    return `图片相似度 ≥ ${filter.filter_value}`
  }
  if (filter.filter_type === 'image') {
    return '图片消息'
  }
  if (filter.filter_type === 'image_filter') {
    return `图片过滤 ≥ ${filter.filter_value || '0.95'}`
  }
  if (filter.filter_type === 'user_repeat') {
    return `用户重复发送 ≤ ${filter.filter_value || '5'} 秒`
  }
  if (filter.filter_type === 'keyword_match_limit') {
    return `关键词命中上限 ≤ ${filter.filter_value || '0'}`
  }
  if (filter.filter_type === 'role_id') {
    return `身份组ID: ${filter.filter_value}`
  }
  return `${filter.filter_type} "${filter.filter_value}"`
}

const getDefaultFilterValueForType = (filterType: string) => {
  if (filterType === 'numeric_range') {
    return buildNumericRangeFilterValue({ keyword: '', min: '', max: '' })
  }
  if (filterType === 'image_filter') {
    return '0.95'
  }
  if (filterType === 'user_repeat') {
    return '5'
  }
  if (filterType === 'keyword_match_limit') {
    return '2'
  }
  return ''
}

const getFilterValuePlaceholder = (filterType: string) => {
  if (filterType === 'user_id') {
    return '输入用户ID，多个用逗号分隔'
  }
  if (filterType === 'role_id') {
    return '输入身份组ID，多个用逗号分隔'
  }
  if (filterType === 'keyword_match_limit') {
    return '输入上限，例如 2'
  }
  return '输入过滤条件'
}

const normalizeMultiValueFilterInput = (value: string) =>
  value
    .split(/[,\n，]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .join(',')

const normalizeKeywordMatchLimitFilter = (rawValue: string) => {
  const trimmed = rawValue.trim()
  if (!trimmed) {
    return { ok: false, error: '关键词命中上限不能为空' as const }
  }
  const value = Number.parseInt(trimmed, 10)
  if (!Number.isFinite(value)) {
    return { ok: false, error: '关键词命中上限必须是整数' as const }
  }
  if (value < 0) {
    return { ok: false, error: '关键词命中上限不能小于 0' as const }
  }
  return { ok: true as const, value: String(value) }
}

const createFilterId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `f_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

const BARK_SETTINGS_CACHE_KEY = 'discord_marketing_bark_settings_v1'

const hasOwn = (obj: any, key: string) => Object.prototype.hasOwnProperty.call(obj, key)
const toBoolean = (value: any) => (
  value === true ||
  value === 1 ||
  value === '1' ||
  value === 'true' ||
  value === 'True'
)

const pickBarkSettings = (source: any) => ({
  bark_enabled: toBoolean(source?.bark_enabled),
  bark_server_url: String(source?.bark_server_url || 'https://api.day.app').trim() || 'https://api.day.app',
  bark_device_key: String(source?.bark_device_key || ''),
})

const readBarkSettingsCache = () => {
  if (typeof window === 'undefined') {
    return {}
  }
  try {
    const raw = localStorage.getItem(BARK_SETTINGS_CACHE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return {
      bark_enabled: toBoolean(parsed?.bark_enabled),
      bark_server_url: typeof parsed?.bark_server_url === 'string' ? parsed.bark_server_url : 'https://api.day.app',
      bark_device_key: typeof parsed?.bark_device_key === 'string' ? parsed.bark_device_key : '',
    }
  } catch {
    return {}
  }
}

const writeBarkSettingsCache = (settings: any) => {
  if (typeof window === 'undefined') {
    return
  }
  try {
    localStorage.setItem(
      BARK_SETTINGS_CACHE_KEY,
      JSON.stringify({
        bark_enabled: !!settings?.bark_enabled,
        bark_server_url: settings?.bark_server_url || 'https://api.day.app',
        bark_device_key: settings?.bark_device_key || '',
      })
    )
  } catch {
    // ignore cache errors
  }
}

function CooldownTimer({ remaining }: { remaining: number }) {
  if (remaining <= 0) return null
  return (
    <div className="flex items-center text-orange-600 text-xs gap-1 mt-1 bg-orange-50 px-2 py-0.5 rounded border border-orange-100">
      <Clock className="w-3 h-3" />
      <span className="font-mono">{Math.ceil(remaining)}s 冷却中</span>
    </div>
  )
}

export function AccountsView({ isActive = true }: { isActive?: boolean }) {
  const [accounts, setAccounts] = useState<any[]>([])
  const [accountPage, setAccountPage] = useState(1)
  const accountsPerPage = 5
  const [users, setUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [newAccount, setNewAccount] = useState({
    token: ""
  })
  const [settings, setSettings] = useState({
    discord_similarity_threshold: 0.6,
    global_reply_min_delay: 1.0,
    global_reply_max_delay: 3.0,
    keyword_match_limit: 0,
    bark_enabled: false,
    bark_server_url: 'https://api.day.app',
    bark_device_key: '',
  })
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [barkTesting, setBarkTesting] = useState(false)
  const [barkAutoSaving, setBarkAutoSaving] = useState(false)
  const barkCacheHydratedRef = useRef(false)
  const barkAutoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const barkAutoSaveLastPayloadRef = useRef('')

  // 新增：当前用户信息状态
  const [currentUser, setCurrentUser] = useState<any>(null)
  const [deleteAccountConfirm, setDeleteAccountConfirm] = useState<any>(null)

  // 使用API缓存hook
  const { cachedFetch, invalidateCache } = useApiCache()

  // 网站配置相关状态
  const [websites, setWebsites] = useState<any[]>([])
  const [showAddWebsite, setShowAddWebsite] = useState(false)
  const [selectedWebsiteTemplateKey, setSelectedWebsiteTemplateKey] = useState(DEFAULT_WEBSITE_TEMPLATE_KEY)
  const [editingWebsite, setEditingWebsite] = useState<any>(null)
  const [newWebsite, setNewWebsite] = useState(createWebsiteConfigFromTemplateKey(DEFAULT_WEBSITE_TEMPLATE_KEY))
  const [websiteChannels, setWebsiteChannels] = useState<{[key: number]: string[]}>({})
  const [channelInputs, setChannelInputs] = useState<{[key: number]: string}>({})
  const [channelToRemove, setChannelToRemove] = useState<{webId: number, chanId: string} | null>(null)
  const [replyModes, setReplyModes] = useState<{[key: number]: string}>({})
  const [pendingReplyModes, setPendingReplyModes] = useState<{[key: number]: string}>({})
  const [replyModeSaving, setReplyModeSaving] = useState<{[key: number]: boolean}>({})
  const [rotationInputs, setRotationInputs] = useState<{[key: number]: string}>({})
  const [keywordIntervalInputs, setKeywordIntervalInputs] = useState<{[key: number]: string}>({})
  const [keywordBatchInputs, setKeywordBatchInputs] = useState<{[key: number]: string}>({})
  const [keywordDispatchModes, setKeywordDispatchModes] = useState<{[key: number]: string}>({})

  const [cooldowns, setCooldowns] = useState<any[]>([])

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
  const [websiteSimilarityInputs, setWebsiteSimilarityInputs] = useState<{[key: number]: string}>({})
  const [websiteReplyDelayInputs, setWebsiteReplyDelayInputs] = useState<{[key: number]: { min: string, max: string }}>({})
  const [websiteKeywordMatchInputs, setWebsiteKeywordMatchInputs] = useState<{[key: number]: string}>({})
  const [websiteNewFilter, setWebsiteNewFilter] = useState({
    filter_type: 'contains',
    filter_value: ''
  })
  const [websiteNewFilterImages, setWebsiteNewFilterImages] = useState<File[]>([])
  const [editingWebsiteFilter, setEditingWebsiteFilter] = useState<any>(null)
  const [editingWebsiteFilterImages, setEditingWebsiteFilterImages] = useState<any[]>([])
  const [editingWebsiteFilterNewFiles, setEditingWebsiteFilterNewFiles] = useState<File[]>([])
  const [editingWebsiteFilterImagesLoading, setEditingWebsiteFilterImagesLoading] = useState(false)
  const [editingWebsiteFilterImagesUploading, setEditingWebsiteFilterImagesUploading] = useState(false)
  const websiteNewFilterImageInputRef = useRef<HTMLInputElement | null>(null)
  const websiteEditingFilterImageInputRef = useRef<HTMLInputElement | null>(null)

  // 消息过滤相关状态
  const [messageFilters, setMessageFilters] = useState<any[]>([])
  const [showAddFilter, setShowAddFilter] = useState(false)
  const [editingFilter, setEditingFilter] = useState<any>(null)
  const [newFilter, setNewFilter] = useState({
    filter_type: 'contains',
    filter_value: ''
  })

  // 图片过滤相关状态
  const [newFilterImages, setNewFilterImages] = useState<File[]>([])
  const [editingFilterImages, setEditingFilterImages] = useState<any[]>([])
  const [editingFilterNewFiles, setEditingFilterNewFiles] = useState<File[]>([])
  const [editingFilterImagesLoading, setEditingFilterImagesLoading] = useState(false)
  const [editingFilterImagesUploading, setEditingFilterImagesUploading] = useState(false)
  const newFilterImageInputRef = useRef<HTMLInputElement | null>(null)
  const editingFilterImageInputRef = useRef<HTMLInputElement | null>(null)
  const websiteSimilaritySaveTimersRef = useRef<{[key: number]: ReturnType<typeof setTimeout> | undefined}>({})
  const websiteReplyDelaySaveTimersRef = useRef<{[key: number]: ReturnType<typeof setTimeout> | undefined}>({})
  const websiteReplyDelayInputsRef = useRef<{[key: number]: { min: string, max: string }}>({})
  const websiteKeywordMatchSaveTimersRef = useRef<{[key: number]: ReturnType<typeof setTimeout> | undefined}>({})
  const formatThresholdForInput = (value: any) => {
    if (value === null || value === undefined || value === '') return ''
    const num = Number(value)
    return Number.isFinite(num) ? String(num) : ''
  }

  const formatReplyDelayForInput = (value: any) => {
    if (value === null || value === undefined || value === '') return ''
    const num = Number(value)
    return Number.isFinite(num) ? String(num) : ''
  }

  const formatWebsiteForEdit = (website: any) => ({
    ...website,
    image_similarity_threshold: formatThresholdForInput(website?.image_similarity_threshold)
  })

  const applyWebsiteSimilarityState = (websiteId: number, threshold: string) => {
    setWebsites(prev => prev.map(website => (
      website.id === websiteId
        ? { ...website, image_similarity_threshold: threshold === '' ? null : Number(threshold) }
        : website
    )))
    setWebsiteSimilarityInputs(prev => ({ ...prev, [websiteId]: threshold }))
  }

  const applyWebsiteReplyDelayState = (websiteId: number, minDelay: string, maxDelay: string) => {
    setWebsites(prev => prev.map(website => (
      website.id === websiteId
        ? {
            ...website,
            reply_min_delay: minDelay === '' ? null : Number(minDelay),
            reply_max_delay: maxDelay === '' ? null : Number(maxDelay),
          }
        : website
    )))
    const nextInputs = { ...websiteReplyDelayInputsRef.current, [websiteId]: { min: minDelay, max: maxDelay } }
    websiteReplyDelayInputsRef.current = nextInputs
    setWebsiteReplyDelayInputs(nextInputs)
  }

  const applyWebsiteKeywordMatchState = (websiteId: number, value: string) => {
    setWebsites(prev => prev.map(website => (
      website.id === websiteId
        ? { ...website, keyword_match_limit: value === '' ? null : Number(value) }
        : website
    )))
    setWebsiteKeywordMatchInputs(prev => ({ ...prev, [websiteId]: value }))
  }

  const mergeIncomingSettings = (prev: any, data: any) => {
    const delayRange = normalizeReplyDelayRange(
      Number(data?.global_reply_min_delay ?? prev.global_reply_min_delay ?? 1.0),
      Number(data?.global_reply_max_delay ?? prev.global_reply_max_delay ?? 3.0),
    )
    const next = {
      ...prev,
      discord_similarity_threshold: data?.discord_similarity_threshold ?? prev.discord_similarity_threshold ?? 0.6,
      global_reply_min_delay: delayRange.minDelay,
      global_reply_max_delay: delayRange.maxDelay,
      keyword_match_limit: Number(data?.keyword_match_limit ?? prev.keyword_match_limit ?? 0),
    }

    if (hasOwn(data, 'bark_enabled')) {
      next.bark_enabled = toBoolean(data.bark_enabled)
    }
    if (hasOwn(data, 'bark_server_url')) {
      next.bark_server_url = data.bark_server_url || 'https://api.day.app'
    }
    if (hasOwn(data, 'bark_device_key')) {
      next.bark_device_key = data.bark_device_key || ''
    }
    return next
  }

  const saveBarkSettings = async (sourceSettings: any, options?: { silent?: boolean }) => {
    const payload = pickBarkSettings(sourceSettings)
    const payloadKey = JSON.stringify(payload)
    if (payloadKey === barkAutoSaveLastPayloadRef.current) {
      return true
    }

    if (!options?.silent) {
      setBarkAutoSaving(true)
    }

    try {
      const response = await fetch('/api/user/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      })
      if (!response.ok) {
        if (!options?.silent) {
          toast.error('Bark 配置自动保存失败，请点击“保存设置”重试')
        }
        return false
      }
      barkAutoSaveLastPayloadRef.current = payloadKey
      return true
    } catch {
      if (!options?.silent) {
        toast.error('Bark 配置自动保存失败，请点击“保存设置”重试')
      }
      return false
    } finally {
      if (!options?.silent) {
        setBarkAutoSaving(false)
      }
    }
  }

  const scheduleBarkAutoSave = (nextSettings: any, delay = 600) => {
    if (barkAutoSaveTimerRef.current) {
      clearTimeout(barkAutoSaveTimerRef.current)
    }
    barkAutoSaveTimerRef.current = setTimeout(() => {
      void saveBarkSettings(nextSettings)
    }, delay)
  }


  const fetchWebsites = async (forceRefresh = false) => {
    try {
      const cacheKey = '/api/websites'
      let data: any
      if (forceRefresh) {
        // 强制刷新：清除缓存
        sessionStorage.removeItem(`cache_${cacheKey}`)
        invalidateCache('/api/websites')
        const response = await fetch('/api/websites', {
          credentials: 'include',
          cache: 'no-store'
        })
        data = await response.json().catch(() => ({}))
        if (!response.ok) {
          throw new Error(getApiErrorMessage(data, '获取网站配置失败'))
        }
      } else {
        data = await cachedFetch('/api/websites', { credentials: 'include' })
      }
      const websites = data.websites || []

      // 后端已包含channels和accounts信息
      const channels: {[key: number]: string[]} = {}
      const accounts: {[key: number]: any[]} = {}
      const filters: {[key: number]: any[]} = {}
      const replyModes: {[key: number]: string} = {}
      const rotationInputs: {[key: number]: string} = {}
      const keywordIntervalInputs: {[key: number]: string} = {}
      const keywordBatchInputs: {[key: number]: string} = {}
      const keywordDispatchModes: {[key: number]: string} = {}
      const similarityInputs: {[key: number]: string} = {}
      const replyDelayInputs: {[key: number]: { min: string, max: string }} = {}
      const keywordMatchInputs: {[key: number]: string} = {}

      websites.forEach((website: any) => {
        channels[website.id] = website.channels || []
        accounts[website.id] = website.accounts || []
        replyModes[website.id] = website.reply_mode || 'rotation'
        rotationInputs[website.id] = (website.rotation_interval || 180).toString()
        keywordIntervalInputs[website.id] = (website.keyword_reply_interval ?? website.rotation_interval ?? 180).toString()
        keywordBatchInputs[website.id] = (website.keyword_reply_batch_size ?? 0).toString()
        keywordDispatchModes[website.id] = website.keyword_batch_dispatch_mode ?? 'immediate'
        similarityInputs[website.id] = formatThresholdForInput(website.image_similarity_threshold)
        replyDelayInputs[website.id] = {
          min: formatReplyDelayForInput(website.reply_min_delay),
          max: formatReplyDelayForInput(website.reply_max_delay),
        }
        keywordMatchInputs[website.id] = formatThresholdForInput(website.keyword_match_limit)
        try {
          if (Array.isArray(website.message_filters)) {
            filters[website.id] = website.message_filters
          } else if (typeof website.message_filters === 'string') {
            filters[website.id] = JSON.parse(website.message_filters || '[]')
          } else {
            filters[website.id] = []
          }
        } catch (e) {
          filters[website.id] = []
        }
      })

      startTransition(() => {
        setWebsites(websites)
        setWebsiteChannels(channels)
        setWebsiteAccounts(accounts)
        setWebsiteFilters(filters)
        setReplyModes(replyModes)
        setRotationInputs(rotationInputs)
        setKeywordIntervalInputs(keywordIntervalInputs)
        setKeywordBatchInputs(keywordBatchInputs)
        setKeywordDispatchModes(keywordDispatchModes)
        setWebsiteSimilarityInputs(similarityInputs)
        setWebsiteReplyDelayInputs(replyDelayInputs)
        setWebsiteKeywordMatchInputs(keywordMatchInputs)
      })
    } catch (e) {
      console.error('获取网站配置失败:', e)
      toast.error(getApiErrorMessage(e, '获取网站配置失败'))
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
      toast.error(getApiErrorMessage(e, '获取消息过滤规则失败'))
    }
  }

  const fetchMessageFilterImages = async (filterId: number) => {
    setEditingFilterImagesLoading(true)
    try {
      const res = await fetch(`/api/message-filters/${filterId}/images`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setEditingFilterImages(data.images || [])
      }
    } catch (e) {
      console.error('获取过滤图片失败:', e)
      toast.error(getApiErrorMessage(e, '获取过滤图片失败'))
    } finally {
      setEditingFilterImagesLoading(false)
    }
  }

  const uploadMessageFilterImages = async (filterId: number, files: File[]) => {
    if (!files.length) return true
    setEditingFilterImagesUploading(true)
    try {
      for (const file of files) {
        const formData = new FormData()
        formData.append('image', file)
        const res = await fetch(`/api/message-filters/${filterId}/images`, {
          method: 'POST',
          body: formData,
          credentials: 'include'
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          toast.error(getApiErrorMessage(data, '上传失败'))
          return false
        }
      }
      return true
    } catch (e) {
      toast.error(getApiErrorMessage(e, '上传失败'))
      return false
    } finally {
      setEditingFilterImagesUploading(false)
    }
  }

  const handleDeleteMessageFilterImage = async (filterId: number, imageId: number) => {
    try {
      const res = await fetch(`/api/message-filters/${filterId}/images/${imageId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        setEditingFilterImages(prev => prev.filter(img => img.id !== imageId))
        toast.success('已移除')
      } else {
        const data = await res.json().catch(() => ({}))
        toast.error(getApiErrorMessage(data, '删除失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '删除失败'))
    }
  }

  const fetchWebsiteFilterImages = async (websiteId: number, filterId: string) => {
    setEditingWebsiteFilterImagesLoading(true)
    try {
      const res = await fetch(`/api/websites/${websiteId}/filters/${filterId}/images`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setEditingWebsiteFilterImages(data.images || [])
      }
    } catch (e) {
      console.error('获取网站过滤图片失败:', e)
      toast.error(getApiErrorMessage(e, '获取网站过滤图片失败'))
    } finally {
      setEditingWebsiteFilterImagesLoading(false)
    }
  }

  const fetchWebsiteFiltersForWebsite = async (websiteId: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/filters`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        const filters = data.filters || []
        setWebsiteFilters(prev => ({ ...prev, [websiteId]: filters }))
        return filters
      }
    } catch (e) {
      console.error('获取网站过滤规则失败:', e)
      toast.error(getApiErrorMessage(e, '获取网站过滤规则失败'))
    }
    return null
  }

  const uploadWebsiteFilterImages = async (websiteId: number, filterId: string, files: File[]) => {
    if (!files.length) return true
    setEditingWebsiteFilterImagesUploading(true)
    try {
      for (const file of files) {
        const formData = new FormData()
        formData.append('image', file)
        const res = await fetch(`/api/websites/${websiteId}/filters/${filterId}/images`, {
          method: 'POST',
          body: formData,
          credentials: 'include'
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          toast.error(getApiErrorMessage(data, '上传失败'))
          return false
        }
      }
      return true
    } catch (e) {
      toast.error(getApiErrorMessage(e, '上传失败'))
      return false
    } finally {
      setEditingWebsiteFilterImagesUploading(false)
    }
  }

  const handleMessageFilterFileSelect = async (files: FileList | null) => {
    if (!editingFilter) return
    if (editingFilter.filter_type !== 'image_filter') {
      toast.error('请先将过滤类型设置为图片过滤并保存')
      return
    }
    const fileList = Array.from(files || [])
    if (!fileList.length) return

    const filterId = editingFilter.id
    if (!filterId) {
      toast.error('过滤规则不存在，请先保存')
      return
    }

    setEditingFilterNewFiles(fileList)
    const ok = await uploadMessageFilterImages(filterId, fileList)
    if (ok) {
      toast.success('图片已上传')
      fetchMessageFilterImages(filterId)
    }
    setEditingFilterNewFiles([])
    if (editingFilterImageInputRef.current) {
      editingFilterImageInputRef.current.value = ''
    }
  }

  const handleWebsiteFilterFileSelect = async (files: FileList | null) => {
    if (!editingWebsiteFilter) return
    const fileList = Array.from(files || [])
    if (!fileList.length) return
    if (editingWebsiteFilter.filter?.filter_type !== 'image_filter') {
      toast.error('请先将过滤类型设置为图片过滤并保存')
      return
    }

    const websiteId = editingWebsiteFilter.websiteId
    const filterId = editingWebsiteFilter.filter?.id
    if (!websiteId || !filterId) {
      toast.error('过滤规则不存在，请先保存')
      return
    }

    const exists = (websiteFilters[websiteId] || []).some((item: any) => String(item.id) === String(filterId))
    if (!exists) {
      toast.error('过滤规则不存在，请先保存')
      return
    }

    setEditingWebsiteFilterNewFiles(fileList)
    const ok = await uploadWebsiteFilterImages(websiteId, String(filterId), fileList)
    if (ok) {
      toast.success('图片已上传')
      fetchWebsiteFilterImages(websiteId, String(filterId))
    }
    setEditingWebsiteFilterNewFiles([])
    if (websiteEditingFilterImageInputRef.current) {
      websiteEditingFilterImageInputRef.current.value = ''
    }
  }

  const handleDeleteWebsiteFilterImage = async (websiteId: number, filterId: string, imageId: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/filters/${filterId}/images/${imageId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (res.ok) {
        setEditingWebsiteFilterImages(prev => prev.filter(img => img.id !== imageId))
        toast.success('已移除')
      } else {
        const data = await res.json().catch(() => ({}))
        toast.error(getApiErrorMessage(data, '删除失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '删除失败'))
    }
  }


  const fetchCooldowns = async () => {
    try {
      const res = await fetch('/api/bot/cooldowns', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setCooldowns(data.cooldowns || [])
      }
    } catch {
      // ignore
    }
  }

  const getCooldownRemaining = (accountId: number, websiteId: number) => {
    const website = websites.find(w => w.id === websiteId)
    if (!website) return 0

    const interval = website.rotation_interval || 180
    const channels = websiteChannels[websiteId] || []

    let maxRemaining = 0

    for (const cd of cooldowns) {
      if (cd.account_id === accountId && channels.includes(cd.channel_id)) {
        const passed = Date.now() / 1000 - cd.last_sent
        const remaining = interval - passed
        if (remaining > maxRemaining) {
          maxRemaining = remaining
        }
      }
    }

    return maxRemaining > 0 ? maxRemaining : 0
  }

  const getWebsiteSenderCount = (websiteId: number) => {
    return (websiteAccounts[websiteId] || []).filter((binding: any) => (
      binding.role === 'sender' || binding.role === 'both'
    )).length
  }

  const getWebsiteReplyMode = (website: any) => {
    if (!website) return 'rotation'
    return getDisplayedReplyMode(
      replyModes[website.id] ?? website.reply_mode,
      pendingReplyModes[website.id],
    )
  }

  const clearPendingReplyModeState = (websiteId: number) => {
    startTransition(() => {
      setPendingReplyModes(prev => {
        if (!(websiteId in prev)) return prev
        const next = { ...prev }
        delete next[websiteId]
        return next
      })
      setReplyModeSaving(prev => {
        if (!(websiteId in prev)) return prev
        const next = { ...prev }
        delete next[websiteId]
        return next
      })
    })
  }

  const applyRotationSettingsState = (websiteId: number, nextSettings: any) => {
    if (!nextSettings) return

    setWebsites(prev => prev.map(website => (
            website.id === websiteId
        ? {
            ...website,
            rotation_interval: nextSettings.rotation_interval,
            rotation_enabled: nextSettings.rotation_enabled,
            reply_mode: nextSettings.reply_mode,
            keyword_reply_interval: nextSettings.keyword_reply_interval,
            keyword_reply_batch_size: nextSettings.keyword_reply_batch_size,
            keyword_batch_dispatch_mode: nextSettings.keyword_batch_dispatch_mode,
            keyword_match_limit: nextSettings.keyword_match_limit,
            reply_min_delay: nextSettings.reply_min_delay,
            reply_max_delay: nextSettings.reply_max_delay,
          }
        : website
    )))
    setReplyModes(prev => ({ ...prev, [websiteId]: nextSettings.reply_mode ?? 'rotation' }))
    setRotationInputs(prev => ({ ...prev, [websiteId]: String(nextSettings.rotation_interval ?? 180) }))
    setKeywordIntervalInputs(prev => ({
      ...prev,
      [websiteId]: String(nextSettings.keyword_reply_interval ?? nextSettings.rotation_interval ?? 180)
    }))
    setKeywordBatchInputs(prev => ({
      ...prev,
      [websiteId]: String(nextSettings.keyword_reply_batch_size ?? 0)
    }))
    setKeywordDispatchModes(prev => ({
      ...prev,
      [websiteId]: nextSettings.keyword_batch_dispatch_mode ?? 'immediate'
    }))
    if (nextSettings.keyword_match_limit !== undefined) {
      setWebsiteKeywordMatchInputs(prev => ({
        ...prev,
        [websiteId]: formatThresholdForInput(nextSettings.keyword_match_limit),
      }))
    }
    if (nextSettings.reply_min_delay !== undefined || nextSettings.reply_max_delay !== undefined) {
      setWebsiteReplyDelayInputs(prev => ({
        ...prev,
        [websiteId]: {
          min: formatReplyDelayForInput(nextSettings.reply_min_delay),
          max: formatReplyDelayForInput(nextSettings.reply_max_delay),
        }
      }))
    }
  }

  const updateWebsiteRotationSettings = async (
    websiteId: number,
    payload: Record<string, any>,
    fallbackSuccessMessage: string,
  ) => {
    const res = await fetch(`/api/websites/${websiteId}/rotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    })

    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      throw new Error(data?.error || '更新失败')
    }

    applyRotationSettingsState(websiteId, data.settings)
    toast.success(data?.message || fallbackSuccessMessage)
    return data
  }

  const refreshWebsiteRotationSettings = async (websiteId: number) => {
    const res = await fetch(`/api/websites/${websiteId}/rotation`, {
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      throw new Error(data?.error || '获取设置失败')
    }
    applyRotationSettingsState(websiteId, data)
    return data
  }

  useEffect(() => {
    if (!isActive) return
    // 先恢复本地 Bark 配置缓存，避免后端响应缺字段时把输入框清空
    const cached = readBarkSettingsCache()
    if (Object.keys(cached).length > 0) {
      setSettings(prev => ({ ...prev, ...cached }))
    }
    barkCacheHydratedRef.current = true

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
    fetchWebsites(true); // 强制刷新，清除旧的缓存数据
    fetchMessageFilters();
    fetchCooldowns();

    // 降低轮询频率，减轻账号页和后端的持续刷新压力
    const statusInterval = setInterval(() => {
      if (!document.hidden) { // 只在标签页可见时刷新
        fetchAccounts(true); // 强制刷新，清除缓存
      }
    }, 30000);

    // 冷却状态允许稍慢一些，避免后台持续刷接口
    const cooldownInterval = setInterval(() => {
      if (!document.hidden) { // 只在标签页可见时刷新
        fetchCooldowns()
      }
    }, 20000)

    const handleStatusChange = () => {
      fetchAccounts(true)
    }
    window.addEventListener('bot-status-changed', handleStatusChange)

    return () => {
      clearInterval(statusInterval);
      clearInterval(cooldownInterval);
      window.removeEventListener('bot-status-changed', handleStatusChange)
    }
  }, [isActive])

  useEffect(() => {
    if (!editingFilter) return
    if (editingFilter.filter_type === 'image_filter') {
      fetchMessageFilterImages(editingFilter.id)
      return
    }
    setEditingFilterImages([])
    setEditingFilterNewFiles([])
    if (editingFilterImageInputRef.current) {
      editingFilterImageInputRef.current.value = ''
    }
  }, [editingFilter])

  useEffect(() => {
    if (!editingWebsiteFilter) return
    if (editingWebsiteFilter.filter?.filter_type === 'image_filter') {
      fetchWebsiteFilterImages(editingWebsiteFilter.websiteId, editingWebsiteFilter.filter.id)
      return
    }
    setEditingWebsiteFilterImages([])
    setEditingWebsiteFilterNewFiles([])
    if (websiteEditingFilterImageInputRef.current) {
      websiteEditingFilterImageInputRef.current.value = ''
    }
  }, [editingWebsiteFilter])

  useEffect(() => {
    if (!barkCacheHydratedRef.current) {
      return
    }
    writeBarkSettingsCache(settings)
  }, [settings.bark_enabled, settings.bark_server_url, settings.bark_device_key])

  useEffect(() => {
    return () => {
      if (barkAutoSaveTimerRef.current) {
        clearTimeout(barkAutoSaveTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    return () => {
      Object.values(websiteSimilaritySaveTimersRef.current).forEach(timer => {
        if (timer) clearTimeout(timer)
      })
      Object.entries(websiteReplyDelaySaveTimersRef.current).forEach(([websiteId, timer]) => {
        if (timer) {
          clearTimeout(timer)
          flushWebsiteReplyDelaySave(Number(websiteId), { keepalive: true })
        }
      })
      Object.values(websiteKeywordMatchSaveTimersRef.current).forEach(timer => {
        if (timer) clearTimeout(timer)
      })
    }
  }, [])

  useEffect(() => {
    websiteReplyDelayInputsRef.current = websiteReplyDelayInputs
  }, [websiteReplyDelayInputs])

  useEffect(() => {
    const flushPendingReplyDelaySaves = () => {
      Object.entries(websiteReplyDelaySaveTimersRef.current).forEach(([websiteId, timer]) => {
        if (timer) {
          flushWebsiteReplyDelaySave(Number(websiteId), { keepalive: true })
        }
      })
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        flushPendingReplyDelaySaves()
      }
    }

    window.addEventListener('beforeunload', flushPendingReplyDelaySaves)
    window.addEventListener('pagehide', flushPendingReplyDelaySaves)
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      window.removeEventListener('beforeunload', flushPendingReplyDelaySaves)
      window.removeEventListener('pagehide', flushPendingReplyDelaySaves)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
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
            setSettings(prev => {
              const merged = mergeIncomingSettings(prev, data)
              barkAutoSaveLastPayloadRef.current = JSON.stringify(pickBarkSettings(merged))
              return merged
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
        setSettings(prev => {
          const merged = mergeIncomingSettings(prev, data)
          barkAutoSaveLastPayloadRef.current = JSON.stringify(pickBarkSettings(merged))
          return merged
        })
      } else {
        const errorData = await response.json().catch(() => ({}))
        toast.error(getApiErrorMessage(errorData, '获取设置失败'))
      }
    } catch (error) {
      console.error('Failed to fetch settings:', error)
      toast.error(getApiErrorMessage(error, '获取设置失败'))
    }
  }

  const handleSaveSettings = async () => {
    if (settings.bark_enabled && !settings.bark_device_key.trim()) {
      toast.error("已启用 Bark 通知，请填写 Bark 设备 Key")
      return
    }
    if (settings.global_reply_min_delay >= settings.global_reply_max_delay) {
      toast.error("最小延迟必须小于最大延迟")
      return
    }
    if (settings.keyword_match_limit < 0) {
      toast.error("关键词命中上限不能小于 0")
      return
    }
    if (settings.global_reply_min_delay < REPLY_DELAY_MIN || settings.global_reply_max_delay > REPLY_DELAY_MAX) {
      toast.error("回复延迟范围无效")
      return
    }
    setSettingsLoading(true)
    try {
      const response = await fetch('/api/user/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(settings)
      })

      if (response.ok) {
        barkAutoSaveLastPayloadRef.current = JSON.stringify(pickBarkSettings(settings))
        toast.success("设置已保存")
      } else {
        const errorData = await response.json().catch(() => ({}))
        toast.error(getApiErrorMessage(errorData, "保存设置失败"))
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, "保存设置失败"))
    } finally {
      setSettingsLoading(false)
    }
  }

  const handleTestBarkNotification = async () => {
    if (!settings.bark_device_key.trim()) {
      toast.error("请先填写 Bark 设备 Key")
      return
    }

    setBarkTesting(true)
    try {
      // 先尝试保存当前配置，避免“测试后重启看起来丢失”
      await saveBarkSettings(settings, { silent: true }).catch(() => null)

      const response = await fetch('/internal-api/bark-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          bark_server_url: settings.bark_server_url,
          bark_device_key: settings.bark_device_key,
        })
      })

      const data = await response.json().catch(() => ({}))
      if (response.ok) {
        if (data?.device_key_updated) {
          const nextSettings = { ...settings, bark_device_key: data.device_key_updated }
          setSettings(nextSettings)
          // 自动持久化转换后的 device_key，避免重启后丢失
          await saveBarkSettings(nextSettings, { silent: true }).catch(() => null)
        }
        toast.success(data.message || "测试推送已发送")
        if (data?.hint) {
          toast.info(data.hint)
        }
      } else {
        const extra = data?.stage ? ` (${data.stage})` : ''
        toast.error((data.error || "测试推送失败") + extra)
      }
    } catch (error) {
      toast.error("测试推送失败，请检查网络后重试")
    } finally {
      setBarkTesting(false)
    }
  }

  const fetchAccounts = async (forceRefresh = false) => {
          try {
      console.log('获取账号列表...')
      const cacheKey = '/api/accounts'
      if (forceRefresh) {
        // 强制刷新：清除缓存
        sessionStorage.removeItem(`cache_${cacheKey}`)
      }
      const data = await cachedFetch('/api/accounts', { credentials: 'include' })
            setAccounts(data.accounts || [])
    } catch (error) {
      console.error('获取账号列表出错:', error)
      toast.error(getApiErrorMessage(error, '获取账号列表失败'))
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

  const resetNewWebsiteForm = () => {
    setSelectedWebsiteTemplateKey(DEFAULT_WEBSITE_TEMPLATE_KEY)
    setNewWebsite(createWebsiteConfigFromTemplateKey(DEFAULT_WEBSITE_TEMPLATE_KEY))
  }

  const handleAddWebsiteDialogOpenChange = (open: boolean) => {
    setShowAddWebsite(open)
    if (!open) {
      resetNewWebsiteForm()
    }
  }

  // 网站配置处理函数
  const handleAddWebsite = async () => {
    try {
      const template = getWebsiteTemplateByKey(selectedWebsiteTemplateKey)
      const displayName = (newWebsite.display_name || template?.display_name || '').trim()
      if (!displayName) {
        toast.error('请填写网站显示名称')
        return
      }

      const existingNames = websites.map(website => String(website.name || '').trim()).filter(Boolean)
      const baseConfig = selectedWebsiteTemplateKey === CUSTOM_WEBSITE_TEMPLATE_KEY
        ? { ...createEmptyWebsiteConfig(), ...newWebsite }
        : createWebsiteConfigFromTemplateKey(selectedWebsiteTemplateKey, displayName)
      const internalName = buildUniqueWebsiteInternalName(
        selectedWebsiteTemplateKey === CUSTOM_WEBSITE_TEMPLATE_KEY
          ? displayName
          : `${selectedWebsiteTemplateKey}-${displayName}`,
        existingNames
      )
      const websitePayload = {
        ...baseConfig,
        name: internalName || baseConfig.name,
        display_name: displayName,
      }

      const res = await fetch('/api/websites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(websitePayload)
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('网站配置已添加')
        handleAddWebsiteDialogOpenChange(false)
        await fetchWebsites(true)
      } else {
        toast.error(getApiErrorMessage(data, '添加失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
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
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('网站配置已更新')
        setEditingWebsite(null)
        await fetchWebsites(true)
      } else {
        toast.error(getApiErrorMessage(data, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleDeleteWebsite = async (website: any) => {
    if (!confirm(`确定要删除网站配置 "${website.display_name}" 吗？`)) return
    try {
      const res = await fetch(`/api/websites/${website.id}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('网站配置已删除')
        await fetchWebsites(true)
      } else {
        toast.error(getApiErrorMessage(data, '删除失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const saveWebsiteSimilarity = async (websiteId: number, rawValue: string, options?: { silent?: boolean }) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/similarity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          image_similarity_threshold: rawValue === '' ? '' : rawValue
        })
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        applyWebsiteSimilarityState(websiteId, rawValue)
        if (!options?.silent) {
          toast.success('图片相似度已更新')
        }
      } else {
        toast.error(getApiErrorMessage(data, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const scheduleWebsiteSimilaritySave = (websiteId: number, rawValue: string) => {
    if (websiteSimilaritySaveTimersRef.current[websiteId]) {
      clearTimeout(websiteSimilaritySaveTimersRef.current[websiteId])
    }
    websiteSimilaritySaveTimersRef.current[websiteId] = setTimeout(() => {
      void saveWebsiteSimilarity(websiteId, rawValue, { silent: true })
    }, 450)
  }

  const saveWebsiteReplyDelay = async (
    websiteId: number,
    minValue: string,
    maxValue: string,
    options?: { silent?: boolean }
  ) => {
    if (websiteReplyDelaySaveTimersRef.current[websiteId]) {
      clearTimeout(websiteReplyDelaySaveTimersRef.current[websiteId])
      delete websiteReplyDelaySaveTimersRef.current[websiteId]
    }

    if (minValue === '' && maxValue === '') {
      try {
        const res = await fetch(`/api/websites/${websiteId}/rotation`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            reply_min_delay: '',
            reply_max_delay: '',
          })
        })
        const data = await res.json().catch(() => ({}))
        if (res.ok) {
          applyWebsiteReplyDelayState(websiteId, '', '')
          if (!options?.silent) {
            toast.success('站点回复延迟已清空')
          }
        } else {
          toast.error(getApiErrorMessage(data, '更新失败'))
        }
      } catch (e) {
        toast.error(getApiErrorMessage(e, '网络错误'))
      }
      return
    }

    if (minValue === '' || maxValue === '') {
      return
    }

    const min = Number(minValue)
    const max = Number(maxValue)
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      return
    }
    const [normalizedMin, normalizedMax] = normalizeReplyDelayRange(min, max)

    try {
      const res = await fetch(`/api/websites/${websiteId}/rotation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          reply_min_delay: normalizedMin,
          reply_max_delay: normalizedMax,
        })
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        applyWebsiteReplyDelayState(websiteId, String(normalizedMin), String(normalizedMax))
        if (!options?.silent) {
          toast.success('站点回复延迟已更新')
        }
      } else {
        toast.error(getApiErrorMessage(data, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const scheduleWebsiteReplyDelaySave = (websiteId: number, minValue: string, maxValue: string) => {
    if (websiteReplyDelaySaveTimersRef.current[websiteId]) {
      clearTimeout(websiteReplyDelaySaveTimersRef.current[websiteId])
    }
    websiteReplyDelaySaveTimersRef.current[websiteId] = setTimeout(() => {
      void saveWebsiteReplyDelay(websiteId, minValue, maxValue, { silent: true })
    }, 450)
  }

  const flushWebsiteReplyDelaySave = (websiteId: number, options?: { keepalive?: boolean }) => {
    const pendingTimer = websiteReplyDelaySaveTimersRef.current[websiteId]
    if (pendingTimer) {
      clearTimeout(pendingTimer)
      delete websiteReplyDelaySaveTimersRef.current[websiteId]
    }

    const current = websiteReplyDelayInputsRef.current[websiteId] ?? { min: '', max: '' }

    if (options?.keepalive) {
      const sendPayload = (payload: Record<string, unknown>) => {
        void fetch(`/api/websites/${websiteId}/rotation`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          keepalive: true,
          body: JSON.stringify(payload),
        }).catch(() => undefined)
      }

      if (current.min === '' && current.max === '') {
        sendPayload({
          reply_min_delay: '',
          reply_max_delay: '',
        })
        return
      }

      if (current.min === '' || current.max === '') {
        return
      }

      const min = Number(current.min)
      const max = Number(current.max)
      if (!Number.isFinite(min) || !Number.isFinite(max)) {
        return
      }

      const [normalizedMin, normalizedMax] = normalizeReplyDelayRange(min, max)
      sendPayload({
        reply_min_delay: normalizedMin,
        reply_max_delay: normalizedMax,
      })
      return
    }

    void saveWebsiteReplyDelay(websiteId, current.min, current.max, { silent: true })
  }

  const saveWebsiteKeywordMatchLimit = async (websiteId: number, rawValue: string, options?: { silent?: boolean }) => {
    const payload = {
      keyword_match_limit: rawValue === '' ? '' : rawValue,
    }
    try {
      const res = await fetch(`/api/websites/${websiteId}/rotation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        applyWebsiteKeywordMatchState(websiteId, rawValue)
        if (!options?.silent) {
          toast.success('关键词命中上限已更新')
        }
      } else {
        toast.error(getApiErrorMessage(data, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const scheduleWebsiteKeywordMatchLimitSave = (websiteId: number, rawValue: string) => {
    if (websiteKeywordMatchSaveTimersRef.current[websiteId]) {
      clearTimeout(websiteKeywordMatchSaveTimersRef.current[websiteId])
    }
    websiteKeywordMatchSaveTimersRef.current[websiteId] = setTimeout(() => {
      void saveWebsiteKeywordMatchLimit(websiteId, rawValue, { silent: true })
    }, 450)
  }

  const handleAddChannel = async (websiteId: number, channelId: string) => {
    if (!channelId.trim()) {
      toast.warning("频道ID不能为空")
      return
    }
    try {
      const res = await fetch(`/api/websites/${websiteId}/channels`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ channel_id: channelId.trim() })
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('频道绑定已添加')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteChannels(prev => ({
          ...prev,
          [websiteId]: [...(prev[websiteId] || []), channelId.trim()]
        }))
        setChannelInputs(prev => ({ ...prev, [websiteId]: '' }))
      } else {
        toast.error(getApiErrorMessage(data, '添加失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络连接错误，请稍后再试'))
    }
  }

  const confirmRemoveChannel = (websiteId: number, channelId: string) => {
    setChannelToRemove({ webId: websiteId, chanId: channelId })
  }

  const executeRemoveChannel = async () => {
    if (!channelToRemove) return
    const { webId, chanId } = channelToRemove
    try {
      // 【修复】如果channelId是完整的Discord URL，提取频道ID
      let actualChannelId = chanId
      if (chanId.includes('discord.com/channels/')) {
        const parts = chanId.split('/')
        actualChannelId = parts[parts.length - 1];
      }

      const res = await fetch(`/api/websites/${webId}/channels/${actualChannelId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('频道绑定已移除')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteChannels(prev => ({
          ...prev,
          [webId]: prev[webId]?.filter(id => id !== chanId) || []
        }))
      } else {
        toast.error(getApiErrorMessage(data, '移除失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    } finally {
      setChannelToRemove(null)
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
      const data = await res.json().catch(() => ({}))
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

        await refreshWebsiteRotationSettings(websiteId)

        setNewAccountBinding({ account_id: '', role: 'both' })
      } else {
        toast.error(getApiErrorMessage(data, '绑定失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleUnbindAccount = async (websiteId: number, accountId: number) => {
    try {
      const res = await fetch(`/api/websites/${websiteId}/accounts/${accountId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('账号解绑成功')
        // 立即更新前端状态，而不是重新获取所有数据
        setWebsiteAccounts(prev => ({
          ...prev,
          [websiteId]: prev[websiteId]?.filter(binding => binding.account_id !== accountId) || []
        }))
        await refreshWebsiteRotationSettings(websiteId)
      } else {
        toast.error(getApiErrorMessage(data, '解绑失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  // 轮换间隔设置
  const handleUpdateRotation = async (websiteId: number, rotationInterval: number) => {
    try {
      await updateWebsiteRotationSettings(
        websiteId,
        { rotation_interval: rotationInterval },
        '轮换间隔已更新'
      )
    } catch (e: any) {
      toast.error(e?.message || '网络错误')
    }
  }

  const handleUpdateKeywordBatchSize = async (websiteId: number, keywordReplyBatchSize: number) => {
    try {
      await updateWebsiteRotationSettings(
        websiteId,
        { keyword_reply_batch_size: keywordReplyBatchSize },
        keywordReplyBatchSize === 0 ? '单轮关键词上限已改为不限' : '单轮关键词上限已更新'
      )
    } catch (e: any) {
      toast.error(e?.message || '网络错误')
    }
  }

  const handleUpdateKeywordReplyInterval = async (websiteId: number, keywordReplyInterval: number) => {
    try {
      await updateWebsiteRotationSettings(
        websiteId,
        { keyword_reply_interval: keywordReplyInterval },
        '单轮关键词时间已更新'
      )
    } catch (e: any) {
      toast.error(e?.message || '网络错误')
    }
  }

  const handleUpdateKeywordBatchDispatchMode = async (
    websiteId: number,
    keywordBatchDispatchMode: string,
    fallbackMode: string,
  ) => {
    try {
      await updateWebsiteRotationSettings(
        websiteId,
        { keyword_batch_dispatch_mode: keywordBatchDispatchMode },
        `关键词发送方式已切换为${getKeywordBatchDispatchModeLabel(keywordBatchDispatchMode)}`
      )
    } catch (e: any) {
      setKeywordDispatchModes(prev => ({ ...prev, [websiteId]: fallbackMode }))
      toast.error(e?.message || '网络错误')
    }
  }

  const handleUpdateReplyMode = async (websiteId: number, replyMode: string) => {
    startTransition(() => {
      setPendingReplyModes(prev => ({ ...prev, [websiteId]: replyMode }))
      setReplyModeSaving(prev => ({ ...prev, [websiteId]: true }))
    })
    try {
      await updateWebsiteRotationSettings(
        websiteId,
        { reply_mode: replyMode },
        `已切换到${getReplyModeLabel(replyMode)}`
      )
    } catch (e: any) {
      toast.error(e?.message || '网络错误')
    } finally {
      clearPendingReplyModeState(websiteId)
    }
  }

  const handleReplyModeChange = async (websiteId: number, senderCount: number, replyMode: string) => {
    const switchError = getReplyModeSwitchError(senderCount, replyMode)
    if (switchError) {
      toast.error(switchError)
      return
    }

    await handleUpdateReplyMode(websiteId, replyMode)
  }

  // 网站过滤规则管理
  const handleAddWebsiteFilter = async (websiteId: number) => {
    try {
      let payload = { ...websiteNewFilter }

      if (websiteNewFilter.filter_type === 'image_filter') {
        const value = Number(websiteNewFilter.filter_value)
        const normalized = Number.isFinite(value) ? value : 0.95
        if (normalized < 0 || normalized > 1) {
          toast.error('相似度必须在0-1之间')
          return
        }
        if (websiteNewFilterImages.length === 0) {
          toast.error('图片过滤规则需要先上传至少1张图片')
          return
        }
        payload = { filter_type: 'image_filter', filter_value: String(normalized) }
      }

      if (websiteNewFilter.filter_type === 'numeric_range') {
        const normalized = normalizeNumericRangeFilter(websiteNewFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = { filter_type: 'numeric_range', filter_value: normalized.value }
      }

      if (websiteNewFilter.filter_type === 'user_repeat') {
        const seconds = Number(websiteNewFilter.filter_value)
        if (!Number.isFinite(seconds) || seconds <= 0) {
          toast.error('秒必须大于0')
          return
        }
        payload = { filter_type: 'user_repeat', filter_value: String(seconds) }
      }

      if (websiteNewFilter.filter_type === 'keyword_match_limit') {
        const normalized = normalizeKeywordMatchLimitFilter(websiteNewFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = { filter_type: 'keyword_match_limit', filter_value: normalized.value }
      }

      if (websiteNewFilter.filter_type === 'image') {
        payload = { filter_type: 'image', filter_value: '' }
      }

      if (websiteNewFilter.filter_type === 'role_id' || websiteNewFilter.filter_type === 'user_id') {
        const normalized = normalizeMultiValueFilterInput(websiteNewFilter.filter_value)
        if (!normalized) {
          toast.error(websiteNewFilter.filter_type === 'role_id' ? '身份组ID不能为空' : '用户ID不能为空')
          return
        }
        payload = { filter_type: websiteNewFilter.filter_type, filter_value: normalized }
      }

      const currentFilters = websiteFilters[websiteId] || []
      const newFilterId = createFilterId()
      const newFilters = [
        ...currentFilters,
        {
          id: newFilterId,
          filter_type: payload.filter_type,
          filter_value: payload.filter_value
        }
      ]

      const updateRes = await fetch(`/api/websites/${websiteId}/filters`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ filters: newFilters })
      })
      const updateData = await updateRes.json().catch(() => ({}))

      if (updateRes.ok) {
        const currentIds = new Set(currentFilters.map((item: any) => String(item.id)))
        const refreshedFilters = await fetchWebsiteFiltersForWebsite(websiteId)
        const finalFilters = refreshedFilters || newFilters
        let actualFilterId = newFilterId

        if (finalFilters.length > 0) {
          const matchById = finalFilters.find(item => String(item.id) === String(newFilterId))
          const addedFilters = finalFilters.filter(item => !currentIds.has(String(item.id)))
          const matchByValue = finalFilters.find(item =>
            item.filter_type === payload.filter_type && String(item.filter_value) === String(payload.filter_value)
          )
          actualFilterId = (matchById || addedFilters[0] || matchByValue || { id: newFilterId }).id
        }

        if (payload.filter_type === 'image_filter') {
          const uploadOk = await uploadWebsiteFilterImages(websiteId, String(actualFilterId), websiteNewFilterImages)
          if (!uploadOk) {
            toast.error('部分图片上传失败')
          } else {
            toast.success('图片过滤已添加')
          }
        } else {
          toast.success('过滤规则已添加')
        }

        if (!refreshedFilters) {
          setWebsiteFilters(prev => ({
            ...prev,
            [websiteId]: newFilters
          }))
        }
        setShowAddWebsiteFilter(null)
        setWebsiteNewFilter({ filter_type: 'contains', filter_value: '' })
        setWebsiteNewFilterImages([])
        if (websiteNewFilterImageInputRef.current) {
          websiteNewFilterImageInputRef.current.value = ''
        }
      } else {
        toast.error(getApiErrorMessage(updateData, '添加过滤规则失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleUpdateWebsiteFilter = async () => {
    if (!editingWebsiteFilter) return
    try {
      const { websiteId } = editingWebsiteFilter
      let filter = { ...editingWebsiteFilter.filter }
      if (!filter.id) {
        filter = { ...filter, id: createFilterId() }
      }

      if (filter.filter_type === 'image_filter') {
        const value = Number(filter.filter_value)
        const normalized = Number.isFinite(value) ? value : 0.95
        if (normalized < 0 || normalized > 1) {
          toast.error('相似度必须在0-1之间')
          return
        }
        filter.filter_value = String(normalized)
      }

      if (filter.filter_type === 'numeric_range') {
        const normalized = normalizeNumericRangeFilter(filter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        filter.filter_value = normalized.value
      }

      if (filter.filter_type === 'user_repeat') {
        const seconds = Number(filter.filter_value)
        if (!Number.isFinite(seconds) || seconds <= 0) {
          toast.error('秒必须大于0')
          return
        }
        filter.filter_value = String(seconds)
      }

      if (filter.filter_type === 'keyword_match_limit') {
        const normalized = normalizeKeywordMatchLimitFilter(filter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        filter.filter_value = normalized.value
      }

      if (filter.filter_type === 'image') {
        filter.filter_value = ''
      }

      if (filter.filter_type === 'role_id' || filter.filter_type === 'user_id') {
        const normalized = normalizeMultiValueFilterInput(filter.filter_value)
        if (!normalized) {
          toast.error(filter.filter_type === 'role_id' ? '身份组ID不能为空' : '用户ID不能为空')
          return
        }
        filter.filter_value = normalized
      }

      const currentFilters = websiteFilters[websiteId] || []
      const updatedFilters = currentFilters.map(item =>
        String(item.id || '') === String(filter.id) ? filter : item
      )

      const updateRes = await fetch(`/api/websites/${websiteId}/filters`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ filters: updatedFilters })
      })
      const updateData = await updateRes.json().catch(() => ({}))

      if (updateRes.ok) {
        let finalFilters = updatedFilters
        let resolvedFilterId = String(filter.id)
        const refreshedFilters = await fetchWebsiteFiltersForWebsite(websiteId)

        if (refreshedFilters) {
          finalFilters = refreshedFilters
          const matchById = refreshedFilters.find(item => String(item.id) === String(filter.id))
          const matchByValue = refreshedFilters.find(item =>
            item.filter_type === filter.filter_type && String(item.filter_value) === String(filter.filter_value)
          )
          const resolved = matchById || matchByValue
          if (resolved?.id) {
            resolvedFilterId = String(resolved.id)
          }
        }

        if (filter.filter_type === 'image_filter' && editingWebsiteFilterNewFiles.length > 0) {
          const uploadOk = await uploadWebsiteFilterImages(websiteId, resolvedFilterId, editingWebsiteFilterNewFiles)
          if (!uploadOk) {
            toast.error('部分图片上传失败')
          } else {
            toast.success('过滤规则已更新')
            fetchWebsiteFilterImages(websiteId, resolvedFilterId)
          }
          setEditingWebsiteFilterNewFiles([])
          if (websiteEditingFilterImageInputRef.current) {
            websiteEditingFilterImageInputRef.current.value = ''
          }
        } else {
          toast.success('过滤规则已更新')
        }
        if (!refreshedFilters) {
          setWebsiteFilters(prev => ({
            ...prev,
            [websiteId]: finalFilters
          }))
        }
        setEditingWebsiteFilter(null)
      } else {
        toast.error(getApiErrorMessage(updateData, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleRemoveWebsiteFilter = async (websiteId: number, filterId: string) => {
    try {
      const currentFilters = websiteFilters[websiteId] || []
      const newFilters = currentFilters.filter((filter: any) => String(filter.id) !== String(filterId))

      const updateRes = await fetch(`/api/websites/${websiteId}/filters`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ filters: newFilters })
      })
      const updateData = await updateRes.json().catch(() => ({}))

      if (updateRes.ok) {
        toast.success('过滤规则已删除')
        setWebsiteFilters(prev => ({
          ...prev,
          [websiteId]: newFilters
        }))
      } else {
        toast.error(getApiErrorMessage(updateData, '删除过滤规则失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  // 消息过滤处理函数
  const normalizeNumericRangeFilter = (rawValue: string) => {
    const fields = parseNumericRangeFilterValue(rawValue)
    const keyword = fields.keyword.trim()

    if (!keyword) {
      return { ok: false, error: '请输入匹配关键词' }
    }
    if (fields.min === '' || fields.max === '') {
      return { ok: false, error: '请输入完整的数字范围' }
    }

    const minValue = Number(fields.min)
    const maxValue = Number(fields.max)

    if (Number.isNaN(minValue) || Number.isNaN(maxValue)) {
      return { ok: false, error: '请输入有效的数字范围' }
    }
    if (minValue >= maxValue) {
      return { ok: false, error: '最小值必须小于最大值' }
    }

    return {
      ok: true,
      value: buildNumericRangeFilterValue({
        keyword,
        min: String(minValue),
        max: String(maxValue)
      })
    }
  }

  const updateNewNumericFilter = (patch: Partial<NumericRangeFilterValue>) => {
    const current = parseNumericRangeFilterValue(newFilter.filter_value)
    const next = { ...current, ...patch }
    setNewFilter(prev => ({
      ...prev,
      filter_value: buildNumericRangeFilterValue(next)
    }))
  }

  const updateEditingNumericFilter = (patch: Partial<NumericRangeFilterValue>) => {
    if (!editingFilter) return
    const current = parseNumericRangeFilterValue(editingFilter.filter_value)
    const next = { ...current, ...patch }
    setEditingFilter((prev: any) => ({
      ...prev,
      filter_value: buildNumericRangeFilterValue(next)
    }))
  }

  const updateWebsiteNewNumericFilter = (patch: Partial<NumericRangeFilterValue>) => {
    const current = parseNumericRangeFilterValue(websiteNewFilter.filter_value)
    const next = { ...current, ...patch }
    setWebsiteNewFilter(prev => ({
      ...prev,
      filter_value: buildNumericRangeFilterValue(next)
    }))
  }

  const updateWebsiteEditingNumericFilter = (patch: Partial<NumericRangeFilterValue>) => {
    if (!editingWebsiteFilter) return
    const current = parseNumericRangeFilterValue(editingWebsiteFilter.filter.filter_value)
    const next = { ...current, ...patch }
    setEditingWebsiteFilter((prev: any) => ({
      ...prev,
      filter: {
        ...prev.filter,
        filter_value: buildNumericRangeFilterValue(next)
      }
    }))
  }

  const handleAddMessageFilter = async () => {
    try {
      let payload = { ...newFilter }
      if (newFilter.filter_type === 'image_filter') {
        const value = Number(newFilter.filter_value)
        const normalized = Number.isFinite(value) ? value : 0.95
        if (normalized < 0 || normalized > 1) {
          toast.error('相似度必须在0-1之间')
          return
        }
        if (newFilterImages.length === 0) {
          toast.error('图片过滤规则需要先上传至少1张图片')
          return
        }
        payload = { filter_type: 'image_filter', filter_value: String(normalized) }
      }
      if (newFilter.filter_type === 'numeric_range') {
        const normalized = normalizeNumericRangeFilter(newFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = { filter_type: 'numeric_range', filter_value: normalized.value }
      }
      if (newFilter.filter_type === 'user_repeat') {
        const seconds = Number(newFilter.filter_value)
        if (!Number.isFinite(seconds) || seconds <= 0) {
          toast.error('秒必须大于0')
          return
        }
        payload = { filter_type: 'user_repeat', filter_value: String(seconds) }
      }

      if (newFilter.filter_type === 'keyword_match_limit') {
        const normalized = normalizeKeywordMatchLimitFilter(newFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = { filter_type: 'keyword_match_limit', filter_value: normalized.value }
      }

      if (newFilter.filter_type === 'role_id' || newFilter.filter_type === 'user_id') {
        const normalized = normalizeMultiValueFilterInput(newFilter.filter_value)
        if (!normalized) {
          toast.error(newFilter.filter_type === 'role_id' ? '身份组ID不能为空' : '用户ID不能为空')
          return
        }
        payload = { filter_type: newFilter.filter_type, filter_value: normalized }
      }

      const res = await fetch('/api/message-filters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        if (newFilter.filter_type === 'image_filter') {
          const filterId = data.id
          if (!filterId) {
            toast.error('创建过滤规则失败')
            return
          }
          const uploadOk = await uploadMessageFilterImages(filterId, newFilterImages)
          if (!uploadOk) {
            toast.error('部分图片上传失败，请检查')
          } else {
            toast.success('图片过滤已添加')
          }
          setNewFilterImages([])
          if (newFilterImageInputRef.current) {
            newFilterImageInputRef.current.value = ''
          }
        } else {
          toast.success('过滤规则添加成功')
        }
        setShowAddFilter(false)
        setNewFilter({ filter_type: 'contains', filter_value: '' })
        await fetchMessageFilters()
      } else {
        toast.error(getApiErrorMessage(data, '添加失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleUpdateMessageFilter = async () => {
    if (!editingFilter) return
    try {
      let payload = {
        filter_type: editingFilter.filter_type,
        filter_value: editingFilter.filter_value,
        is_active: editingFilter.is_active
      }

      if (editingFilter.filter_type === 'image_filter') {
        const value = Number(editingFilter.filter_value)
        const normalized = Number.isFinite(value) ? value : 0.95
        if (normalized < 0 || normalized > 1) {
          toast.error('相似度必须在0-1之间')
          return
        }
        payload = {
          ...payload,
          filter_value: String(normalized)
        }
      }
      if (editingFilter.filter_type === 'numeric_range') {
        const normalized = normalizeNumericRangeFilter(editingFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = {
          ...payload,
          filter_value: normalized.value
        }
      }
      if (editingFilter.filter_type === 'user_repeat') {
        const seconds = Number(editingFilter.filter_value)
        if (!Number.isFinite(seconds) || seconds <= 0) {
          toast.error('秒必须大于0')
          return
        }
        payload = {
          ...payload,
          filter_value: String(seconds)
        }
      }

      if (editingFilter.filter_type === 'keyword_match_limit') {
        const normalized = normalizeKeywordMatchLimitFilter(editingFilter.filter_value)
        if (!normalized.ok) {
          toast.error(normalized.error)
          return
        }
        payload = {
          ...payload,
          filter_value: normalized.value
        }
      }

      if (editingFilter.filter_type === 'role_id' || editingFilter.filter_type === 'user_id') {
        const normalized = normalizeMultiValueFilterInput(editingFilter.filter_value)
        if (!normalized) {
          toast.error(editingFilter.filter_type === 'role_id' ? '身份组ID不能为空' : '用户ID不能为空')
          return
        }
        payload = {
          ...payload,
          filter_value: normalized
        }
      }

      const res = await fetch(`/api/message-filters/${editingFilter.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('过滤规则更新成功')
        setEditingFilter(null)
        await fetchMessageFilters()
      } else {
        toast.error(getApiErrorMessage(data, '更新失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const handleDeleteMessageFilter = async (filterId: number) => {
    if (!confirm('确定要删除这个过滤规则吗？')) return
    try {
      const res = await fetch(`/api/message-filters/${filterId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        toast.success('过滤规则删除成功')
        await fetchMessageFilters()
      } else {
        toast.error(getApiErrorMessage(data, '删除失败'))
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e, '网络错误'))
    }
  }

  const totalAccountPages = Math.ceil(accounts.length / accountsPerPage)
  const paginatedAccounts = accounts.slice((accountPage - 1) * accountsPerPage, accountPage * accountsPerPage)

  useEffect(() => {
    if (totalAccountPages > 0 && accountPage > totalAccountPages) {
      setAccountPage(totalAccountPages)
    }
  }, [accountPage, totalAccountPages])

  useEffect(() => {
    if (editingFilter && editingFilter.filter_type === 'image_filter') {
      fetchMessageFilterImages(editingFilter.id)
    } else {
      setEditingFilterImages([])
      setEditingFilterNewFiles([])
      if (editingFilterImageInputRef.current) {
        editingFilterImageInputRef.current.value = ''
      }
    }
  }, [editingFilter?.id, editingFilter?.filter_type])

  useEffect(() => {
    if (editingWebsiteFilter && editingWebsiteFilter.filter?.filter_type === 'image_filter') {
      fetchWebsiteFilterImages(editingWebsiteFilter.websiteId, editingWebsiteFilter.filter.id)
    } else {
      setEditingWebsiteFilterImages([])
      setEditingWebsiteFilterNewFiles([])
      if (websiteEditingFilterImageInputRef.current) {
        websiteEditingFilterImageInputRef.current.value = ''
      }
    }
  }, [editingWebsiteFilter?.websiteId, editingWebsiteFilter?.filter?.id, editingWebsiteFilter?.filter?.filter_type])


  return (
    <div className="space-y-8" data-tutorial="accounts-root">
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
          {paginatedAccounts.map((account) => (
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
        {totalAccountPages > 1 && (
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4 mt-4 pt-4 border-t">
            <div className="text-sm text-muted-foreground font-medium">
              显示第 {(accountPage - 1) * accountsPerPage + 1} - {Math.min(accountPage * accountsPerPage, accounts.length)} 条，共 {accounts.length} 条记录
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={accountPage === 1}
                onClick={() => setAccountPage(page => page - 1)}
              >
                上一页
              </Button>
              <div className="text-sm font-medium bg-primary text-primary-foreground px-3 py-1 rounded">
                {accountPage} / {totalAccountPages}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={accountPage === totalAccountPages}
                onClick={() => setAccountPage(page => page + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        )}
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
            {/* 相似度和延迟设置 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-tutorial="accounts-global-settings">
              <div className="space-y-2">
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

              <div className="space-y-2" data-tutorial="accounts-delay-settings">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium" htmlFor="min-delay">回复延迟</Label>
                  <span className="text-sm font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded">
                    {settings.global_reply_min_delay}-{settings.global_reply_max_delay}s
                  </span>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1">
                      <Input
                        id="min-delay"
                        type="number"
                        step={REPLY_DELAY_STEP}
                        min={REPLY_DELAY_MIN}
                        max={REPLY_DELAY_MAX - REPLY_DELAY_STEP}
                        value={settings.global_reply_min_delay}
                        onChange={(e) => {
                          const value = parseFloat(e.target.value)
                          if (!isNaN(value) && value >= REPLY_DELAY_MIN && value <= REPLY_DELAY_MAX - REPLY_DELAY_STEP) {
                            setSettings(prev => {
                              const next = normalizeReplyDelayRange(value, prev.global_reply_max_delay)
                              return {
                                ...prev,
                                global_reply_min_delay: next.minDelay,
                                global_reply_max_delay: next.maxDelay,
                              }
                            })
                          }
                        }}
                        className="w-24 h-9 text-center"
                      />
                      <span className="text-sm text-muted-foreground">-</span>
                      <Input
                        id="max-delay"
                        type="number"
                        step={REPLY_DELAY_STEP}
                        min={getMinimumReplyMaxDelay(settings.global_reply_min_delay)}
                        max={REPLY_DELAY_MAX}
                        value={settings.global_reply_max_delay}
                        onChange={(e) => {
                          const value = parseFloat(e.target.value)
                          if (!isNaN(value) && value >= getMinimumReplyMaxDelay(settings.global_reply_min_delay) && value <= REPLY_DELAY_MAX) {
                            setSettings(prev => {
                              const next = normalizeReplyDelayRange(prev.global_reply_min_delay, value)
                              return {
                                ...prev,
                                global_reply_min_delay: next.minDelay,
                                global_reply_max_delay: next.maxDelay,
                              }
                            })
                          }
                        }}
                        className="w-24 h-9 text-center"
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

            <div className="space-y-4 border-t pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="bark-enabled" className="text-sm font-medium">iPhone Bark 通知</Label>
                  <p className="text-xs text-muted-foreground mt-1">
                    当任一已添加账号被他人回复或 @ 时，立即推送到 iPhone
                  </p>
                </div>
                <Switch
                  id="bark-enabled"
                  checked={settings.bark_enabled}
                  onCheckedChange={(checked) => {
                    setSettings(prev => {
                      const next = { ...prev, bark_enabled: checked }
                      scheduleBarkAutoSave(next, 120)
                      return next
                    })
                  }}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label htmlFor="bark-server-url" className="text-sm">Bark 服务地址</Label>
                  <Input
                    id="bark-server-url"
                    type="text"
                    value={settings.bark_server_url}
                    onChange={(e) => {
                      const value = e.target.value
                      setSettings(prev => {
                        const next = { ...prev, bark_server_url: value }
                        scheduleBarkAutoSave(next)
                        return next
                      })
                    }}
                    placeholder="https://api.day.app"
                    className="h-9"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="bark-device-key" className="text-sm">Bark 设备 Key</Label>
                  <Input
                    id="bark-device-key"
                    type="password"
                    value={settings.bark_device_key}
                    onChange={(e) => {
                      const value = e.target.value
                      setSettings(prev => {
                        const next = { ...prev, bark_device_key: value }
                        scheduleBarkAutoSave(next)
                        return next
                      })
                    }}
                    placeholder="从 Bark App 复制"
                    className="h-9"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {barkAutoSaving ? "Bark 配置自动保存中..." : "Bark 配置改动会自动保存"}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleTestBarkNotification}
                  disabled={barkTesting}
                >
                  {barkTesting ? "测试推送中..." : "发送测试推送"}
                </Button>
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
                <Label>回复模板</Label>
                <Textarea
                  value={editingWebsite.reply_template || '{url}'}
                  onChange={e => setEditingWebsite(prev => ({ ...prev, reply_template: e.target.value }))}
                  rows={3}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  使用 <span className="font-mono">{`{url}`}</span> 作为链接占位符。
                </p>
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

        {/* 消息过滤设置 - 每个用户独立配置 */}
        {currentUser && (
          <Card className="mt-6" data-tutorial="accounts-message-filters">
            <CardHeader>
              <div className="flex justify-between items-center">
                <div>
                  <CardTitle className="text-lg">消息过滤</CardTitle>
                  <CardDescription>设置账号不回复的消息内容规则</CardDescription>
                </div>
                <Dialog
                  open={showAddFilter}
                  onOpenChange={(open) => {
                    setShowAddFilter(open)
                    if (!open) {
                      setNewFilter({ filter_type: 'contains', filter_value: '' })
                      setNewFilterImages([])
                      if (newFilterImageInputRef.current) {
                        newFilterImageInputRef.current.value = ''
                      }
                    }
                  }}
                >
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
                        <Select
                          value={newFilter.filter_type}
                          onValueChange={value => {
                            setNewFilter(prev => ({
                              ...prev,
                              filter_type: value,
                              filter_value: getDefaultFilterValueForType(value)
                            }))
                            if (value !== 'image_filter') {
                              setNewFilterImages([])
                              if (newFilterImageInputRef.current) {
                                newFilterImageInputRef.current.value = ''
                              }
                            }
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="contains">包含文本</SelectItem>
                            <SelectItem value="starts_with">开头是</SelectItem>
                            <SelectItem value="ends_with">结尾是</SelectItem>
                            <SelectItem value="regex">正则表达式</SelectItem>
                            <SelectItem value="image">图片消息</SelectItem>
                            <SelectItem value="user_id">用户ID</SelectItem>
                            <SelectItem value="role_id">身份组ID</SelectItem>
                            <SelectItem value="image_filter">图片过滤</SelectItem>
                            <SelectItem value="numeric_range">数字范围</SelectItem>
                            <SelectItem value="user_repeat">用户重复发送</SelectItem>
                            <SelectItem value="keyword_match_limit">关键词命中上限</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>过滤值</Label>
                        {newFilter.filter_type === 'numeric_range' ? (
                          <div className="space-y-3">
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">匹配关键词</Label>
                              <Input
                                value={parseNumericRangeFilterValue(newFilter.filter_value).keyword}
                                onChange={e => updateNewNumericFilter({ keyword: e.target.value })}
                                placeholder="例如: size"
                                className="h-9"
                              />
                            </div>
                            <div className="flex items-center gap-3">
                              <div className="flex items-center gap-2">
                                <span className="text-xs text-muted-foreground">小于</span>
                                <Input
                                  type="number"
                                  value={parseNumericRangeFilterValue(newFilter.filter_value).min}
                                  onChange={e => updateNewNumericFilter({ min: e.target.value })}
                                  className="w-24 h-9"
                                />
                                <span className="text-xs text-muted-foreground">不回复</span>
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs text-muted-foreground">大于</span>
                                <Input
                                  type="number"
                                  value={parseNumericRangeFilterValue(newFilter.filter_value).max}
                                  onChange={e => updateNewNumericFilter({ max: e.target.value })}
                                  className="w-24 h-9"
                                />
                                <span className="text-xs text-muted-foreground">不回复</span>
                              </div>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              匹配关键词后面的数字（如 "size 49"），超出范围将忽略该消息。
                            </p>
                          </div>
                        ) : newFilter.filter_type === 'user_repeat' ? (
                          <div className="flex items-center gap-2">
                          <Label className="text-xs text-muted-foreground">重复间隔(秒)</Label>
                            <Input
                              type="number"
                              step="1"
                              min="1"
                              value={newFilter.filter_value}
                              onChange={e => setNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                              className="h-8 w-24 text-xs"
                              placeholder="5"
                            />
                            <span className="text-xs text-muted-foreground">同一用户相同商品</span>
                          </div>
                        ) : newFilter.filter_type === 'image_filter' ? (
                          <div className="space-y-3">
                            <div className="flex items-center gap-2">
                              <Label className="text-xs text-muted-foreground">相似度阈值(0-1)</Label>
                              <Input
                                type="number"
                                step="0.01"
                                value={newFilter.filter_value}
                                onChange={e => setNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                                placeholder="0.95"
                                className="h-8 w-24 text-xs"
                              />
                              <span className="text-xs text-muted-foreground">≥该值即过滤</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <Input
                                ref={newFilterImageInputRef}
                                type="file"
                                accept="image/*"
                                multiple
                                className="h-8 text-xs"
                                onChange={(e) => setNewFilterImages(Array.from(e.target.files || []))}
                              />
                              <span className="text-xs text-muted-foreground">
                                已选 {newFilterImages.length} 张
                              </span>
                            </div>
                            {newFilterImages.length === 0 && (
                              <p className="text-xs text-amber-600">
                                添加前请先上传至少 1 张图片
                              </p>
                            )}
                            {newFilterImages.length > 0 && (
                              <div className="flex flex-wrap gap-2">
                                {newFilterImages.map((file, idx) => (
                                  <div key={`${file.name}-${idx}`} className="flex items-center gap-1 rounded bg-muted px-2 py-1 text-xs">
                                    <span className="max-w-[140px] truncate">{file.name}</span>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-4 w-4 p-0"
                                      onClick={() => setNewFilterImages(prev => prev.filter((_, i) => i !== idx))}
                                    >
                                      <X className="w-3 h-3" />
                                    </Button>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : newFilter.filter_type === 'image' ? (
                          <div className="text-xs text-muted-foreground">图片消息无需填写过滤值</div>
                        ) : (
                          <Input
                            value={newFilter.filter_value}
                            onChange={e => setNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                            placeholder={getFilterValuePlaceholder(newFilter.filter_type)}
                          />
                        )}
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setShowAddFilter(false)}>取消</Button>
                      <Button
                        onClick={handleAddMessageFilter}
                        disabled={newFilter.filter_type === 'image_filter' && newFilterImages.length === 0}
                      >
                        添加规则
                      </Button>
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
                      <div className="font-medium">{formatMessageFilterLabel(filter)}</div>
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

        {/* 网站配置区域 - 所有登录用户可见 */}
        {currentUser && (
        <Card className="mt-6" data-tutorial="accounts-websites-list">
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
                  <Dialog open={showAddWebsite} onOpenChange={handleAddWebsiteDialogOpenChange}>
                  <DialogTrigger asChild>
                    <Button size="sm" data-tutorial="accounts-add-website">
                      <Plus className="w-4 h-4 mr-2" />
                      添加网站
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>添加网站配置</DialogTitle>
                      <DialogDescription>优先选择内置模板；需要特殊站点时再用自定义手填</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4" data-tutorial="accounts-template-dialog">
                      <div>
                        <Label>网站模板</Label>
                        <Select
                          value={selectedWebsiteTemplateKey}
                          onValueChange={value => {
                            setSelectedWebsiteTemplateKey(value)
                            if (value === CUSTOM_WEBSITE_TEMPLATE_KEY) {
                              setNewWebsite(createEmptyWebsiteConfig())
                            } else {
                              setNewWebsite(createWebsiteConfigFromTemplateKey(value))
                            }
                          }}
                        >
                          <SelectTrigger data-tutorial="accounts-template-select">
                            <SelectValue placeholder="选择内置网站模板" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={CUSTOM_WEBSITE_TEMPLATE_KEY}>自定义</SelectItem>
                            {BUILTIN_WEBSITE_TEMPLATES.map(template => (
                              <SelectItem key={template.key} value={template.key}>
                                {template.display_name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>显示名称</Label>
                        <Input
                          data-tutorial="accounts-template-name"
                          value={newWebsite.display_name}
                          onChange={e => setNewWebsite(prev => ({ ...prev, display_name: e.target.value }))}
                          placeholder={getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.display_name || '例如: Kakobuy 2'}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          这个名字只影响页面展示。系统内部标识会自动生成并去重。
                        </p>
                      </div>
                      {selectedWebsiteTemplateKey === CUSTOM_WEBSITE_TEMPLATE_KEY ? (
                        <div className="space-y-4" data-tutorial="accounts-template-custom-fields">
                          <div>
                            <Label>URL模板</Label>
                            <Input
                              value={newWebsite.url_template}
                              onChange={e => setNewWebsite(prev => ({ ...prev, url_template: e.target.value }))}
                              placeholder="https://www.kakobuy.com/item/details?url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}"
                            />
                          </div>
                          <div>
                            <Label>回复模板</Label>
                            <Textarea
                              value={newWebsite.reply_template}
                              onChange={e => setNewWebsite(prev => ({ ...prev, reply_template: e.target.value }))}
                              placeholder="{url}"
                              rows={3}
                            />
                            <p className="text-xs text-muted-foreground mt-1">
                              使用 <span className="font-mono">{`{url}`}</span> 作为链接占位符。
                            </p>
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
                      ) : (
                        <div className="rounded-lg border bg-muted/30 p-3 text-sm space-y-2">
                          <div className="font-medium">{getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.display_name}</div>
                          <div className="text-muted-foreground">
                            {getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.description}
                          </div>
                          <div className="text-xs text-muted-foreground break-all">
                            URL 模板: {getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.url_template}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            ID 模式: {getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.id_pattern}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            回复模板: {getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.reply_template}
                          </div>
                          <div className="text-xs text-muted-foreground break-all">
                            内部标识预览: {buildUniqueWebsiteInternalName(
                              `${selectedWebsiteTemplateKey}-${newWebsite.display_name || getWebsiteTemplateByKey(selectedWebsiteTemplateKey)?.display_name || ''}`,
                              websites.map(website => String(website.name || '').trim()).filter(Boolean)
                            ) || '自动生成'}
                          </div>
                        </div>
                      )}
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => handleAddWebsiteDialogOpenChange(false)}>取消</Button>
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
                  <div key={website.id} className="border rounded-lg p-4 space-y-4">
                    <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                      <div className="space-y-2 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center rounded-md border font-semibold w-fit whitespace-nowrap text-xs px-2.5 py-0.5 h-6 border-none shrink-0 text-white ${
                            website.badge_color === 'blue' ? 'bg-blue-600' :
                            website.badge_color === 'green' ? 'bg-green-600' :
                            website.badge_color === 'orange' ? 'bg-orange-600' :
                            website.badge_color === 'red' ? 'bg-red-600' :
                            website.badge_color === 'purple' ? 'bg-purple-600' :
                            'bg-gray-600'
                          }`}>
                            {website.display_name}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          <div>URL模板: {website.url_template}</div>
                          <div>ID模式: {website.id_pattern}</div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 self-start lg:self-auto">
                        {/* 只有管理员可以编辑/删除网站定义 */}
                        {currentUser?.role === 'admin' && (
                          <div className="flex gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => setEditingWebsite(formatWebsiteForEdit(website))}
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
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2 text-center">
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">总回复</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_total || 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">文本回复</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_text || 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">图片回复</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_image || 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">今日总</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_daily_total || 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">今日文本</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_daily_text || 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">今日图片</div>
                        <div className="text-base font-semibold leading-none mt-1">{website.stat_replies_daily_image || 0}</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-tutorial="accounts-website-overrides">
                      <div className="space-y-2" data-tutorial="accounts-website-threshold">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="text-sm font-medium truncate">相似度阈值</div>
                            <span className="text-xs font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded shrink-0">
                              {websiteSimilarityInputs[website.id] === '' || websiteSimilarityInputs[website.id] === undefined
                                ? '继承全局'
                                : Number(websiteSimilarityInputs[website.id]).toFixed(2)}
                            </span>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Input
                            type="number"
                            step="0.01"
                            placeholder="继承全局"
                            value={websiteSimilarityInputs[website.id] ?? ''}
                            onChange={e => {
                              const value = e.target.value
                              setWebsiteSimilarityInputs(prev => ({ ...prev, [website.id]: value }))
                              scheduleWebsiteSimilaritySave(website.id, value)
                            }}
                            className="h-9 text-xs"
                          />
                        </div>
                      </div>

                      <div className="space-y-2" data-tutorial="accounts-website-delay">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="text-sm font-medium truncate">回复延迟</div>
                            <span className="text-xs font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded shrink-0">
                              {(() => {
                                const current = websiteReplyDelayInputs[website.id]
                                const minDelay = current?.min ?? ''
                                const maxDelay = current?.max ?? ''
                                if (!minDelay && !maxDelay) return '继承全局'
                                if (!minDelay || !maxDelay) return '未完成'
                                return `${minDelay}-${maxDelay}s`
                              })()}
                            </span>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <div className="flex items-center gap-1">
                              <Input
                                type="number"
                                step={REPLY_DELAY_STEP}
                                min={REPLY_DELAY_MIN}
                                max={REPLY_DELAY_MAX - REPLY_DELAY_STEP}
                                placeholder="继承全局"
                                value={websiteReplyDelayInputs[website.id]?.min ?? ''}
                                onChange={e => {
                                  const min = e.target.value
                                  const current = websiteReplyDelayInputs[website.id] ?? { min: '', max: '' }
                                  const next = { ...current, min }
                                  websiteReplyDelayInputsRef.current = { ...websiteReplyDelayInputsRef.current, [website.id]: next }
                                  setWebsiteReplyDelayInputs(prev => ({ ...prev, [website.id]: next }))
                                  scheduleWebsiteReplyDelaySave(website.id, next.min, next.max)
                                }}
                                onBlur={() => {
                                  flushWebsiteReplyDelaySave(website.id)
                                }}
                                className="w-24 h-9 text-center"
                              />
                              <span className="text-sm text-muted-foreground">-</span>
                              <Input
                                type="number"
                                step={REPLY_DELAY_STEP}
                                min={REPLY_DELAY_MIN}
                                max={REPLY_DELAY_MAX}
                                placeholder="继承全局"
                                value={websiteReplyDelayInputs[website.id]?.max ?? ''}
                                onChange={e => {
                                  const max = e.target.value
                                  const current = websiteReplyDelayInputs[website.id] ?? { min: '', max: '' }
                                  const next = { ...current, max }
                                  websiteReplyDelayInputsRef.current = { ...websiteReplyDelayInputsRef.current, [website.id]: next }
                                  setWebsiteReplyDelayInputs(prev => ({ ...prev, [website.id]: next }))
                                  scheduleWebsiteReplyDelaySave(website.id, next.min, next.max)
                                }}
                                onBlur={() => {
                                  flushWebsiteReplyDelaySave(website.id)
                                }}
                                className="w-24 h-9 text-center"
                              />
                            </div>
                            <span className="text-xs text-muted-foreground">秒</span>
                          </div>
                        </div>
                      </div>

                    </div>

                    {/* 频道绑定 */}
                    <div className="space-y-2" data-tutorial="accounts-website-filters">
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
                              onClick={() => confirmRemoveChannel(website.id, channelId)}
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
                        {(websiteAccounts[website.id] || []).map((binding: any) => {
                          const remaining = getCooldownRemaining(binding.account_id, website.id)
                          return (
                            <div key={binding.id} className="flex flex-col items-start bg-muted rounded px-2 py-1 border">
                              <div className="flex items-center gap-1">
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
                              <CooldownTimer remaining={remaining} />
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    {/* 账号轮换设置 - 每个用户独立配置 */}
                    {currentUser && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Settings className="w-4 h-4" />
                          <span className="text-sm font-medium">轮换设置</span>
                        </div>
                        {(() => {
                          const senderCount = getWebsiteSenderCount(website.id)
                          const replyMode = getWebsiteReplyMode(website)
                          const keywordModeDisabled = isReplyModeOptionDisabled(senderCount, 'keyword')
                          const isReplyModeSaving = Boolean(replyModeSaving[website.id])
                          const isKeywordMode = replyMode === 'keyword'
                          const settingsSection = getReplyModeSettingsSection(replyMode)
                          const keywordBatchDispatchMode = keywordDispatchModes[website.id] ?? (website.keyword_batch_dispatch_mode ?? 'immediate')

                          return (
                            <>
                              <div className="flex items-center gap-2">
                                <Label className="text-xs">回复模式:</Label>
                                <Select
                                  value={replyMode}
                                  disabled={isReplyModeSaving}
                                  onValueChange={(value) => {
                                    void handleReplyModeChange(website.id, senderCount, value)
                                  }}
                                >
                                  <SelectTrigger className="w-[180px] h-8 text-xs">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="default">默认模式</SelectItem>
                                    <SelectItem value="rotation">轮换模式</SelectItem>
                                    <SelectItem value="keyword" disabled={keywordModeDisabled}>
                                      关键词模式
                                    </SelectItem>
                                  </SelectContent>
                                </Select>
                                {isReplyModeSaving ? (
                                  <span className="text-[11px] text-muted-foreground">保存中...</span>
                                ) : null}
                              </div>

                              {settingsSection === 'rotation' ? (
                                <div className="flex items-center gap-2">
                                  <Label className="text-xs">账号轮换间隔(秒):</Label>
                                  <Input
                                    type="number"
                                    value={rotationInputs[website.id] ?? (website.rotation_interval ?? 180).toString()}
                                    className="w-20 h-7 text-xs"
                                    onChange={(e) => {
                                      const value = e.target.value
                                      setRotationInputs(prev => ({ ...prev, [website.id]: value }))
                                    }}
                                    onBlur={() => {
                                      const value = parseInt(rotationInputs[website.id] ?? (website.rotation_interval ?? 180).toString())
                                      if (value > 0 && value !== website.rotation_interval) {
                                        void handleUpdateRotation(website.id, value)
                                      } else if (value <= 0) {
                                        toast.error('轮换间隔必须大于0秒')
                                        setRotationInputs(prev => ({ ...prev, [website.id]: (website.rotation_interval ?? 180).toString() }))
                                      }
                                    }}
                                  />
                                  <span className="text-xs text-muted-foreground">
                                    ({(() => {
                                      const v = parseInt(rotationInputs[website.id] ?? (website.rotation_interval ?? 180).toString())
                                      const sec = Number.isFinite(v) ? v : (website.rotation_interval ?? 180)
                                      return `${Math.floor(sec / 60)}分${sec % 60}秒`
                                    })()})
                                  </span>
                                </div>
                              ) : settingsSection === 'keyword' ? (
                                <>
                                  <div className="flex items-center gap-2">
                                    <Label className="text-xs">单轮关键词时间(秒):</Label>
                                    <Input
                                      type="number"
                                      value={keywordIntervalInputs[website.id] ?? (website.keyword_reply_interval ?? website.rotation_interval ?? 180).toString()}
                                      className="w-20 h-7 text-xs"
                                      disabled={senderCount !== 1}
                                      onChange={(e) => {
                                        const value = e.target.value
                                        setKeywordIntervalInputs(prev => ({ ...prev, [website.id]: value }))
                                      }}
                                      onBlur={() => {
                                        const value = parseInt(
                                          keywordIntervalInputs[website.id]
                                          ?? (website.keyword_reply_interval ?? website.rotation_interval ?? 180).toString()
                                        )
                                        const current = website.keyword_reply_interval ?? website.rotation_interval ?? 180
                                        if (value > 0 && value !== current) {
                                          void handleUpdateKeywordReplyInterval(website.id, value)
                                        } else if (value <= 0) {
                                          toast.error('单轮关键词时间必须大于0秒')
                                          setKeywordIntervalInputs(prev => ({
                                            ...prev,
                                            [website.id]: current.toString()
                                          }))
                                        }
                                      }}
                                    />
                                    <span className="text-xs text-muted-foreground">
                                      ({(() => {
                                        const v = parseInt(
                                          keywordIntervalInputs[website.id]
                                          ?? (website.keyword_reply_interval ?? website.rotation_interval ?? 180).toString()
                                        )
                                        const sec = Number.isFinite(v) ? v : (website.keyword_reply_interval ?? website.rotation_interval ?? 180)
                                        return `${Math.floor(sec / 60)}分${sec % 60}秒`
                                      })()})
                                    </span>
                                  </div>

                                  <div className="flex items-center gap-2">
                                    <Label className="text-xs">单轮关键词上限:</Label>
                                    <Input
                                      type="number"
                                      min="0"
                                      value={keywordBatchInputs[website.id] ?? (website.keyword_reply_batch_size ?? 0).toString()}
                                      className="w-20 h-7 text-xs"
                                      disabled={senderCount !== 1}
                                      onChange={(e) => {
                                        const value = e.target.value
                                        setKeywordBatchInputs(prev => ({ ...prev, [website.id]: value }))
                                      }}
                                      onBlur={() => {
                                        const rawValue = keywordBatchInputs[website.id] ?? (website.keyword_reply_batch_size ?? 0).toString()
                                        const value = parseInt(rawValue)
                                        if (Number.isFinite(value) && value >= 0 && value !== (website.keyword_reply_batch_size ?? 0)) {
                                          void handleUpdateKeywordBatchSize(website.id, value)
                                        } else if (!Number.isFinite(value) || value < 0) {
                                          toast.error('单轮关键词上限不能小于0')
                                          setKeywordBatchInputs(prev => ({
                                            ...prev,
                                            [website.id]: (website.keyword_reply_batch_size ?? 0).toString()
                                          }))
                                        }
                                      }}
                                    />
                                    <span className="text-xs text-muted-foreground">
                                      0 = 不限制
                                    </span>
                                  </div>

                                  <div className="flex items-center gap-2">
                                    <Label className="text-xs">关键词发送方式:</Label>
                                    <Select
                                      value={keywordBatchDispatchMode}
                                      disabled={senderCount !== 1}
                                      onValueChange={(value) => {
                                        setKeywordDispatchModes(prev => ({ ...prev, [website.id]: value }))
                                        if (value !== (website.keyword_batch_dispatch_mode ?? 'immediate')) {
                                          void handleUpdateKeywordBatchDispatchMode(
                                            website.id,
                                            value,
                                            website.keyword_batch_dispatch_mode ?? 'immediate',
                                          )
                                        }
                                      }}
                                    >
                                      <SelectTrigger className="w-[220px] h-8 text-xs">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="immediate">达到上限立即发送</SelectItem>
                                        <SelectItem value="window_end">达到上限后停收，窗口结束统一发送</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </>
                              ) : null}

                              <div className="text-xs text-muted-foreground space-y-1">
                                <div>
                                  {senderCount === 0
                                    ? '请先绑定至少一个发送账号。'
                                    : replyMode === 'default'
                                      ? '默认模式下，命中关键词后会立刻回复原消息，不走轮换冷却，也不使用关键词时间窗。'
                                      : isKeywordMode
                                        ? keywordBatchDispatchMode === 'window_end'
                                          ? '关键词模式下，同一 Discord 频道会按整轮时间窗累计命中；达到单轮关键词上限后会停止继续识别本轮新增关键词，等本轮倒计时结束后统一发送。批量 @ 消息会直接发送，不引用原消息。'
                                          : '关键词模式下，同一 Discord 频道会按整轮时间窗累计命中；达到单轮关键词上限会立即发送，未达到会在本轮到点时统一发送。批量 @ 消息会直接发送，不引用原消息。'
                                        : senderCount === 1
                                          ? '当前只有 1 个发送账号，轮换模式下会继续使用这个账号发送，轮换间隔会作为发送冷却时间。'
                                          : '轮换模式下会按轮换间隔在可用发送账号之间切换。'}
                                </div>
                                <div>
                                  {replyMode === 'default'
                                    ? '默认模式不显示轮换和关键词窗口设置，行为等同于立即回复。'
                                    : senderCount === 1
                                      ? '关键词模式只在绑定 1 个发送账号时可用；切回其他模式后，已填写的关键词时间和上限会保留，下次切回可继续使用。'
                                      : '当前绑定了多个发送账号，关键词模式不可选；如需使用关键词模式，请先只保留 1 个发送账号。'}
                                </div>
                              </div>
                            </>
                          )
                        })()}
                      </div>
                    )}

                    {/* 消息过滤规则 */}
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Settings className="w-4 h-4" />
                        <span className="text-sm font-medium">消息过滤</span>
                        <Dialog open={showAddWebsiteFilter === website.id} onOpenChange={(open) => {
                          setShowAddWebsiteFilter(open ? website.id : null)
                          setWebsiteNewFilter({ filter_type: 'contains', filter_value: '' })
                          setWebsiteNewFilterImages([])
                          if (websiteNewFilterImageInputRef.current) {
                            websiteNewFilterImageInputRef.current.value = ''
                          }
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
                                <Select
                                  value={websiteNewFilter.filter_type}
                                  onValueChange={value => {
                                    setWebsiteNewFilter(prev => ({
                                      ...prev,
                                      filter_type: value,
                                      filter_value: getDefaultFilterValueForType(value)
                                    }))
                                    if (value !== 'image_filter') {
                                      setWebsiteNewFilterImages([])
                                      if (websiteNewFilterImageInputRef.current) {
                                        websiteNewFilterImageInputRef.current.value = ''
                                      }
                                    }
                                  }}
                                >
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="contains">包含文本</SelectItem>
                                    <SelectItem value="starts_with">开头是</SelectItem>
                                    <SelectItem value="ends_with">结尾是</SelectItem>
                                    <SelectItem value="regex">正则表达式</SelectItem>
                                    <SelectItem value="image">图片消息</SelectItem>
                                    <SelectItem value="user_id">用户ID</SelectItem>
                                    <SelectItem value="role_id">身份组ID</SelectItem>
                                    <SelectItem value="image_filter">图片过滤</SelectItem>
                                    <SelectItem value="numeric_range">数字范围</SelectItem>
                                    <SelectItem value="user_repeat">用户重复发送</SelectItem>
                                    <SelectItem value="keyword_match_limit">关键词命中上限</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                              <div>
                                <Label>过滤值</Label>
                                {websiteNewFilter.filter_type === 'numeric_range' ? (
                                  <div className="space-y-3">
                                    <div className="space-y-1">
                                      <Label className="text-xs text-muted-foreground">匹配关键词</Label>
                                      <Input
                                        value={parseNumericRangeFilterValue(websiteNewFilter.filter_value).keyword}
                                        onChange={e => updateWebsiteNewNumericFilter({ keyword: e.target.value })}
                                        placeholder="例如: size"
                                        className="h-9"
                                      />
                                    </div>
                                    <div className="flex items-center gap-3">
                                      <div className="flex items-center gap-2">
                                        <span className="text-xs text-muted-foreground">小于</span>
                                        <Input
                                          type="number"
                                          value={parseNumericRangeFilterValue(websiteNewFilter.filter_value).min}
                                          onChange={e => updateWebsiteNewNumericFilter({ min: e.target.value })}
                                          className="w-24 h-9"
                                        />
                                        <span className="text-xs text-muted-foreground">不回复</span>
                                      </div>
                                      <div className="flex items-center gap-2">
                                        <span className="text-xs text-muted-foreground">大于</span>
                                        <Input
                                          type="number"
                                          value={parseNumericRangeFilterValue(websiteNewFilter.filter_value).max}
                                          onChange={e => updateWebsiteNewNumericFilter({ max: e.target.value })}
                                          className="w-24 h-9"
                                        />
                                        <span className="text-xs text-muted-foreground">不回复</span>
                                      </div>
                                    </div>
                                  </div>
                                ) : websiteNewFilter.filter_type === 'user_repeat' ? (
                                  <div className="flex items-center gap-2">
                                    <Label className="text-xs text-muted-foreground">重复间隔(秒)</Label>
                                    <Input
                                      type="number"
                                      step="1"
                                      min="1"
                                      value={websiteNewFilter.filter_value}
                                      onChange={e => setWebsiteNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                                      className="h-8 w-24 text-xs"
                                      placeholder="5"
                                    />
                                    <span className="text-xs text-muted-foreground">同一用户相同商品</span>
                                  </div>
                                ) : websiteNewFilter.filter_type === 'image_filter' ? (
                                  <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                      <Label className="text-xs text-muted-foreground">相似度阈值(0-1)</Label>
                                      <Input
                                        type="number"
                                        step="0.01"
                                        value={websiteNewFilter.filter_value}
                                        onChange={e => setWebsiteNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                                        placeholder="0.95"
                                        className="h-8 w-24 text-xs"
                                      />
                                      <span className="text-xs text-muted-foreground">≥该值即过滤</span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                      <input
                                        ref={websiteNewFilterImageInputRef}
                                        type="file"
                                        accept="image/*"
                                        multiple
                                        className="hidden"
                                        onChange={(e) => setWebsiteNewFilterImages(Array.from(e.target.files || []))}
                                      />
                                      <Button
                                        size="sm"
                                        className="h-8 px-3 text-xs"
                                        onClick={() => websiteNewFilterImageInputRef.current?.click()}
                                      >
                                        上传图片
                                      </Button>
                                      <span className="text-xs text-muted-foreground">
                                        已选 {websiteNewFilterImages.length} 张
                                      </span>
                                    </div>
                                    {websiteNewFilterImages.length === 0 && (
                                      <p className="text-xs text-amber-600">
                                        添加前请先上传至少 1 张图片
                                      </p>
                                    )}
                                    <p className="text-xs text-muted-foreground">
                                      仅你在此处上传的图片过滤规则才会生效。
                                    </p>
                                    {websiteNewFilterImages.length > 0 && (
                                      <div className="flex flex-wrap gap-2">
                                        {websiteNewFilterImages.map((file, idx) => (
                                          <div key={`${file.name}-${idx}`} className="flex items-center gap-1 rounded bg-muted px-2 py-1 text-xs">
                                            <span className="max-w-[140px] truncate">{file.name}</span>
                                            <Button
                                              variant="ghost"
                                              size="sm"
                                              className="h-4 w-4 p-0"
                                              onClick={() => setWebsiteNewFilterImages(prev => prev.filter((_, i) => i !== idx))}
                                            >
                                              <X className="w-3 h-3" />
                                            </Button>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                ) : websiteNewFilter.filter_type === 'image' ? (
                                  <div className="text-xs text-muted-foreground">图片消息无需填写过滤值</div>
                                ) : (
                                  <Input
                                    value={websiteNewFilter.filter_value}
                                    onChange={e => setWebsiteNewFilter(prev => ({ ...prev, filter_value: e.target.value }))}
                                    placeholder={getFilterValuePlaceholder(websiteNewFilter.filter_type)}
                                  />
                                )}
                              </div>
                            </div>
                            <DialogFooter>
                              <Button variant="outline" onClick={() => setShowAddWebsiteFilter(null)}>取消</Button>
                              <Button
                                onClick={() => handleAddWebsiteFilter(website.id)}
                                disabled={websiteNewFilter.filter_type === 'image_filter' && websiteNewFilterImages.length === 0}
                              >
                                添加
                              </Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(websiteFilters[website.id] || []).map((filter: any, index: number) => (
                          <div key={filter.id || index} className="flex items-center gap-1 bg-muted rounded px-2 py-1">
                            <span className="text-xs truncate max-w-56" title={formatMessageFilterLabel(filter)}>
                              {formatMessageFilterLabel(filter)}
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-4 w-4 p-0"
                              onClick={() => setEditingWebsiteFilter({ websiteId: website.id, filter: { ...filter } })}
                            >
                              <Edit className="w-3 h-3" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-4 w-4 p-0"
                              onClick={() => handleRemoveWebsiteFilter(website.id, filter.id)}
                            >
                              <X className="w-3 h-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    </div>

                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

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
                    <Select
                      value={editingFilter.filter_type}
                      onValueChange={value => setEditingFilter((prev: any) => ({
                        ...prev,
                        filter_type: value,
                        filter_value: getDefaultFilterValueForType(value)
                      }))}
                    >
                      <SelectTrigger>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="contains">包含文本</SelectItem>
                      <SelectItem value="starts_with">开头是</SelectItem>
                      <SelectItem value="ends_with">结尾是</SelectItem>
                      <SelectItem value="regex">正则表达式</SelectItem>
                      <SelectItem value="image">图片消息</SelectItem>
                      <SelectItem value="user_id">用户ID</SelectItem>
                      <SelectItem value="role_id">身份组ID</SelectItem>
                      <SelectItem value="image_filter">图片过滤</SelectItem>
                      <SelectItem value="numeric_range">数字范围</SelectItem>
                      <SelectItem value="user_repeat">用户重复发送</SelectItem>
                      <SelectItem value="keyword_match_limit">关键词命中上限</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>过滤值</Label>
                  {editingFilter.filter_type === 'numeric_range' ? (
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">匹配关键词</Label>
                        <Input
                          value={parseNumericRangeFilterValue(editingFilter.filter_value).keyword}
                          onChange={e => updateEditingNumericFilter({ keyword: e.target.value })}
                          placeholder="例如: size"
                          className="h-9"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">小于</span>
                          <Input
                            type="number"
                            value={parseNumericRangeFilterValue(editingFilter.filter_value).min}
                            onChange={e => updateEditingNumericFilter({ min: e.target.value })}
                            className="w-24 h-9"
                          />
                          <span className="text-xs text-muted-foreground">不回复</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">大于</span>
                          <Input
                            type="number"
                            value={parseNumericRangeFilterValue(editingFilter.filter_value).max}
                            onChange={e => updateEditingNumericFilter({ max: e.target.value })}
                            className="w-24 h-9"
                          />
                          <span className="text-xs text-muted-foreground">不回复</span>
                        </div>
                      </div>
                    </div>
                  ) : editingFilter.filter_type === 'user_repeat' ? (
                    <div className="flex items-center gap-2">
                      <Label className="text-xs text-muted-foreground">重复间隔(秒)</Label>
                      <Input
                        type="number"
                        step="1"
                        min="1"
                        value={editingFilter.filter_value}
                        onChange={e => setEditingFilter((prev: any) => ({ ...prev, filter_value: e.target.value }))}
                        className="h-8 w-24 text-xs"
                        placeholder="5"
                      />
                      <span className="text-xs text-muted-foreground">同一用户相同商品</span>
                    </div>
                  ) : editingFilter.filter_type === 'image_filter' ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <Label className="text-xs text-muted-foreground">相似度阈值(0-1)</Label>
                        <Input
                          type="number"
                          step="0.01"
                          value={editingFilter.filter_value}
                          onChange={e => setEditingFilter((prev: any) => ({ ...prev, filter_value: e.target.value }))}
                          placeholder="0.95"
                          className="h-8 w-24 text-xs"
                        />
                        <span className="text-xs text-muted-foreground">≥该值即过滤</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          ref={editingFilterImageInputRef}
                          type="file"
                          accept="image/*"
                          multiple
                          className="hidden"
                          onChange={(e) => handleMessageFilterFileSelect(e.target.files)}
                        />
                        <Button
                          size="sm"
                          className="h-8 px-3 text-xs"
                          onClick={() => editingFilterImageInputRef.current?.click()}
                          disabled={editingFilterImagesUploading}
                        >
                          {editingFilterImagesUploading ? '上传中...' : '上传图片'}
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {editingFilterImagesLoading ? (
                          <span className="text-xs text-muted-foreground">加载中...</span>
                        ) : editingFilterImages.length === 0 ? (
                          <span className="text-xs text-muted-foreground">暂无图片</span>
                        ) : (
                          editingFilterImages.map((img: any) => (
                            <div key={img.id} className="group relative h-12 w-12">
                              <img
                                src={img.url}
                                alt={`filter-${img.id}`}
                                className="h-12 w-12 rounded border object-cover"
                                loading="lazy"
                              />
                              <Button
                                variant="destructive"
                                size="icon"
                                className="absolute -top-2 -right-2 h-5 w-5 opacity-0 transition-opacity group-hover:opacity-100"
                                onClick={() => handleDeleteMessageFilterImage(editingFilter.id, img.id)}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  ) : editingFilter.filter_type === 'image' ? (
                    <div className="text-xs text-muted-foreground">图片消息无需填写过滤值</div>
                  ) : (
                    <Input
                      value={editingFilter.filter_value}
                      onChange={e => setEditingFilter((prev: any) => ({ ...prev, filter_value: e.target.value }))}
                      placeholder={getFilterValuePlaceholder(editingFilter.filter_type)}
                    />
                  )}
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditingFilter(null)}>取消</Button>
                <Button onClick={handleUpdateMessageFilter}>保存修改</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}

        {/* 编辑网站过滤对话框 */}
        {editingWebsiteFilter && (
          <Dialog open={!!editingWebsiteFilter} onOpenChange={() => setEditingWebsiteFilter(null)}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>编辑网站过滤规则</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label>过滤类型</Label>
                  <Select
                    value={editingWebsiteFilter.filter.filter_type}
                    onValueChange={value => {
                      setEditingWebsiteFilter((prev: any) => ({
                        ...prev,
                        filter: {
                          ...prev.filter,
                          filter_type: value,
                          filter_value: getDefaultFilterValueForType(value)
                        }
                      }))
                      if (value !== 'image_filter') {
                        setEditingWebsiteFilterImages([])
                        setEditingWebsiteFilterNewFiles([])
                        if (websiteEditingFilterImageInputRef.current) {
                          websiteEditingFilterImageInputRef.current.value = ''
                        }
                      }
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="contains">包含文本</SelectItem>
                      <SelectItem value="starts_with">开头是</SelectItem>
                      <SelectItem value="ends_with">结尾是</SelectItem>
                      <SelectItem value="regex">正则表达式</SelectItem>
                      <SelectItem value="image">图片消息</SelectItem>
                      <SelectItem value="user_id">用户ID</SelectItem>
                      <SelectItem value="role_id">身份组ID</SelectItem>
                      <SelectItem value="image_filter">图片过滤</SelectItem>
                      <SelectItem value="numeric_range">数字范围</SelectItem>
                      <SelectItem value="user_repeat">用户重复发送</SelectItem>
                      <SelectItem value="keyword_match_limit">关键词命中上限</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>过滤值</Label>
                  {editingWebsiteFilter.filter.filter_type === 'numeric_range' ? (
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">匹配关键词</Label>
                        <Input
                          value={parseNumericRangeFilterValue(editingWebsiteFilter.filter.filter_value).keyword}
                          onChange={e => updateWebsiteEditingNumericFilter({ keyword: e.target.value })}
                          placeholder="例如: size"
                          className="h-9"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">小于</span>
                          <Input
                            type="number"
                            value={parseNumericRangeFilterValue(editingWebsiteFilter.filter.filter_value).min}
                            onChange={e => updateWebsiteEditingNumericFilter({ min: e.target.value })}
                            className="w-24 h-9"
                          />
                          <span className="text-xs text-muted-foreground">不回复</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">大于</span>
                          <Input
                            type="number"
                            value={parseNumericRangeFilterValue(editingWebsiteFilter.filter.filter_value).max}
                            onChange={e => updateWebsiteEditingNumericFilter({ max: e.target.value })}
                            className="w-24 h-9"
                          />
                          <span className="text-xs text-muted-foreground">不回复</span>
                        </div>
                      </div>
                    </div>
                  ) : editingWebsiteFilter.filter.filter_type === 'user_repeat' ? (
                    <div className="flex items-center gap-2">
                      <Label className="text-xs text-muted-foreground">重复间隔(秒)</Label>
                      <Input
                        type="number"
                        step="1"
                        min="1"
                        value={editingWebsiteFilter.filter.filter_value}
                        onChange={e => setEditingWebsiteFilter((prev: any) => ({
                          ...prev,
                          filter: { ...prev.filter, filter_value: e.target.value }
                        }))}
                        className="h-8 w-24 text-xs"
                        placeholder="5"
                      />
                      <span className="text-xs text-muted-foreground">同一用户相同商品</span>
                    </div>
                  ) : editingWebsiteFilter.filter.filter_type === 'image_filter' ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <Label className="text-xs text-muted-foreground">相似度阈值(0-1)</Label>
                        <Input
                          type="number"
                          step="0.01"
                          value={editingWebsiteFilter.filter.filter_value}
                          onChange={e => setEditingWebsiteFilter((prev: any) => ({
                            ...prev,
                            filter: { ...prev.filter, filter_value: e.target.value }
                          }))}
                          placeholder="0.95"
                          className="h-8 w-24 text-xs"
                        />
                        <span className="text-xs text-muted-foreground">≥该值即过滤</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          ref={websiteEditingFilterImageInputRef}
                          type="file"
                          accept="image/*"
                          multiple
                          className="hidden"
                          onChange={(e) => handleWebsiteFilterFileSelect(e.target.files)}
                        />
                        <Button
                          size="sm"
                          className="h-8 px-3 text-xs"
                          onClick={() => websiteEditingFilterImageInputRef.current?.click()}
                          disabled={editingWebsiteFilterImagesUploading}
                        >
                          {editingWebsiteFilterImagesUploading ? '上传中...' : '上传图片'}
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {editingWebsiteFilterImagesLoading ? (
                          <span className="text-xs text-muted-foreground">加载中...</span>
                        ) : editingWebsiteFilterImages.length === 0 ? (
                          <span className="text-xs text-muted-foreground">暂无图片</span>
                        ) : (
                          editingWebsiteFilterImages.map((img: any) => (
                            <div key={img.id} className="group relative h-12 w-12">
                              <img
                                src={img.url}
                                alt={`website-filter-${img.id}`}
                                className="h-12 w-12 rounded border object-cover"
                                loading="lazy"
                              />
                              <Button
                                variant="destructive"
                                size="icon"
                                className="absolute -top-2 -right-2 h-5 w-5 opacity-0 transition-opacity group-hover:opacity-100"
                                onClick={() => handleDeleteWebsiteFilterImage(editingWebsiteFilter.websiteId, editingWebsiteFilter.filter.id, img.id)}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  ) : editingWebsiteFilter.filter.filter_type === 'image' ? (
                    <div className="text-xs text-muted-foreground">图片消息无需填写过滤值</div>
                  ) : (
                    <Input
                      value={editingWebsiteFilter.filter.filter_value}
                      onChange={e => setEditingWebsiteFilter((prev: any) => ({
                        ...prev,
                        filter: { ...prev.filter, filter_value: e.target.value }
                      }))}
                      placeholder={getFilterValuePlaceholder(editingWebsiteFilter.filter.filter_type)}
                    />
                  )}
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditingWebsiteFilter(null)}>取消</Button>
                <Button onClick={handleUpdateWebsiteFilter}>保存</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}


        {/* 移除频道确认对话框 */}
        <Dialog open={!!channelToRemove} onOpenChange={(open) => !open && setChannelToRemove(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认移除频道?</DialogTitle>
              <DialogDescription>
                确定要解除频道 {channelToRemove?.chanId} 的绑定吗？
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setChannelToRemove(null)}>取消</Button>
              <Button variant="destructive" onClick={executeRemoveChannel}>确认移除</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

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
