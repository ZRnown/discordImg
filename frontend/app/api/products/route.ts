// 强制使用内网回环地址，速度最快且最稳定
export const dynamic = 'force-dynamic'

const BACKEND_URL = 'http://127.0.0.1:5001'

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const query = url.searchParams.toString()
    const backendUrl = query
      ? `${BACKEND_URL}/api/products?${query}`
      : `${BACKEND_URL}/api/products`
    const response = await fetch(backendUrl, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        'Cookie': request.headers.get('cookie') || ''
      }
    })

    if (!response.ok) {
      return new Response(JSON.stringify({ error: 'Failed to fetch products' }), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    const data = await response.json()
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
    })
  } catch (error) {
    console.error('Error fetching products:', error)
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

export async function PUT(request: Request) {
  try {
    const contentType = request.headers.get('content-type') || ''

    let response;
    if (contentType.includes('multipart/form-data')) {
      // 处理FormData请求（包含文件上传）
      const formData = await request.formData()

      response = await fetch(`${BACKEND_URL}/api/products`, {
        method: 'PUT',
        headers: {
          'Cookie': request.headers.get('cookie') || ''
        },
        body: formData
      })
    } else {
      // 处理JSON请求
      const body = await request.json()

      response = await fetch(`${BACKEND_URL}/api/products`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Cookie': request.headers.get('cookie') || ''
        },
        body: JSON.stringify(body)
      })
    }

    if (!response.ok) {
      return new Response(JSON.stringify({ error: 'Failed to update product' }), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    const data = await response.json()
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  } catch (error) {
    console.error('Error updating product:', error)
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

export async function DELETE(request: Request) {
  try {
    const url = new URL(request.url)
    const ids = url.searchParams.get('ids')

    if (!ids) {
      return new Response(JSON.stringify({ error: 'Missing ids parameter' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    const response = await fetch(`${BACKEND_URL}/api/products/batch`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': request.headers.get('cookie') || ''
      },
      body: JSON.stringify({ ids: ids.split(',').map(id => parseInt(id)) })
    })

    if (!response.ok) {
      return new Response(JSON.stringify({ error: 'Failed to delete products' }), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    const data = await response.json()
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  } catch (error) {
    console.error('Error deleting products:', error)
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}
