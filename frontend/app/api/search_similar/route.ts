import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const cookie = request.headers.get('cookie')

    const response = await fetch(`${BACKEND_URL}/search_similar`, {
      method: 'POST',
      body: formData,
      headers: cookie ? { cookie } : undefined
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend search_similar error:', errorText);
      return NextResponse.json({ error: 'Search failed' }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('POST /api/search_similar failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
