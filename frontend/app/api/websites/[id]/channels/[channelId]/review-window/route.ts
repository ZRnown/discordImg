import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; channelId: string }> }
) {
  try {
    const { id, channelId } = await params
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/channels/${channelId}/review-window`, {
      method: 'PUT',
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
    console.error('PUT /api/websites/[id]/channels/[channelId]/review-window failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
