import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(request: NextRequest) {
  try {
    const cookieHeader = request.headers.get('cookie') || ''
    const queryString = request.nextUrl.searchParams.toString()
    const response = await fetch(
      `${BACKEND_URL}/api/keyword-image-search/jobs${queryString ? `?${queryString}` : ''}`,
      {
        headers: { Cookie: cookieHeader },
        cache: 'no-store',
      },
    )

    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status })
    }
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error: any) {
    console.error('GET /api/keyword-image-search/jobs failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
