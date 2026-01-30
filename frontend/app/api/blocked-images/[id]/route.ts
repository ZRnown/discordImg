import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params;
    const cookies = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/blocked-images/${resolvedParams.id}`, {
      method: 'DELETE',
      headers: cookies ? { cookie: cookies } : undefined
    });

    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('DELETE /api/blocked-images/[id] failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
