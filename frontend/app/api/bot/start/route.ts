import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { userId } = body;

    if (!userId) {
      return NextResponse.json({ error: '需要用户ID' }, { status: 400 });
    }

    // 获取前端的session cookie并传递给后端
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    // 调用后端启动机器人API
    const backendResponse = await fetch(`${BACKEND_URL}/api/bot/start`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ userId })
    });

    const data = await backendResponse.json();

    if (backendResponse.ok) {
      return NextResponse.json(data);
    } else {
      return NextResponse.json(data, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('Start bot API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
