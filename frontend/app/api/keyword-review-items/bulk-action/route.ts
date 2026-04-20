import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(`${BACKEND_URL}/api/keyword-review-items/bulk-action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: cookieHeader,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      return NextResponse.json(errorData, { status: response.status })
    }

    return NextResponse.json(await response.json())
  } catch (error: any) {
    console.error('POST /api/keyword-review-items/bulk-action failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
