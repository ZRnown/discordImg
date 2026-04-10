import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; postId: string; filename: string }> }
) {
  try {
    const { id, postId, filename } = await params
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(
      `${BACKEND_URL}/api/websites/${id}/post-library/${postId}/images/${encodeURIComponent(filename)}`,
      {
        headers: { Cookie: cookieHeader },
        cache: 'no-store',
      }
    )

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      return NextResponse.json(data, { status: response.status })
    }

    const contentType = response.headers.get('content-type') || 'application/octet-stream'
    const arrayBuffer = await response.arrayBuffer()
    return new NextResponse(arrayBuffer, {
      status: response.status,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'no-store',
      },
    })
  } catch (error: any) {
    console.error('GET /api/websites/[id]/post-library/[postId]/images/[filename] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
