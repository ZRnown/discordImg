import { NextRequest, NextResponse } from 'next/server';
import { fetchFromBackend } from '../../_utils/backend';

export async function GET(request: NextRequest) {
  try {
    // 获取浏览器传来的所有 Cookie
    const cookies = request.headers.get('cookie') || '';

    // 调用后端验证 Session 有效性
    const { response: backendResponse, rawText } = await fetchFromBackend('/api/auth/me', {
      headers: {
        'Cookie': cookies // 关键：转发 Cookie 给后端
      }
    }, request.headers.get('host'), 3000);
    let data: any = null;
    let parsed = false;
    try {
      data = rawText ? JSON.parse(rawText) : null;
      parsed = true;
    } catch {
      data = { error: rawText || 'Backend error' };
    }

    if (!parsed) {
      return NextResponse.json({
        error: 'Backend returned non-JSON response',
        details: rawText ? rawText.slice(0, 200) : ''
      }, { status: backendResponse.status || 502 });
    }

    if (backendResponse.ok) {
      return NextResponse.json(data);
    } else {
      // 如果后端验证失败 (401)，前端也要清除 user_session
      const response = NextResponse.json(data, { status: backendResponse.status });

      if (backendResponse.status === 401) {
        response.cookies.set('user_session', '', { maxAge: 0 });
      }
      return response;
    }
  } catch (error: any) {
    console.error('Auth me API error:', error);
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 401 });
  }
}
