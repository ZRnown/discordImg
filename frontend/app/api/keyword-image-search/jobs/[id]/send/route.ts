import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(`${BACKEND_URL}/api/keyword-image-search/jobs/${id}/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookieHeader,
      },
      body: JSON.stringify(body),
    })

    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status })
    }
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('POST /api/keyword-image-search/jobs/[id]/send failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
