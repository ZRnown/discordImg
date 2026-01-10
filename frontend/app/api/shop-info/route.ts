import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const shopId = searchParams.get('shopId')

    if (!shopId) {
      return NextResponse.json({ error: '缺少shopId参数' }, { status: 400 })
    }

    // 代理请求到后端，使用127.0.0.1避免代理问题
    const backendUrl = `http://127.0.0.1:5001/api/shop-info?shopId=${shopId}`

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      return NextResponse.json({ error: '后端请求失败' }, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)

  } catch (error) {
    console.error('Shop info API error:', error)
    return NextResponse.json({ error: '获取店铺信息失败' }, { status: 500 })
  }
}
