import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function GET(request: NextRequest) {
  try {
    // 修复：手动获取并转发 Cookie
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/announcements`, {
      headers: {
        'Cookie': cookieHeader
      }
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('GET /api/announcements failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/announcements`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookieHeader
      },
      body: JSON.stringify(body)
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('POST /api/announcements failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
