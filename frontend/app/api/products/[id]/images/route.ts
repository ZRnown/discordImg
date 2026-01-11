import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params
    const id = resolvedParams.id
    const formData = await request.formData()
    const cookieHeader = request.headers.get('cookie') || '';

    // FormData上传时，不要设置Content-Type，让浏览器自动处理multipart/form-data
    // 只传递Cookie头
    const response = await fetch(`${BACKEND_URL}/api/products/${id}/images`, {
      method: 'POST',
      body: formData,
      headers: cookieHeader ? {
        'Cookie': cookieHeader
      } : undefined
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Upload failed' }));
      return NextResponse.json(errorData, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
}
