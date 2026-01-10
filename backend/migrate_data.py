#!/usr/bin/env python3
"""
数据迁移脚本：将PP-ShiTuV2数据迁移到DINOv2 + FAISS方案

使用方法：
1. 备份旧数据：cp data/metadata.db data/metadata_old.db
2. 运行迁移：python migrate_data.py

注意：
- 迁移过程会重新提取所有图片的特征向量
- 旧的Milvus数据将被完全替换
- 迁移过程可能需要较长时间，取决于图片数量
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import db
from feature_extractor import get_feature_extractor
from vector_engine import get_vector_engine
from config import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate_data():
    """执行数据迁移"""
    logger.info("开始数据迁移：PP-ShiTuV2 -> DINOv2 + FAISS")

    try:
        # 1. 检查旧数据是否存在
        logger.info("检查旧数据...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            product_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM product_images")
            image_count = cursor.fetchone()[0]

        logger.info(f"发现 {product_count} 个商品，{image_count} 张图片")

        if image_count == 0:
            logger.info("没有图片数据需要迁移")
            return

        # 2. 获取所有图片路径
        logger.info("获取图片路径...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pi.id, pi.product_id, pi.image_path, pi.image_index, p.title
                FROM product_images pi
                JOIN products p ON pi.product_id = p.id
                ORDER BY pi.product_id, pi.image_index
            """)
            images = cursor.fetchall()

        logger.info(f"需要处理 {len(images)} 张图片")

        # 3. 初始化新的AI引擎
        logger.info("初始化DINOv2 + YOLOv8引擎...")
        extractor = get_feature_extractor()
        engine = get_vector_engine()

        # 4. 重新提取特征并建立索引
        migrated_count = 0
        failed_count = 0

        for image_record in images:
            try:
                image_id = image_record['id']
                product_id = image_record['product_id']
                image_path = image_record['image_path']
                image_index = image_record['image_index']
                product_title = image_record['title']

                logger.info(f"处理商品 '{product_title}' 的图片 {image_index}...")

                # 检查图片文件是否存在
                if not os.path.exists(image_path):
                    logger.warning(f"图片文件不存在: {image_path}")
                    failed_count += 1
                    continue

                # 提取特征 (包含YOLO裁剪)
                features = extractor.extract_feature(image_path)
                if features is None:
                    logger.error(f"特征提取失败: {image_path}")
                    failed_count += 1
                    continue

                # 添加到FAISS索引
                success = engine.add_vector(image_id, features)
                if not success:
                    logger.error(f"FAISS索引失败: product_id={product_id}, image_index={image_index}")
                    failed_count += 1
                    continue

                migrated_count += 1
                logger.info(f"✅ 迁移成功: {product_title} - 图片{image_index}")

            except Exception as e:
                logger.error(f"迁移图片失败: {e}")
                failed_count += 1
                continue

        # 5. 保存索引
        logger.info("保存FAISS索引...")
        engine.save()

        # 6. 输出迁移结果
        logger.info("=" * 50)
        logger.info("数据迁移完成！")
        logger.info(f"成功迁移: {migrated_count} 张图片")
        logger.info(f"迁移失败: {failed_count} 张图片")
        logger.info(f"向量维度: {config.VECTOR_DIMENSION}")
        logger.info(f"索引类型: HNSW")
        logger.info(f"相似度度量: InnerProduct (Cosine)")
        logger.info("=" * 50)

        if failed_count > 0:
            logger.warning("注意：部分图片迁移失败，请检查日志")
        else:
            logger.info("🎉 所有数据迁移成功！")

        # 7. 建议清理旧数据
        logger.info("建议操作：")
        logger.info("1. 验证新索引工作正常：python test_search_debug.py")
        logger.info("2. 备份完成后可删除旧的Milvus数据文件")
        logger.info("3. 重启应用服务")

    except Exception as e:
        logger.error(f"数据迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    """主函数"""
    print("猎鹰架构数据迁移工具")
    print("将PP-ShiTuV2数据迁移到DINOv2 + FAISS")
    print("-" * 50)

    # 检查命令行参数
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--yes':
        confirm = 'y'
    else:
        # 确认操作
        try:
            confirm = input("⚠️  此操作将重新提取所有图片特征，耗时较长。是否继续？(y/N): ")
        except EOFError:
            print("非交互环境，自动跳过确认")
            confirm = 'y'

    if confirm.lower() not in ['y', 'yes']:
        print("操作已取消")
        return

    # 执行迁移
    migrate_data()

if __name__ == "__main__":
    main()
