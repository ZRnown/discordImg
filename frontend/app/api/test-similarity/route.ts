import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();

    const response = await fetch(`${BACKEND_URL}/api/test_similarity`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend test_similarity error:', errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch (error: any) {
    console.error('POST /api/test-similarity failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
