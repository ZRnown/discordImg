import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params
    const historyId = resolvedParams.id

    const response = await fetch(`${BACKEND_URL}/api/search_history/${historyId}/query-image`)

    if (!response.ok) {
      return NextResponse.json({ error: 'Image not found' }, { status: response.status })
    }

    const imageBuffer = await response.arrayBuffer()
    const contentType = response.headers.get('content-type') || 'image/jpeg'

    return new NextResponse(imageBuffer, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=3600',
      },
    })
  } catch (error: any) {
    console.error('GET /api/search_history/[id]/query-image failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
