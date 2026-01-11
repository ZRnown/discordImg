import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function GET(request: NextRequest) {
  try {
    const cookies = request.headers.get('cookie') || '';

    const backendResponse = await fetch(`${BACKEND_URL}/api/user/settings`, {
        headers: {
            'Cookie': cookies
        }
    });

    if (backendResponse.ok) {
      const data = await backendResponse.json();
      return NextResponse.json(data);
    } else {
      // 捕获错误并返回状态码，前端收到 401 可处理跳转
      const errorData = await backendResponse.json().catch(() => ({ error: 'Failed to fetch settings' }));
      return NextResponse.json(errorData, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('User settings API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function PUT(request: NextRequest) {
  try {
    const body = await request.json();
    const cookies = request.headers.get('cookie') || '';

    const backendResponse = await fetch(`${BACKEND_URL}/api/user/settings`, {
      method: 'PUT',
      headers: {
          'Content-Type': 'application/json',
          'Cookie': cookies
      },
      body: JSON.stringify(body)
    });

    const data = await backendResponse.json();

    if (backendResponse.ok) {
      return NextResponse.json(data);
    } else {
      return NextResponse.json(data, { status: backendResponse.status });
    }
  } catch (error: any) {
    console.error('Update user settings API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
