from flask import Flask, request, jsonify
import numpy as np
import os
import logging
from datetime import datetime
from feature_extractor import get_feature_extractor
from database import db
from config import config

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def extract_features(image_path):
    """使用深度学习模型提取图像特征"""
    try:
        extractor = get_feature_extractor()
        features = extractor.extract_feature(image_path)
        # 如果特征提取失败，返回 None（上层将处理并返回错误）
        if features is None:
            logger.warning(f"特征提取失败: {image_path}")
            return None

        return features

    except Exception as e:
        logger.error(f"特征提取异常: {e}")
        return None

@app.route('/search_similar', methods=['POST'])
def search_similar():
    """搜索相似图像 - 使用 Milvus Lite"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        image_file = request.files['image']
        threshold = float(request.form.get('threshold', 0.3))  # 从0到1，默认30% (降低阈值)

        # 调试信息
        print(f"DEBUG: Received threshold: {threshold}")
        print(f"DEBUG: Form data: {list(request.form.keys())}")

        # 保存查询图片到临时文件
        import uuid
        temp_filename = f"{uuid.uuid4()}.jpg"
        image_path = f"/tmp/{temp_filename}"
        image_file.save(image_path)

        try:
            # 提取特征 (使用 PP-ShiTuV2)
            query_features = extract_features(image_path)

            if query_features is None:
                return jsonify({'error': 'Feature extraction failed'}), 500

            # 使用 Milvus 向量搜索
            print(f"DEBUG: Searching with threshold: {threshold}, vector length: {len(query_features)}")
            # 临时将阈值设为0，确保能返回结果进行调试
            debug_threshold = max(0.0, threshold)  # 确保不为负数
            results = db.search_similar_images(query_features, limit=1, threshold=debug_threshold)
            print(f"DEBUG: Search results count: {len(results) if results else 0}")
            if results:
                print(f"DEBUG: Best match similarity: {results[0]['similarity']}")
            print(f"DEBUG: Total indexed images: {db.get_total_indexed_images()}")

            response_data = {
                'success': False,
                'message': f'未找到相似度超过{threshold*100:.0f}%的商品',
                'searchTime': datetime.now().isoformat(),
                'debugInfo': {
                    'totalIndexedImages': db.get_total_indexed_images(),
                    'threshold': threshold,
                    'searchedVectors': len(results) if results else 0
                }
            }

            if results:
                # 返回最相似的结果
                best_match = results[0]

                # 获取完整产品信息
                product_info = db._get_product_info_by_id(best_match['id'])

                # 保存搜索历史
                db.add_search_history(
                    query_image_path=image_path,
                    matched_product_id=best_match['id'],
                    matched_image_index=best_match['image_index'],
                    similarity=float(best_match['similarity']),
                    threshold=threshold
                )

                response_data = {
                    'success': True,
                    'similarity': float(best_match['similarity']),
                    'skuId': product_info['product_url'] if product_info else best_match['product_url'],
                    'imageIndex': best_match['image_index'],
                    'matchedImage': f"/api/image/{best_match['id']}/{best_match['image_index']}",
                    'searchTime': datetime.now().isoformat(),
                    'debugInfo': {
                        'totalIndexedImages': db.get_total_indexed_images(),
                        'threshold': threshold,
                        'bestSimilarity': float(best_match['similarity']),
                        'searchedVectors': len(results) if results else 0
                    },
                    'product': {
                        'id': best_match['id'],
                        'title': product_info['title'] if product_info else best_match['title'],
                        'englishTitle': product_info.get('english_title', ''),
                        'weidianUrl': product_info['product_url'] if product_info else best_match['product_url'],
                        'cnfansUrl': product_info.get('cnfans_url', ''),
                        'ruleEnabled': product_info.get('ruleEnabled', True) if product_info else True,
                        'images': [f"/api/image/{best_match['id']}/{i}" for i in range(10)]  # 预估图片数量
                    }
                }

            return jsonify(response_data)

        finally:
            # 清理临时文件
            if os.path.exists(image_path):
                os.unlink(image_path)

    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/scrape', methods=['POST'])
def scrape_product():
    """抓取商品并建立索引"""
    try:
        data = request.json
        url = data.get('url')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        # 验证URL格式
        if 'weidian.com' not in url:
            return jsonify({'error': '只支持微店商品链接'}), 400

        logger.info(f"开始抓取商品: {url}")

        # 使用真正的爬虫
        from weidian_scraper import get_weidian_scraper
        scraper = get_weidian_scraper()

        # 抓取商品信息
        product_info = scraper.scrape_product_info(url)

        if not product_info:
            return jsonify({'error': '商品信息抓取失败，请检查URL是否正确'}), 500

        # 保存到数据库（使用全局延迟配置）
        product_id = db.insert_product({
            'product_url': product_info['weidian_url'],
            'title': product_info['title'],
            'description': product_info['description'],
            'english_title': product_info.get('english_title') or '',
            'cnfans_url': product_info.get('cnfans_url') or '',
            'ruleEnabled': True  # 默认启用自动回复规则
        })

        # 下载图片并建立向量索引
        if product_info['images']:
            logger.info(f"下载 {len(product_info['images'])} 张图片并建立索引")

            # 创建图片保存目录
            import os
            images_dir = os.path.join(os.path.dirname(__file__), 'data', 'scraped_images', product_info['id'])
            os.makedirs(images_dir, exist_ok=True)

            # 下载图片
            saved_image_paths = scraper.download_images(
                product_info['images'],
                images_dir,
                product_info['id']
            )
            # 如果配置启用主体检测，则尝试对下载的图片做检测裁剪（可选）
            if config.USE_DETECT:
                try:
                    from detection import detect_and_crop_batch
                    logger.info("USE_DETECT=True，正在对下载图片执行主体检测并裁剪...")
                    cropped_paths = detect_and_crop_batch(saved_image_paths, images_dir, product_info['id'], model_dir=config.DETECTION_MODEL_DIR)
                    if cropped_paths:
                        saved_image_paths = cropped_paths
                except Exception as e:
                    logger.warning(f"检测模块不可用或执行失败，跳过检测: {e}")

            # 为每张图片建立向量索引
            from feature_extractor import get_feature_extractor
            extractor = get_feature_extractor()

            indexed_images = []
            for i, img_path in enumerate(saved_image_paths):
                try:
                    # 提取特征向量
                    features = extractor.extract_feature(img_path)
                    if features is None:
                        # 特征提取失败——中止并回滚已插入的数据
                        logger.error(f"图片特征提取失败: {img_path}，中止商品建立并回滚")
                        # 尝试删除已保存的文件和数据库记录
                        try:
                            db.delete_product_images(product_id)
                        except Exception as del_e:
                            logger.error(f"回滚删除失败: {del_e}")
                        return jsonify({'error': 'Feature extraction failed for one or more images'}), 500

                    # 插入向量索引
                    success = db.insert_image_vector(
                        product_id=product_id,
                        image_path=img_path,
                        image_index=i,
                        vector=features
                    )
                    if success:
                        indexed_images.append(f"{i}.jpg")
                        logger.info(f"图片 {i} 索引建立成功")
                    else:
                        logger.error(f"图片 {i} 索引建立失败，回滚并返回错误")
                        try:
                            db.delete_product_images(product_id)
                        except Exception as del_e:
                            logger.error(f"回滚删除失败: {del_e}")
                        return jsonify({'error': 'Failed to insert image vector into Milvus'}), 500

                except Exception as e:
                    logger.error(f"处理图片 {i} 时出错: {e}")
                    try:
                        db.delete_product_images(product_id)
                    except Exception as del_e:
                        logger.error(f"回滚删除失败: {del_e}")
                    return jsonify({'error': 'Error processing image files'}), 500

            logger.info(f"共建立 {len(indexed_images)} 张图片的索引")
        else:
            logger.warning("未找到商品图片")

        # 返回完整的商品信息
        result = {
            'id': product_id,
            'weidianId': product_info['id'],  # 添加微店商品ID
            'product_url': product_info['weidian_url'],
            'title': product_info['title'],
            'englishTitle': product_info['english_title'],
            'weidianUrl': product_info['weidian_url'],
            'cnfansUrl': product_info['cnfans_url'],
            'description': product_info['description'],
            'ruleEnabled': True,  # 默认启用规则
            'createdAt': datetime.now().isoformat(),
            'images': product_info['images']  # 返回图片URL列表
        }

        logger.info(f"商品抓取完成: {product_info['title']}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"抓取失败: {e}")
        return jsonify({'error': str(e)}), 500

# Discord 账号管理 API
@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """获取所有 Discord 账号"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, status, last_active, created_at, updated_at
                FROM discord_accounts
                ORDER BY created_at DESC
            """)
            accounts = []
            for row in cursor.fetchall():
                accounts.append({
                    'id': row[0],
                    'username': row[1],
                    'status': row[2],
                    'lastActive': row[3],
                    'createdAt': row[4]
                })
        return jsonify(accounts)
    except Exception as e:
        logger.error(f"获取账号列表失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products', methods=['GET'])
def list_products():
    """列出所有已保存的商品及其图片"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products ORDER BY created_at DESC")
            rows = cursor.fetchall()
            products = []
            for row in rows:
                prod = dict(row)
                # 获取图片路径
                cursor.execute("SELECT image_path FROM product_images WHERE product_id = ? ORDER BY image_index", (prod['id'],))
                rows_imgs = cursor.fetchall()
                images = []
                for idx, r in enumerate(rows_imgs):
                    local_path = r[0]
                    # 构建可访问的图片URL：/api/image/<product_id>/<index>
                    try:
                        host = request.host_url.rstrip('/')
                        images.append(f"{host}/api/image/{prod['id']}/{idx}")
                    except Exception:
                        images.append('')
                prod['images'] = images
                prod['weidianUrl'] = prod.get('product_url')
                # 提取微店ID (itemID)
                try:
                    import re
                    m = re.search(r'itemID=(\d+)', prod.get('product_url') or '')
                    prod['weidianId'] = m.group(1) if m else ''
                except Exception:
                    prod['weidianId'] = ''
                # 保留 camelCase 字段以兼容前端
                prod['englishTitle'] = prod.get('english_title') or prod.get('englishTitle') or ''
                prod['cnfansUrl'] = prod.get('cnfans_url') or prod.get('cnfansUrl') or ''
                prod['createdAt'] = prod.get('created_at') or prod.get('createdAt')
                # 移除商品级别延迟，使用全局延迟
                prod.pop('min_delay', None)
                prod.pop('max_delay', None)
                products.append(prod)
        return jsonify(products)
    except Exception as e:
        logger.error(f"列出商品失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/backfill_products', methods=['POST'])
def backfill_products():
    """为已存在但缺少英名或 cnfans 链接的商品回填数据"""
    try:
        from weidian_scraper import get_weidian_scraper
        scraper = get_weidian_scraper()

        updated = []
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, product_url, english_title, cnfans_url FROM products")
            rows = cursor.fetchall()

            for row in rows:
                pid = row['id']
                url = row['product_url']
                need_english = not row['english_title']
                need_cnfans = not row['cnfans_url']
                if not (need_english or need_cnfans):
                    continue

                product_info = scraper.scrape_product_info(url)
                if not product_info:
                    logger.warning(f"回填失败，无法抓取: {url}")
                    continue

                english = product_info.get('english_title') or ''
                cnfans = product_info.get('cnfans_url') or ''

                cursor.execute("""
                    UPDATE products
                    SET english_title = ?, cnfans_url = ?
                    WHERE id = ?
                """, (english, cnfans, pid))
                conn.commit()
                updated.append(pid)

        return jsonify({'updated': updated, 'count': len(updated)})
    except Exception as e:
        logger.error(f"回填失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/rebuild_vectors', methods=['POST'])
def rebuild_vectors():
    """为已有商品（或缺失向量的图片）重建特征并插入 Milvus"""
    try:
        extractor = get_feature_extractor()
        rebuilt = []
        failed = []

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 查找所有 product_images 中 milvus_id 为空或 NULL 的记录
            cursor.execute("SELECT id, product_id, image_path, image_index FROM product_images WHERE milvus_id IS NULL OR milvus_id = ''")
            rows = cursor.fetchall()

        for row in rows:
            pid = row['product_id']
            img_path = row['image_path']
            idx = row['image_index']
            try:
                features = extractor.extract_feature(img_path)
                if features is None:
                    logger.error(f"重建特征失败: {img_path}")
                    failed.append({'product_id': pid, 'image_index': idx})
                    continue

                success = db.insert_image_vector(product_id=pid, image_path=img_path, image_index=idx, vector=features)
                if success:
                    rebuilt.append({'product_id': pid, 'image_index': idx})
                else:
                    failed.append({'product_id': pid, 'image_index': idx})
            except Exception as e:
                logger.error(f"重建向量出错: {e}")
                failed.append({'product_id': pid, 'image_index': idx})

        return jsonify({'rebuilt': rebuilt, 'failed': failed, 'count': len(rebuilt)})
    except Exception as e:
        logger.error(f"重建向量失败: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/image/<int:product_id>/<int:image_index>', methods=['GET'])
def serve_product_image(product_id: int, image_index: int):
    """返回指定商品指定序号的图片文件（用于前端缩略图/查看）"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT image_path FROM product_images WHERE product_id = ? AND image_index = ?", (product_id, image_index))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Image not found'}), 404
            image_path = row[0]

        # 安全检查并返回文件
        from flask import send_file
        if not os.path.exists(image_path):
            return jsonify({'error': 'Image file missing'}), 404
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"serve_product_image 失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts', methods=['POST'])
def add_account():
    """添加新的 Discord 账号"""
    try:
        data = request.json
        token = data.get('token')
        username = data.get('username', '')

        if not token:
            return jsonify({'error': 'Token is required'}), 400

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO discord_accounts (username, token, status)
                VALUES (?, ?, 'offline')
            """, (username, token))
            account_id = cursor.lastrowid

            cursor.execute("SELECT id, username, status, last_active FROM discord_accounts WHERE id = ?", (account_id,))
            account = cursor.fetchone()
            conn.commit()

        return jsonify({
            'id': account[0],
            'username': account[1],
            'status': account[2],
            'lastActive': account[3]
        })
    except Exception as e:
        logger.error(f"添加账号失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    """删除 Discord 账号"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM discord_accounts WHERE id = ?", (account_id,))
            conn.commit()

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除账号失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<int:account_id>/status', methods=['PUT'])
def update_account_status(account_id):
    """更新账号状态"""
    try:
        data = request.json
        status = data.get('status')

        if status not in ['online', 'offline']:
            return jsonify({'error': 'Invalid status'}), 400

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE discord_accounts
                SET status = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (status, account_id))
            conn.commit()

        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"更新账号状态失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/rotation', methods=['GET'])
def get_rotation_config():
    """获取账号轮换配置"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT enabled, rotation_interval, current_account_id
                FROM account_rotation_config
                LIMIT 1
            """)
            row = cursor.fetchone()

        if row:
            return jsonify({
                'enabled': row[0],
                'rotationInterval': row[1],
                'currentAccountId': row[2]
            })
        return jsonify({'enabled': False, 'rotationInterval': 10})
    except Exception as e:
        logger.error(f"获取轮换配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/rotation', methods=['POST'])
def update_rotation_config():
    """更新账号轮换配置"""
    try:
        data = request.json
        enabled = data.get('enabled', False)
        rotation_interval = data.get('rotationInterval', 10)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE account_rotation_config
                SET enabled = ?, rotation_interval = ?, updated_at = datetime('now')
                WHERE id = 1
            """, (enabled, rotation_interval))
            conn.commit()

        return jsonify({'success': True, 'enabled': enabled, 'rotationInterval': rotation_interval})
    except Exception as e:
        logger.error(f"更新轮换配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/current', methods=['GET'])
def get_current_account():
    """获取当前使用的 Discord 账号"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, token
                FROM discord_accounts
                WHERE status = 'online'
                ORDER BY last_active DESC
                LIMIT 1
            """)
            account = cursor.fetchone()

        if account:
            return jsonify({
                'id': account[0],
                'username': account[1],
                'token': account[2]
            })
        return jsonify({'error': 'No active account found'}), 404
    except Exception as e:
        logger.error(f"获取当前账号失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/get_indexed_ids', methods=['GET'])
def get_indexed_ids():
    """获取已建立索引的商品URL列表"""
    try:
        indexed_urls = db.get_indexed_product_urls()
        return jsonify({'indexedIds': indexed_urls})
    except Exception as e:
        logger.error(f"获取已索引ID失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """删除商品及其所有相关数据"""
    try:
        # 删除商品及其向量数据
        if db.delete_product_images(product_id):
            return jsonify({'success': True, 'message': f'商品 {product_id} 已删除'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除商品失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/discord-threshold', methods=['GET'])
def get_discord_threshold():
    """获取Discord相似度阈值"""
    try:
        return jsonify({
            'threshold': config.DISCORD_SIMILARITY_THRESHOLD,
            'threshold_percentage': config.DISCORD_SIMILARITY_THRESHOLD * 100
        })
    except Exception as e:
        logger.error(f"获取Discord阈值失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/discord-threshold', methods=['POST'])
def update_discord_threshold():
    """更新Discord相似度阈值"""
    try:
        data = request.json
        threshold = float(data.get('threshold', 0.4))

        # 验证范围
        if not (0.0 <= threshold <= 1.0):
            return jsonify({'error': '阈值必须在0.0-1.0之间'}), 400

        # 这里可以保存到配置文件或数据库
        # 暂时只返回成功（实际使用时需要重启服务生效）
        logger.info(f"Discord相似度阈值设置为: {threshold} ({threshold*100:.0f}%)")

        return jsonify({
            'success': True,
            'threshold': threshold,
            'threshold_percentage': threshold * 100,
            'message': 'Discord阈值设置已更新，请重启Discord机器人服务以生效'
        })

    except Exception as e:
        logger.error(f"更新Discord阈值失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/global-reply-delay', methods=['GET'])
def get_global_reply_delay():
    """获取全局回复延迟配置"""
    try:
        delay_config = db.get_global_reply_config()
        return jsonify({
            'min_delay': delay_config['min_delay'],
            'max_delay': delay_config['max_delay'],
            'description': f'{delay_config["min_delay"]}-{delay_config["max_delay"]}秒随机延迟'
        })
    except Exception as e:
        logger.error(f"获取全局回复延迟失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/milvus_status', methods=['GET'])
def get_milvus_status():
    """获取Milvus数据库状态"""
    try:
        db._ensure_milvus_initialized()
        stats = db.milvus_client.get_collection_stats(collection_name="image_embeddings")
        entity_count = stats.get('row_count', 0)

        # 尝试搜索一个测试向量
        test_vector = [0.0] * 512  # 512维零向量
        test_results = db.milvus_client.search(
            collection_name="image_embeddings",
            data=[test_vector],
            limit=1,
            search_params={"metric_type": "COSINE", "params": {}}
        )

        return jsonify({
            'collection_exists': True,
            'entity_count': entity_count,
            'test_search_works': len(test_results) > 0 if test_results else False,
            'vector_dimension': 512,
            'metric_type': 'COSINE'
        })
    except Exception as e:
        logger.error(f"获取Milvus状态失败: {e}")
        return jsonify({
            'error': str(e),
            'collection_exists': False,
            'entity_count': 0
        }), 500

@app.route('/api/test_similarity', methods=['POST'])
def test_similarity():
    """测试两张图片的相似度"""
    try:
        if 'image1' not in request.files or 'image2' not in request.files:
            return jsonify({'error': '需要提供两张图片'}), 400

        image1_file = request.files['image1']
        image2_file = request.files['image2']

        # 保存临时文件
        import uuid
        temp_dir = os.path.join(config.IMAGE_SAVE_DIR, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        image1_path = os.path.join(temp_dir, f'test1_{uuid.uuid4()}.jpg')
        image2_path = os.path.join(temp_dir, f'test2_{uuid.uuid4()}.jpg')

        image1_file.save(image1_path)
        image2_file.save(image2_path)

        try:
            # 提取特征
            features1 = extract_features(image1_path)
            features2 = extract_features(image2_path)

            if features1 is None or features2 is None:
                return jsonify({'error': '特征提取失败'}), 500

            # 计算余弦相似度
            import numpy as np
            dot_product = np.dot(features1, features2)
            norm1 = np.linalg.norm(features1)
            norm2 = np.linalg.norm(features2)

            if norm1 == 0 or norm2 == 0:
                cosine_similarity = 0.0
            else:
                cosine_similarity = dot_product / (norm1 * norm2)

            # 确保相似度在[0,1]范围内
            cosine_similarity = max(0.0, min(1.0, cosine_similarity))

            return jsonify({
                'similarity': float(cosine_similarity),
                'similarity_percentage': float(cosine_similarity * 100),
                'model': 'PPLCNetV2_base (PP-ShiTuV2)',
                'vector_dimension': len(features1),
                'features1_norm': float(norm1),
                'features2_norm': float(norm2),
                'dot_product': float(dot_product)
            })

        finally:
            # 清理临时文件
            if os.path.exists(image1_path):
                os.remove(image1_path)
            if os.path.exists(image2_path):
                os.remove(image2_path)

    except Exception as e:
        logger.error(f"相似度测试失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/global-reply-delay', methods=['POST'])
def update_global_reply_delay():
    """更新全局回复延迟配置"""
    try:
        data = request.json
        min_delay = int(data.get('min_delay', 3))
        max_delay = int(data.get('max_delay', 8))

        # 验证范围
        if min_delay < 0 or max_delay < 0:
            return jsonify({'error': '延迟时间不能为负数'}), 400
        if min_delay > max_delay:
            return jsonify({'error': '最小延迟不能大于最大延迟'}), 400
        if max_delay > 300:
            return jsonify({'error': '最大延迟不能超过300秒'}), 400

        # 保存到数据库
        if db.update_global_reply_config(min_delay, max_delay):
            logger.info(f"全局回复延迟设置为: {min_delay}-{max_delay}秒")

            return jsonify({
                'success': True,
                'min_delay': min_delay,
                'max_delay': max_delay,
                'description': f'{min_delay}-{max_delay}秒随机延迟',
                'message': '全局回复延迟设置已更新，所有自动回复将使用此设置'
            })
        else:
            return jsonify({'error': '保存失败'}), 500

    except Exception as e:
        logger.error(f"更新全局回复延迟失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_history', methods=['GET'])
def get_search_history():
    """获取搜索历史记录"""
    try:
        limit = int(request.args.get('limit', 50))
        history = db.get_search_history(limit)
        return jsonify(history)
    except Exception as e:
        logger.error(f"获取搜索历史失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_history/<int:history_id>', methods=['DELETE'])
def delete_search_history(history_id):
    """删除搜索历史记录"""
    try:
        if db.delete_search_history(history_id):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '记录不存在'}), 404
    except Exception as e:
        logger.error(f"删除搜索历史失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_history', methods=['DELETE'])
def clear_search_history():
    """清空所有搜索历史"""
    try:
        if db.clear_search_history():
            return jsonify({'success': True})
        else:
            return jsonify({'error': '清空失败'}), 500
    except Exception as e:
        logger.error(f"清空搜索历史失败: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # 本地开发模式 - 总是启用热重载
    print("🚀 Starting Flask API in development mode...")
    print("🔄 Hot reload enabled - modify files and refresh browser")
    app.run(host='0.0.0.0', port=config.PORT, debug=config.DEBUG, use_reloader=True)
