import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export async function DELETE(request: NextRequest) {
  try {
    const url = new URL(request.url)
    const query = url.searchParams.toString()
    const cookieHeader = request.headers.get('cookie') || ''

    const response = await fetch(`${BACKEND_URL}/api/products/batch-delete-all${query ? `?${query}` : ''}`, {
      method: 'DELETE',
      headers: { 'Cookie': cookieHeader }
    })

    const data = await response.json().catch(() => ({}))
    return NextResponse.json(data, { status: response.status })
  } catch (error: any) {
    console.error('DELETE /api/products/batch-delete-all failed:', error)
    return NextResponse.json({ error: error.message || 'Backend connection failed' }, { status: 500 })
  }
}
