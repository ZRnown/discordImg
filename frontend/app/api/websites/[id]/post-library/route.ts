import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/post-library`, {
      headers: { Cookie: cookieHeader },
      cache: 'no-store',
    })
    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('GET /api/websites/[id]/post-library failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const cookieHeader = request.headers.get('cookie') || ''
    const formData = await request.formData()
    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/post-library`, {
      method: 'POST',
      headers: { Cookie: cookieHeader },
      body: formData,
    })
    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('POST /api/websites/[id]/post-library failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
