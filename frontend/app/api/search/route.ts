import { NextRequest, NextResponse } from 'next/server'

// 获取后端 URL
const getBackendUrl = () => {
  return process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001'
}

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()
    const imageFile = formData.get('image') as File
    const threshold = parseFloat(formData.get('threshold') as string) || 0.1

    if (!imageFile) {
      return NextResponse.json({ error: 'No image provided' }, { status: 400 })
    }

    console.log('收到图片搜索请求，文件大小:', imageFile.size, 'bytes')

    // 创建新的 FormData 传递给后端
    const backendFormData = new FormData()
    const buffer = Buffer.from(await imageFile.arrayBuffer())
    const blob = new Blob([buffer], { type: imageFile.type })
    backendFormData.append('image', blob, imageFile.name || 'search.jpg')

    const backendUrl = getBackendUrl()
    console.log('调用后端搜索 API:', `${backendUrl}/search_similar`)

    // 直接调用后端的向量搜索 API (使用 Faiss)
    const response = await fetch(`${backendUrl}/search_similar`, {
      method: 'POST',
      body: backendFormData
    })

    if (!response.ok) {
      const errorText = await response.text()
      console.error('后端搜索失败:', response.status, errorText)
      return NextResponse.json({
        error: `后端搜索失败: ${response.status}`,
        details: errorText
      }, { status: response.status })
    }

    const result = await response.json()
    console.log('后端搜索结果:', result)

    if (result.success && result.product) {
      // 后端返回成功，格式化响应
      return NextResponse.json({
        success: true,
        similarity: result.similarity,
        product: {
          id: result.product.id,
          title: result.product.title,
          englishTitle: result.product.englishTitle,
          weidianId: result.skuId,
          weidianUrl: result.skuId, // 直接使用 product_url
          cnfansUrl: result.skuId, // 简化处理
          ruleEnabled: result.product.ruleEnabled,
          matchKeywords: result.product.matchKeywords,
          matchType: result.product.matchType,
          images: [] // 可以从数据库加载
        },
        skuId: result.skuId,
        imageIndex: result.imageIndex,
        matchedImage: `/scraped_images/${result.skuId}/${result.imageIndex}.jpg`,
        searchTime: new Date().toISOString()
      })
    } else {
      // 未找到匹配
      return NextResponse.json({
        success: false,
        message: result.message || `未找到相似度超过 ${(threshold * 100).toFixed(0)}% 的商品`
      })
    }

  } catch (error: any) {
    console.error('搜索错误:', error)
    return NextResponse.json({
      error: error.message,
      stack: error.stack
    }, { status: 500 })
  }
}
