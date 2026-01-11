import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params;
    const response = await fetch(`${BACKEND_URL}/api/accounts/${resolvedParams.id}`, {
      method: 'DELETE'
    })

    if (response.ok) {
      return NextResponse.json({ success: true })
    } else {
      return NextResponse.json({ error: 'Failed to delete account' }, { status: response.status })
    }
  } catch (error) {
    return NextResponse.json({ error: 'Backend connection failed' }, { status: 500 })
  }
}
