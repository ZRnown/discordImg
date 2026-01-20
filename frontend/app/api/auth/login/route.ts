import { NextRequest, NextResponse } from 'next/server';
import { fetchFromBackend } from '../../_utils/backend';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const { response: backendResponse, rawText } = await fetchFromBackend('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }, request.headers.get('host'), 5000);
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
      const response = NextResponse.json(data);

      // --- 关键修复开始 ---
      // 1. 获取后端返回的原始 Set-Cookie 字符串
      // Flask 通常返回类似: "session=eyJ...; HttpOnly; Path=/; SameSite=Lax"
      const setCookieHeader = backendResponse.headers.get('set-cookie');

      if (setCookieHeader) {
        // 简单解析 Cookie 名称和值
        // 注意：如果后端返回多个 Cookie，这里可能需要更复杂的解析，但 Flask 默认通常只返回 session
        const firstPart = setCookieHeader.split(';')[0]; // 获取 "name=value"
        const [name, ...valueParts] = firstPart.split('=');
        const value = valueParts.join('='); // 防止值中包含 =

        if (name && value) {
          // 使用 Next.js API 设置 Cookie，避免与 header 操作冲突
          response.cookies.set({
            name: name.trim(),
            value: value.trim(),
            httpOnly: true, // 保持 HttpOnly 增强安全性
            path: '/',
            sameSite: 'lax',
            secure: false, // 【关键修改】强制为 false，允许HTTP访问
            maxAge: 60 * 60 * 24 * 30 // 30天不过期
          });
        }
      }
      // --- 关键修复结束 ---

      // 2. 设置前端专用的 user_session (用于UI展示)
      response.cookies.set('user_session', JSON.stringify({
        user: data.user,
        timestamp: Date.now()
      }), {
        httpOnly: false, // 允许前端 JS 读取
        secure: false, // 【关键修改】强制为 false，允许HTTP访问
        sameSite: 'lax',
        path: '/',
        maxAge: 60 * 60 * 24 * 30 // 30天不过期
      });

      return response;
    } else {
      return NextResponse.json(data, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('Login API error:', error);
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 503 });
  }
}
