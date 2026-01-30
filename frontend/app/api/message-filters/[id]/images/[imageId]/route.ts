import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; imageId: string }> }
) {
  try {
    const { id, imageId } = await params
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(`${BACKEND_URL}/api/message-filters/${id}/images/${imageId}`, {
      method: 'DELETE',
      headers: { 'Cookie': cookieHeader }
    })

    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('DELETE /api/message-filters/[id]/images/[imageId] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
