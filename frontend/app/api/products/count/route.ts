import { NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/products/count`)

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to fetch count' }))
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('GET /api/products/count failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
