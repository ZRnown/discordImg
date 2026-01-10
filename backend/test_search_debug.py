#!/usr/bin/env python3
"""
调试搜索问题的测试脚本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import db
from feature_extractor import get_feature_extractor
import numpy as np

def test_search():
    print("=== 搜索问题调试 ===")

    # 1. 检查Milvus状态
    print("\n1. 检查Milvus状态:")
    try:
        db._ensure_milvus_initialized()
        stats = db.milvus_client.get_collection_stats(collection_name="image_embeddings")
        entity_count = stats.get('row_count', 0)
        print(f"   集合存在: 是")
        print(f"   实体数量: {entity_count}")
    except Exception as e:
        print(f"   错误: {e}")
        return

    # 2. 检查数据库中的产品和图片
    print("\n2. 检查数据库中的产品和图片:")
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            product_count = cursor.fetchone()[0]
            print(f"   产品数量: {product_count}")

            cursor.execute("SELECT COUNT(*) FROM product_images WHERE milvus_id IS NOT NULL")
            indexed_count = cursor.fetchone()[0]
            print(f"   已索引图片数量: {indexed_count}")

            if indexed_count > 0:
                cursor.execute("SELECT id, product_id, image_path, milvus_id FROM product_images WHERE milvus_id IS NOT NULL LIMIT 3")
                rows = cursor.fetchall()
                print("   示例索引记录:")
                for row in rows:
                    print(f"     ID: {row[0]}, Product: {row[1]}, Path: {row[2]}, MilvusID: {row[3]}")
    except Exception as e:
        print(f"   数据库错误: {e}")

    # 3. 测试特征提取
    print("\n3. 测试特征提取:")
    try:
        extractor = get_feature_extractor()
        # 创建一个简单的测试图片路径 (使用已存在的图片)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT image_path FROM product_images WHERE milvus_id IS NOT NULL LIMIT 1")
            row = cursor.fetchone()
            if row:
                test_image_path = row[0]
                print(f"   测试图片路径: {test_image_path}")
                if os.path.exists(test_image_path):
                    features = extractor.extract_feature(test_image_path)
                    if features:
                        print(f"   特征提取成功: {len(features)}维")
                        print(f"   特征范数: {np.linalg.norm(features):.4f}")
                    else:
                        print("   特征提取失败")
                else:
                    print("   测试图片不存在")
            else:
                print("   没有找到索引的图片")
    except Exception as e:
        print(f"   特征提取错误: {e}")

    # 4. 测试搜索
    print("\n4. 测试搜索:")
    try:
        if indexed_count > 0:
            # 使用第一个索引的图片进行自搜索
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT image_path FROM product_images WHERE milvus_id IS NOT NULL LIMIT 1")
                row = cursor.fetchone()
                test_image_path = row[0]

            if os.path.exists(test_image_path):
                features = extractor.extract_feature(test_image_path)
                if features:
                    print(f"   使用特征向量搜索，阈值0.0...")
                    results = db.search_similar_images(features, limit=5, threshold=0.0)
                    print(f"   搜索结果数量: {len(results)}")
                    if results:
                        for i, result in enumerate(results):
                            print(f"     结果{i+1}: 相似度 {result['similarity']:.4f}, 产品ID {result['id']}")
                    else:
                        print("   无搜索结果")
                else:
                    print("   无法提取特征进行搜索测试")
            else:
                print("   测试图片不存在")
        else:
            print("   没有索引的图片，无法测试搜索")
    except Exception as e:
        print(f"   搜索测试错误: {e}")

if __name__ == "__main__":
    test_search()
