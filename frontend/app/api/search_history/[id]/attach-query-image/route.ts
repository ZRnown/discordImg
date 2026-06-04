import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: historyId } = await params
    const cookie = request.headers.get('cookie')
    const body = await request.text()

    const response = await fetch(`${BACKEND_URL}/api/search_history/${historyId}/attach-query-image`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(cookie ? { cookie } : {}),
      },
      body: body || '{}',
    })

    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('POST /api/search_history/[id]/attach-query-image failed:', error)
    return NextResponse.json({ error: error.message || 'Backend connection failed' }, { status: 500 })
  }
}
