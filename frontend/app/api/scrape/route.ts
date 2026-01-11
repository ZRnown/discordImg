import { NextResponse } from 'next/server';

// 后端 API URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function POST(request: Request) {
  try {
    const data = await request.json();
    const { url, weidianId } = data;
    const cookieHeader = request.headers.get('cookie') || '';

    // 支持两种输入方式：完整URL或商品ID
    if (!url && !weidianId) {
      return NextResponse.json({ error: 'URL or weidianId is required' }, { status: 400 });
    }

    // 如果提供了weidianId，构造URL
    const finalUrl = url || `https://weidian.com/item.html?itemID=${weidianId}`;

    // 调用后端 API
    const backendResponse = await fetch(`${BACKEND_URL}/scrape`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookieHeader
      },
      body: JSON.stringify({ url: finalUrl })
    });

    // 修复：处理 409 Conflict，不要抛出通用错误，而是传递给前端处理
    if (backendResponse.status === 409) {
        const errorData = await backendResponse.json();
        return NextResponse.json(errorData, { status: 409 });
    }

    if (!backendResponse.ok) {
      const errorData = await backendResponse.json().catch(() => ({ error: 'Backend scrape failed' }));
      return NextResponse.json(errorData, { status: backendResponse.status });
    }

    const result = await backendResponse.json();
    return NextResponse.json(result);

  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const type = url.searchParams.get('type');

    if (type === 'indexed') {
      // 获取已建立向量索引的商品URL列表
      const response = await fetch(`${BACKEND_URL}/api/get_indexed_ids`);
      if (response.ok) {
        const data = await response.json();
        return NextResponse.json(data);
      }
      return NextResponse.json({ indexedIds: [] });
    }

    // 获取前端的session cookie并传递给后端
    const cookies = request.headers.get('cookie') || '';
    const headers: Record<string, string> = {};
    if (cookies) {
      headers['Cookie'] = cookies;
    }

    // 调用后端 API 获取商品列表
    const response = await fetch(`${BACKEND_URL}/api/products`, { headers });

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data);
    } else if (response.status === 401) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    return NextResponse.json([]);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const { id } = await request.json();
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/products/${id}`, {
      method: 'DELETE',
      headers: { 'Cookie': cookieHeader }
    });
    if (response.ok) {
      return NextResponse.json({ success: true });
    } else {
      const err = await response.json().catch(() => ({ error: 'Delete failed' }));
      return NextResponse.json(err, { status: response.status });
    }
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PUT方法用于更新商品信息
export async function PUT(request: Request) {
  try {
    const body = await request.json();
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/products`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookieHeader
      },
      body: JSON.stringify(body)
    });

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data);
    }
    return NextResponse.json({ error: 'Update failed' }, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PATCH方法用于删除单个图片
export async function PATCH(request: Request) {
  try {
    const { productId, imageIndex } = await request.json();
    const cookieHeader = request.headers.get('cookie') || '';

    const response = await fetch(`${BACKEND_URL}/api/products/${productId}/images/${imageIndex}`, {
      method: 'DELETE',
      headers: { 'Cookie': cookieHeader }
    });

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data);
    }
    return NextResponse.json({ error: 'Delete image failed' }, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
