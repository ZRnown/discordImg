import { NextResponse } from 'next/server';

// 后端 API URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

export async function POST(request: Request) {
  try {
    const data = await request.json();
    const { url, weidianId } = data;

    // 支持两种输入方式：完整URL或商品ID
    if (!url && !weidianId) {
      return NextResponse.json({ error: 'URL or weidianId is required' }, { status: 400 });
    }

    // 如果提供了weidianId，构造URL
    const finalUrl = url || `https://weidian.com/item.html?itemID=${weidianId}`;

    // 调用后端 API
    const backendResponse = await fetch(`${BACKEND_URL}/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: finalUrl })
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

    // 调用后端 API 获取商品列表
    const response = await fetch(`${BACKEND_URL}/api/products`);
    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data);
    }
    return NextResponse.json([]);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const { id } = await request.json();
    // 代理到后端服务以彻底删除（包括FAISS向量）
    const response = await fetch(`${BACKEND_URL}/api/products/${id}`, {
      method: 'DELETE'
    });
    if (response.ok) {
      return NextResponse.json({ success: true });
    } else {
      const err = await response.json();
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
    const response = await fetch(`${BACKEND_URL}/api/products/${body.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
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
    const response = await fetch(`${BACKEND_URL}/api/products/${productId}/images/${imageIndex}`, {
      method: 'DELETE'
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
