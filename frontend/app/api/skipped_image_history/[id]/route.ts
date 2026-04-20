import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function DELETE(
  _request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await context.params
    const response = await fetch(`${BACKEND_URL}/api/skipped_image_history/${id}`, {
      method: 'DELETE'
    })

    if (!response.ok) {
      const errorData = await response.json()
      return NextResponse.json(errorData, { status: response.status })
    }

    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('DELETE /api/skipped_image_history/[id] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
