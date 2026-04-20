import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(request: NextRequest) {
  try {
    const cookieHeader = request.headers.get('cookie') || ''
    const search = request.nextUrl.searchParams.toString()
    const response = await fetch(
      `${BACKEND_URL}/api/keyword-review-items${search ? `?${search}` : ''}`,
      {
        headers: { Cookie: cookieHeader },
      },
    )

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      return NextResponse.json(errorData, { status: response.status })
    }

    return NextResponse.json(await response.json())
  } catch (error: any) {
    console.error('GET /api/keyword-review-items failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
