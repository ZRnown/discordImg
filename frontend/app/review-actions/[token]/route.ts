import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'

export const dynamic = 'force-dynamic'

const proxyReviewAction = async (
  request: NextRequest,
  token: string,
  method: 'GET' | 'POST',
) => {
  const headers: HeadersInit = {
    Accept: 'text/html',
  }
  const cookieHeader = request.headers.get('cookie') || ''
  if (cookieHeader) {
    headers.Cookie = cookieHeader
  }

  let body: BodyInit | undefined
  if (method === 'POST') {
    const contentType = request.headers.get('content-type') || 'application/x-www-form-urlencoded'
    headers['content-type'] = contentType
    body = await request.text()
  }

  const response = await fetch(`${BACKEND_URL}/review-actions/${encodeURIComponent(token)}`, {
    method,
    headers,
    body,
    cache: 'no-store',
  })
  const html = await response.text()

  return new NextResponse(html, {
    status: response.status,
    headers: {
      'content-type': response.headers.get('content-type') || 'text/html; charset=utf-8',
      'cache-control': 'no-store',
    },
  })
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  try {
    const { token } = await params
    return await proxyReviewAction(request, token, 'GET')
  } catch (error: any) {
    console.error('GET /review-actions/[token] failed:', error)
    return new NextResponse('审核页面暂时无法打开，请稍后重试。', {
      status: 502,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    })
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  try {
    const { token } = await params
    return await proxyReviewAction(request, token, 'POST')
  } catch (error: any) {
    console.error('POST /review-actions/[token] failed:', error)
    return new NextResponse('审核提交失败，请稍后重试。', {
      status: 502,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    })
  }
}
