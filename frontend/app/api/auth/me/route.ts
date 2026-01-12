import { NextRequest, NextResponse } from 'next/server';

// 强制使用内网回环地址，速度最快且最稳定
const BACKEND_URL = 'http://127.0.0.1:5001';

export async function GET(request: NextRequest) {
  try {
    // 获取浏览器传来的所有 Cookie
    const cookies = request.headers.get('cookie') || '';

    // 调用后端验证 Session 有效性
    const backendResponse = await fetch(`${BACKEND_URL}/api/auth/me`, {
      headers: {
        'Cookie': cookies // 关键：转发 Cookie 给后端
      }
    });

    if (backendResponse.ok) {
      const data = await backendResponse.json();
      return NextResponse.json(data);
    } else {
      // 如果后端验证失败 (401)，前端也要清除 user_session
      const errorData = await backendResponse.json().catch(() => ({ error: 'Not authenticated' }));
      const response = NextResponse.json(errorData, { status: backendResponse.status });

      if (backendResponse.status === 401) {
      response.cookies.set('user_session', '', { maxAge: 0 });
      }
      return response;
    }
  } catch (error: any) {
    console.error('Auth me API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
