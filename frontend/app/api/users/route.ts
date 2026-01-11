import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001';

// 获取用户列表（管理员权限）
export async function GET(request: NextRequest) {
  try {
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = {};
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    const backendResponse = await fetch(`${BACKEND_URL}/api/users`, { headers });
    const data = await backendResponse.json();

    if (backendResponse.ok) {
      return NextResponse.json(data);
    } else {
      return NextResponse.json(data, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('Users API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// 创建新用户（管理员权限）
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    const backendResponse = await fetch(`${BACKEND_URL}/api/users`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body)
    });

    const data = await backendResponse.json();

    if (backendResponse.ok) {
      return NextResponse.json(data);
    } else {
      return NextResponse.json(data, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('Create user API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
