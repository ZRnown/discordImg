import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}))
    const cookies = request.headers.get('cookie') || ''

    const backendResponse = await fetch(`${BACKEND_URL}/api/user/bark-test`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: cookies
      },
      body: JSON.stringify(body)
    })

    const data = await backendResponse.json().catch(() => ({ error: 'Bark test failed' }))
    if (backendResponse.ok) {
      return NextResponse.json(data)
    }
    return NextResponse.json(data, { status: backendResponse.status })
  } catch (error: any) {
    console.error('Bark test API error:', error)
    return NextResponse.json({ error: error.message || 'Bark test failed' }, { status: 500 })
  }
}

