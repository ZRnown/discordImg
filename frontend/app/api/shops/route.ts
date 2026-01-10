import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:5001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/shops`)
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
    const response = await fetch(`${BACKEND_URL}/api/shops`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
