import { NextRequest, NextResponse } from 'next/server'

const DEFAULT_BARK_SERVER = 'https://api.day.app'

const normalizeServerUrl = (raw: unknown) => {
  const text = String(raw || '').trim()
  if (!text) return DEFAULT_BARK_SERVER
  const withProtocol = /^https?:\/\//i.test(text) ? text : `https://${text}`
  return withProtocol.replace(/\/+$/, '')
}

const isLikelyDeviceToken = (value: string) => /^[a-f0-9]{64}$/i.test(value)

const buildPushUrl = (serverUrl: string, deviceKey: string, title: string, content: string) => {
  const pushPath = [
    encodeURIComponent(deviceKey),
    encodeURIComponent(title),
    encodeURIComponent(content),
  ].join('/')
  return `${serverUrl}/${pushPath}?group=${encodeURIComponent('Discord营销系统')}&isArchive=1&sound=gotosleep`
}

const fetchWithTimeout = async (
  url: string,
  init: RequestInit = {},
  timeoutMs = 8000
) => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, {
      ...init,
      cache: 'no-store',
      signal: controller.signal
    })
  } finally {
    clearTimeout(timer)
  }
}

const safeReadText = async (response: Response) => {
  try {
    return await response.text()
  } catch {
    return ''
  }
}

const sendBarkPush = async (
  serverUrl: string,
  deviceKey: string,
  title: string,
  content: string
) => {
  const pushUrl = buildPushUrl(serverUrl, deviceKey, title, content)
  let lastError: unknown = null

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetchWithTimeout(pushUrl, { method: 'GET' }, 8000)
      const text = await safeReadText(response)
      if (response.ok || attempt === 1 || response.status < 500) {
        return { response, text, attempt }
      }
    } catch (error) {
      lastError = error
      if (attempt === 1) {
        throw error
      }
    }
  }

  throw lastError || new Error('unknown bark push error')
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}))
    const barkServerUrl = normalizeServerUrl(body?.bark_server_url)
    const rawBarkKey = String(body?.bark_device_key || '').trim()

    if (!rawBarkKey) {
      return NextResponse.json({ error: '请先填写 Bark 设备 Key' }, { status: 400 })
    }

    const nowText = new Date().toLocaleString('zh-CN', { hour12: false })
    const peerContent = '@jerry_selfbot_01 这双AJ4有39码吗？'
    const title = peerContent
    const content = [
      '账号: jerry_selfbot_01',
      '类型: 被@提及',
      '发送者: mike_buyer',
      '位置: PandaBuy Group / #sneaker-qa',
      `内容: ${peerContent}`,
      `时间: ${nowText}`
    ].join('\n')

    let finalDeviceKey = rawBarkKey
    let { response: barkResp, text: barkText } = await sendBarkPush(
      barkServerUrl,
      finalDeviceKey,
      title,
      content
    )

    // 兼容误填 DeviceToken 的场景：自动注册换取 DeviceKey 再重试
    if (
      !barkResp.ok &&
      isLikelyDeviceToken(rawBarkKey) &&
      barkResp.status === 400 &&
      barkText.includes('failed to get device token')
    ) {
      const registerResp = await fetchWithTimeout(
        `${barkServerUrl}/register`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json; charset=utf-8' },
          body: JSON.stringify({ device_token: rawBarkKey })
        },
        8000
      )
      const registerData = await registerResp.json().catch(() => null)
      const newDeviceKey = String(
        registerData?.data?.device_key || registerData?.data?.key || ''
      ).trim()

      if (registerResp.ok && newDeviceKey) {
        finalDeviceKey = newDeviceKey
        const retry = await sendBarkPush(barkServerUrl, finalDeviceKey, title, content)
        barkResp = retry.response
        barkText = retry.text
      }
    }

    if (!barkResp.ok) {
      return NextResponse.json(
        {
          error: `Bark 推送失败（HTTP ${barkResp.status}）`,
          details: barkText.slice(0, 500),
          stage: 'push',
        },
        { status: 502 }
      )
    }

    return NextResponse.json({
      success: true,
      message: '测试推送已发送，请检查 iPhone 的 Bark 通知',
      server_url: barkServerUrl,
      device_key_updated: finalDeviceKey !== rawBarkKey ? finalDeviceKey : undefined,
      hint:
        finalDeviceKey !== rawBarkKey
          ? '检测到你填写的是 DeviceToken，已自动转换为 DeviceKey。请保存新的 DeviceKey。'
          : undefined,
    })
  } catch (error: any) {
    const timeoutLike =
      error?.name === 'AbortError' ||
      String(error?.message || '').toLowerCase().includes('timeout')

    return NextResponse.json(
      {
        error: timeoutLike ? 'Bark 请求超时，请稍后重试' : (error?.message || '发送测试推送失败'),
        stage: 'request',
      },
      { status: 502 }
    )
  }
}
