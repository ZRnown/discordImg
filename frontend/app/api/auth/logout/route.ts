import { NextRequest, NextResponse } from 'next/server';

// 强制使用内网回环地址，速度最快且最稳定
const BACKEND_URL = 'http://127.0.0.1:5001';

export async function POST(request: NextRequest) {
  try {
    // 获取前端的session cookie并传递给后端
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = {};
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    // 调用后端登出API
    const backendResponse = await fetch(`${BACKEND_URL}/api/auth/logout`, {
      method: 'POST',
      headers: headers
    });

    // 清除前端session cookie
    const response = NextResponse.json({ message: '已登出' });
    response.cookies.set('user_session', '', {
      maxAge: 0
    });

    return response;
  } catch (error: any) {
    console.error('Logout API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
