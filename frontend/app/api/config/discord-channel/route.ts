import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:5001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/config/discord-channel`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      throw new Error(`Backend API error: ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Discord channel config API error:', error)
    return NextResponse.json({ error: 'Failed to fetch discord channel config' }, { status: 500 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()

    const response = await fetch(`${BACKEND_URL}/api/config/discord-channel`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      throw new Error(`Backend API error: ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Discord channel config API error:', error)
    return NextResponse.json({ error: 'Failed to update discord channel config' }, { status: 500 })
  }
}
