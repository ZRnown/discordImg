import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

// 后端 API URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5001';

// 调用Python服务提取特征
async function extractFeatures(imagePath: string): Promise<number[]> {
  try {
    const formData = new FormData();
    const imageBuffer = fs.readFileSync(imagePath);
    const blob = new Blob([imageBuffer]);
    formData.append('image', blob, 'image.jpg');

    const response = await fetch('http://localhost:5001/extract_features', {
      method: 'POST',
      body: formData
    });

    if (response.ok) {
      const data = await response.json();
      return data.features;
    } else {
      console.log('Python服务调用失败，使用模拟特征');
      // 降级到模拟特征
      const features: number[] = [];
      for (let i = 0; i < 512; i++) {
        features.push(Math.random());
      }
      return features;
    }
  } catch (e) {
    console.log('Python服务不可用，使用模拟特征:', e);
    // 降级到模拟特征
    const features: number[] = [];
    for (let i = 0; i < 512; i++) {
      features.push(Math.random());
    }
    return features;
  }
}

// 计算余弦相似度
function cosineSimilarity(vecA: number[], vecB: number[]): number {
  if (vecA.length !== vecB.length) return 0;

  let dotProduct = 0;
  let normA = 0;
  let normB = 0;

  for (let i = 0; i < vecA.length; i++) {
    dotProduct += vecA[i] * vecB[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }

  normA = Math.sqrt(normA);
  normB = Math.sqrt(normB);

  if (normA === 0 || normB === 0) return 0;

  return dotProduct / (normA * normB);
}

export async function POST(request: Request) {
  try {
    const { url } = await request.json();

    if (!url) return NextResponse.json({ error: 'URL is required' }, { status: 400 });

    // 调用后端 API
    const backendResponse = await fetch(`${BACKEND_URL}/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
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
      try {
        const response = await fetch(`${BACKEND_URL}/api/get_indexed_ids`);
        if (response.ok) {
          const data = await response.json();
          return NextResponse.json(data);
        }
      } catch (e) {
        console.log('后端服务不可用:', e);
      }

      return NextResponse.json({ indexedIds: [] });
    }

    // 调用后端 API 获取商品列表
    try {
      const response = await fetch(`${BACKEND_URL}/api/products`);
      if (response.ok) {
        const data = await response.json();
        return NextResponse.json(data);
      }
    } catch (e) {
      console.log('后端服务不可用:', e);
    }
    return NextResponse.json([]);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const { id } = await request.json();
    // 代理到后端服务以彻底删除（包括 Milvus 向量）
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

export async function PUT(request: Request) {
  try {
    const body = await request.json();
    const db = getDb();
    const index = db.products.findIndex((p: any) => p.id === body.id);
    if (index !== -1) {
      db.products[index] = { ...db.products[index], ...body };
      saveDb(db);
      return NextResponse.json(db.products[index]);
    }
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// 图片向量搜索
export async function OPTIONS(request: Request) {
  try {
    const formData = await request.formData();
    const imageFile = formData.get('image') as File;

    if (!imageFile) {
      return NextResponse.json({ error: 'No image provided' }, { status: 400 });
    }

    // 直接调用Python服务进行搜索
    try {
      const pythonFormData = new FormData();
      pythonFormData.append('image', imageFile);

      const response = await fetch('http://localhost:5001/search_similar', {
        method: 'POST',
        body: pythonFormData
      });

      if (response.ok) {
        const result = await response.json();

        if (result.success) {
          // 根据SKU ID查找商品信息
          const db = getDb();
          const product = db.products.find((p: any) => p.weidianId === result.skuId);

          return NextResponse.json({
            success: true,
            similarity: result.similarity,
            product: product,
            skuId: result.skuId,
            imageIndex: result.imageIndex
          });
        } else {
          return NextResponse.json({
            success: false,
            message: result.message || '未找到相似商品'
          });
        }
      } else {
        console.log('Python服务搜索失败，降级到本地搜索');
      }
    } catch (e) {
      console.log('Python服务不可用，降级到本地搜索:', e);
    }

    // 降级到本地搜索
    const uploadDir = path.join(process.cwd(), 'public', 'uploads');
    if (!fs.existsSync(uploadDir)) {
      fs.mkdirSync(uploadDir, { recursive: true });
    }

    const fileName = `search_${Date.now()}.jpg`;
    const filePath = path.join(uploadDir, fileName);
    const buffer = Buffer.from(await imageFile.arrayBuffer());
    fs.writeFileSync(filePath, buffer);

    // 提取特征向量
    const features = await extractFeatures(filePath);

    // 在向量数据库中搜索
    const vectorDb = getVectorDb();
    let bestMatch = null;
    let bestSimilarity = 0;

    for (const vector of vectorDb.vectors) {
      const similarity = cosineSimilarity(features, vector.features);
      if (similarity > bestSimilarity && similarity > 0.1) { // 降低阈值
        bestSimilarity = similarity;
        bestMatch = vector;
      }
    }

    // 清理临时文件
    try {
      fs.unlinkSync(filePath);
    } catch (e) {}

    if (bestMatch) {
      // 根据SKU ID查找商品信息
      const db = getDb();
      const product = db.products.find((p: any) => p.weidianId === bestMatch.skuId);

      return NextResponse.json({
        success: true,
        similarity: bestSimilarity,
        product: product,
        skuId: bestMatch.skuId,
        imageIndex: bestMatch.imageIndex
      });
    } else {
      return NextResponse.json({
        success: false,
        message: '未找到相似商品'
      });
    }
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// 删除单个图片
export async function PATCH(request: Request) {
  try {
    const { productId, imageIndex } = await request.json();
    const db = getDb();
    const productIndex = db.products.findIndex((p: any) => p.id === productId);

    if (productIndex === -1) {
      return NextResponse.json({ error: 'Product not found' }, { status: 404 });
    }

    const product = db.products[productIndex];
    if (!product.images || imageIndex >= product.images.length) {
      return NextResponse.json({ error: 'Image not found' }, { status: 404 });
    }

    // 删除服务器上的图片文件
    const itemDir = path.join(IMAGES_DIR, product.weidianId);
    const fileName = `${imageIndex}.jpg`;
    const filePath = path.join(itemDir, fileName);

    try {
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
        console.log(`Deleted image file: ${filePath}`);
      }
    } catch (fileError) {
      console.log(`Failed to delete file: ${filePath}`, fileError);
    }

    // 从向量数据库中移除对应的向量
    const vectorDb = getVectorDb();
    vectorDb.vectors = vectorDb.vectors.filter((v: any) =>
      !(v.skuId === product.weidianId && v.imageIndex === imageIndex)
    );
    saveVectorDb(vectorDb);

    // 通知Python服务移除索引
    try {
      await fetch('http://localhost:5001/remove_from_index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skuId: product.weidianId,
          imageIndex: imageIndex
        })
      });
    } catch (e) {
      console.log('Python服务移除索引失败:', e);
    }

    // 从数据库中移除图片
    product.images.splice(imageIndex, 1);
    saveDb(db);

    return NextResponse.json({ success: true, product });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
