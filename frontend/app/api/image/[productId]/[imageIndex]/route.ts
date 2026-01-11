import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ productId: string; imageIndex: string }> }
) {
  try {
    const resolvedParams = await params
    const { productId, imageIndex } = resolvedParams;

    const response = await fetch(`${BACKEND_URL}/api/image/${productId}/${imageIndex}`);

    if (!response.ok) {
      return NextResponse.json({ error: 'Image not found' }, { status: response.status });
    }

    const imageBuffer = await response.arrayBuffer();
    const contentType = response.headers.get('content-type') || 'image/jpeg';

    return new NextResponse(imageBuffer, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch (error: any) {
    console.error('GET /api/image/[productId]/[imageIndex] failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
