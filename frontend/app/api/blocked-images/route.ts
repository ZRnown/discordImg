import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function GET(request: NextRequest) {
  try {
    const cookies = request.headers.get('cookie') || '';
    const response = await fetch(`${BACKEND_URL}/api/blocked-images`, {
      headers: cookies ? { cookie: cookies } : undefined
    });

    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('GET /api/blocked-images failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const cookies = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/blocked-images`, {
      method: 'POST',
      body: formData,
      headers: cookies ? { cookie: cookies } : undefined
    });

    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('POST /api/blocked-images failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
