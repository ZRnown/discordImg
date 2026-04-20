import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(`${BACKEND_URL}/api/message-filters/${id}/blocked-users`, {
      headers: { Cookie: cookieHeader }
    })

    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('GET /api/message-filters/[id]/blocked-users failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
