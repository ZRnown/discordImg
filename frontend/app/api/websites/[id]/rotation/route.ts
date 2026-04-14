import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/rotation`, {
      headers: {
        'Cookie': cookieHeader
      },
      cache: 'no-store'
    })

    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status })
    }

    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error: any) {
    console.error('GET /api/websites/[id]/rotation failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/rotation`, {
      method: 'PUT',
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
    console.error('PUT /api/websites/[id]/rotation failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
