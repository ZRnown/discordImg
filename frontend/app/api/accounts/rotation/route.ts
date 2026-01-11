import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/accounts/rotation`)
    if (response.ok) {
      const data = await response.json()
      return NextResponse.json(data)
    } else {
      return NextResponse.json({ enabled: false, rotationInterval: 10 })
    }
  } catch (error) {
    return NextResponse.json({ enabled: false, rotationInterval: 10 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const response = await fetch(`${BACKEND_URL}/api/accounts/rotation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })

    if (response.ok) {
      const data = await response.json()
      return NextResponse.json(data)
    } else {
      return NextResponse.json({ error: 'Failed to update rotation config' }, { status: response.status })
    }
  } catch (error) {
    return NextResponse.json({ error: 'Backend connection failed' }, { status: 500 })
  }
}
