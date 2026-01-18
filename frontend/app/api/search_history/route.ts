import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const limit = url.searchParams.get('limit') || '50';
    // 【修复】获取 offset 参数
    const offset = url.searchParams.get('offset') || '0';

    // 【修复】将 offset 参数拼接到后端请求中
    const response = await fetch(`${BACKEND_URL}/api/search_history?limit=${limit}&offset=${offset}`);
    if (!response.ok) {
      const errorData = await response.json();
      return NextResponse.json(errorData, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('GET /api/search_history failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/search_history`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      const errorData = await response.json();
      return NextResponse.json(errorData, { status: response.status });
    }

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('DELETE /api/search_history failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
