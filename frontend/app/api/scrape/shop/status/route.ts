import { NextResponse } from 'next/server';

// 后端 API URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:5001';

export async function GET(request: Request) {
  try {
    const cookieHeader = request.headers.get('cookie') || '';

    // 调用后端 API
    const backendResponse = await fetch(`${BACKEND_URL}/api/scrape/shop/status`, {
      method: 'GET',
      headers: {
        'Cookie': cookieHeader
      }
    });

    if (!backendResponse.ok) {
      const errorData = await backendResponse.json().catch(() => ({ error: 'Backend error' }));
      return NextResponse.json(errorData, { status: backendResponse.status });
    }

    const result = await backendResponse.json();
    return NextResponse.json(result);

  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
