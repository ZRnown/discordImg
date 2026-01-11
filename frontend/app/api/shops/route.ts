import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function GET(request: NextRequest) {
  try {
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = {};
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    const response = await fetch(`${BACKEND_URL}/api/shops`, {
      headers: headers
    })

    if (response.ok) {
      const data = await response.json()
      return NextResponse.json(data)
    } else {
      return NextResponse.json({ error: 'Failed to fetch shops' }, { status: response.status })
    }
  } catch (error) {
    return NextResponse.json({ error: 'Backend connection failed' }, { status: 500 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    const response = await fetch(`${BACKEND_URL}/api/shops`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body)
    })

    if (response.ok) {
      const data = await response.json()
      return NextResponse.json(data)
    } else {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }
  } catch (error) {
    return NextResponse.json({ error: 'Backend connection failed' }, { status: 500 })
  }
}
