import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; discordUserId: string }> }
) {
  try {
    const { id, discordUserId } = await params
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(
      `${BACKEND_URL}/api/message-filters/${id}/blocked-users/${encodeURIComponent(discordUserId)}`,
      {
        method: 'DELETE',
        headers: { Cookie: cookieHeader }
      }
    )

    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('DELETE /api/message-filters/[id]/blocked-users/[discordUserId] failed:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
