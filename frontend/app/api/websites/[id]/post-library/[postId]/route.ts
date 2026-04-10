import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; postId: string }> }
) {
  try {
    const { id, postId } = await params
    const cookieHeader = request.headers.get('cookie') || ''
    const formData = await request.formData()
    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/post-library/${postId}`, {
      method: 'PUT',
      headers: { Cookie: cookieHeader },
      body: formData,
    })
    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('PUT /api/websites/[id]/post-library/[postId] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; postId: string }> }
) {
  try {
    const { id, postId } = await params
    const cookieHeader = request.headers.get('cookie') || ''
    const response = await fetch(`${BACKEND_URL}/api/websites/${id}/post-library/${postId}`, {
      method: 'DELETE',
      headers: { Cookie: cookieHeader },
    })
    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('DELETE /api/websites/[id]/post-library/[postId] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
