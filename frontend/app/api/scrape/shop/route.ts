import { NextResponse } from 'next/server';

// 后端 API URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:5001';

export async function POST(request: Request) {
  try {
    const body = await request.json();

    // 调用后端 API
    const backendResponse = await fetch(`${BACKEND_URL}/api/scrape/shop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    if (!backendResponse.ok) {
      const errorData = await backendResponse.json();
      return NextResponse.json(errorData, { status: backendResponse.status });
    }

    const result = await backendResponse.json();
    return NextResponse.json(result);

  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
