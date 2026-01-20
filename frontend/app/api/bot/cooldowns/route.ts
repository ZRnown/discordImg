import { NextRequest, NextResponse } from 'next/server'
import { fetchFromBackend } from '../../_utils/backend'

export async function GET(request: NextRequest) {
  try {
    const cookieHeader = request.headers.get('cookie') || ''

    const { response, rawText } = await fetchFromBackend('/api/bot/cooldowns', {
      headers: { 'Cookie': cookieHeader }
    }, request.headers.get('host'))
    let data: any = null
    try {
      data = rawText ? JSON.parse(rawText) : null
    } catch {
      data = { error: rawText || 'Backend error' }
    }

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status })
    }

    return NextResponse.json(data)
  } catch (error: any) {
    console.error('GET /api/bot/cooldowns failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
