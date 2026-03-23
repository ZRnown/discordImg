import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(request: NextRequest) {
  try {
    const cookieHeader = request.headers.get('cookie') || '';
    const response = await fetch(`${BACKEND_URL}/api/websites`, {
      headers: { 'Cookie': cookieHeader },
      cache: 'no-store'
    })

    if (!response.ok) {
      // 404 handling specifically
      if (response.status === 404) {
          return NextResponse.json(
            { websites: [] },
            { headers: { 'Cache-Control': 'no-store' } }
          );
      }
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(errorData, {
        status: response.status,
        headers: { 'Cache-Control': 'no-store' },
      })
    }

    const data = await response.json()
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error: any) {
    console.error('GET /api/websites failed:', error)
    return NextResponse.json(
      { error: error.message },
      {
        status: 500,
        headers: { 'Cache-Control': 'no-store' },
      }
    )
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/websites`, {
      method: 'POST',
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
    console.error('POST /api/websites failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
