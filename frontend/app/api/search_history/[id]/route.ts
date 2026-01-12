import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const resolvedParams = await params;
    const historyId = resolvedParams.id;

    const response = await fetch(`${BACKEND_URL}/api/search_history/${historyId}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      const errorData = await response.json();
      return NextResponse.json(errorData, { status: response.status });
    }

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('DELETE /api/search_history/[id] failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
