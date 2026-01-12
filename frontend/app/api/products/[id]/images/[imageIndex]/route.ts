import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; imageIndex: string }> }
) {
  try {
    const resolvedParams = await params
    const { id, imageIndex } = resolvedParams
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/products/${id}/images/${imageIndex}`, {
      method: 'DELETE',
      headers: { 'Cookie': cookieHeader }
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Delete failed' }));
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('DELETE /api/products/[id]/images/[imageIndex] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
