import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

// 分配Discord账号给用户
export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const resolvedParams = await params;
    const accountId = resolvedParams.id;
    const body = await request.json();
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    const backendResponse = await fetch(`${BACKEND_URL}/api/accounts/${accountId}/user`, {
      method: 'PUT',
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
    console.error('Assign account to user API error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
