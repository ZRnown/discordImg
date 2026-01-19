import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(request: NextRequest) {
  try {
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(`${BACKEND_URL}/api/system/stats`, {
      headers: {
        'Cookie': cookieHeader
      }
    })
    if (!response.ok) {
      const errorData = await response.json()
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('GET /api/system/stats failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
