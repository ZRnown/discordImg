import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://69.30.204.184:5001';

export async function DELETE(

  request: NextRequest,

  { params }: { params: Promise<{ id: string }> }

) {

  try {

    const { id } = await params;

    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/users/${id}`, {

      method: 'DELETE',

      headers: { 'Cookie': cookieHeader }

    });

    if (!response.ok) {

      const errorData = await response.json().catch(() => ({}));

      return NextResponse.json(errorData, { status: response.status });

    }

    return NextResponse.json({ success: true });

  } catch (error: any) {

    return NextResponse.json({ error: error.message }, { status: 500 });

  }

}
