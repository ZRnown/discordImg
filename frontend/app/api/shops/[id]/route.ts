import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:5001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params;
    const response = await fetch(`${BACKEND_URL}/api/shops/${resolvedParams.id}`, {
      method: 'DELETE'
    })

    if (response.ok) {
      const data = await response.json()
      return NextResponse.json(data)
    } else {
      return NextResponse.json({ error: 'Failed to delete shop' }, { status: response.status })
    }
  } catch (error) {
    return NextResponse.json({ error: 'Backend connection failed' }, { status: 500 })
  }
}
