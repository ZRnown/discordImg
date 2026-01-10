from flask import Flask, request, jsonify, Response
import numpy as np
import os
import logging
import sys
from datetime import datetime
from feature_extractor import get_feature_extractor, DINOv2FeatureExtractor
from database import db
from config import config
import requests
import json
from flask_cors import CORS
import queue
import threading
import time
from urllib.parse import quote

# 在应用启动时从数据库加载系统配置
def load_system_config():
    """从数据库加载系统配置到内存"""
    # 在函数内部定义logger，因为此时全局logger可能还没有初始化
    import logging
    func_logger = logging.getLogger(__name__)

    try:
        sys_config = db.get_system_config()
        config.DOWNLOAD_THREADS = sys_config['download_threads']
        config.FEATURE_EXTRACT_THREADS = sys_config['feature_extract_threads']
        config.DISCORD_SIMILARITY_THRESHOLD = sys_config['discord_similarity_threshold']
        config.DISCORD_CHANNEL_ID = sys_config['discord_channel_id']
        config.CNFANS_CHANNEL_ID = sys_config['cnfans_channel_id']
        config.ACBUY_CHANNEL_ID = sys_config['acbuy_channel_id']

        # 加载全局回复延迟配置
        reply_config = db.get_global_reply_config()
        config.GLOBAL_REPLY_MIN_DELAY = reply_config['min_delay']
        config.GLOBAL_REPLY_MAX_DELAY = reply_config['max_delay']

        # 设置环境变量（供机器人使用）
        discord_channel_id = sys_config['discord_channel_id']
        if discord_channel_id:
            os.environ['DISCORD_CHANNEL_ID'] = discord_channel_id

        func_logger.info("系统配置已从数据库加载")
        func_logger.info(f"下载线程: {config.DOWNLOAD_THREADS}")
        func_logger.info(f"特征提取线程: {config.FEATURE_EXTRACT_THREADS}")
        func_logger.info(f"Discord相似度阈值: {config.DISCORD_SIMILARITY_THRESHOLD} ({config.DISCORD_SIMILARITY_THRESHOLD*100:.0f}%)")
        func_logger.info(f"全局回复延迟设置为: {config.GLOBAL_REPLY_MIN_DELAY}-{config.GLOBAL_REPLY_MAX_DELAY}秒")
        func_logger.info(f"Discord频道ID: {discord_channel_id or '未设置(监听所有频道)'}")
    except Exception as e:
        func_logger.warning(f"加载系统配置失败，使用默认值: {e}")

# 加载系统配置
load_system_config()

# 配置日志
logging.basicConfig(level=logging.INFO)

# 创建日志队列用于实时流式传输
log_queue = queue.Queue()
log_clients = []

# 存储所有日志的列表，用于API查询
all_logs = []

class QueueHandler(logging.Handler):
    """自定义日志处理器，将日志发送到队列"""
    def emit(self, record):
        try:
            # 过滤掉HTTP请求日志和不重要的系统日志
            if self._should_filter_log(record):
                return

            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'level': record.levelname,
                'message': self.format(record),
                'module': record.module,
                'func': record.funcName
            }

            # 添加到日志列表（限制大小）
            all_logs.append(log_entry)
            if len(all_logs) > 200:  # 最多保存200条日志
                all_logs.pop(0)

            log_queue.put(log_entry)

            # 通知所有连接的客户端
            for client_queue in log_clients[:]:  # 复制列表以避免修改时的问题
                try:
                    client_queue.put(log_entry)
                except:
                    # 如果客户端队列已满或断开，移除它
                    if client_queue in log_clients:
                        log_clients.remove(client_queue)
        except Exception as e:
            print(f"日志队列错误: {e}")

    def _should_filter_log(self, record):
        """判断是否应该过滤掉这条日志"""
        # 过滤Werkzeug的HTTP请求日志
        if record.module == '_internal':
            return True

        # 过滤包含HTTP请求模式的日志
        message = self.format(record)
        if any(pattern in message for pattern in [
            '"GET ', '"POST ', '"PUT ', '"DELETE ',
            'HTTP/1.1"', 'HTTP/1.0"',
            'werkzeug',
            '127.0.0.1 - -',  # 过滤访问日志
        ]):
            return True

        # 过滤一些不重要的系统日志
        if record.module in ['urllib3', 'requests', 'aiohttp']:
            return True

        # 对于未知模块，只显示WARNING级别以上的日志
        if record.levelno < logging.WARNING and record.module not in [
            '__main__',  # 主程序日志
            'app',       # Flask应用日志
            'database',  # 数据库操作日志
            'bot',       # Discord机器人日志
            'weidian_scraper',  # 微店爬虫日志
            'feature_extractor', # 特征提取日志
            'vector_engine',      # 向量引擎日志
            'migrate_data',       # 数据迁移日志
            'test_search_debug'   # 测试脚本日志
        ]:
            return True

        return False

# 创建队列处理器并添加到根日志器
queue_handler = QueueHandler()
queue_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(queue_handler)

# 设置其他日志器的级别
logging.getLogger('werkzeug').setLevel(logging.WARNING)  # 只显示警告和错误
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 机器人相关变量
bot_clients = []
bot_tasks = []

# AI模型预加载变量
feature_extractor = None

# 预加载AI模型和向量引擎
def preload_ai_models():
    """在应用启动时预加载AI模型和向量引擎，避免每次操作都重新初始化"""
    global feature_extractor
    # 在这个阶段logger可能还没初始化，使用print
    try:
        print("🚀 开始预加载AI模型...")
        feature_extractor = DINOv2FeatureExtractor()
        print("✅ AI模型预加载完成")

        print("🚀 开始预加载FAISS向量引擎...")
        from vector_engine import get_vector_engine
        vector_engine = get_vector_engine()
        print("✅ FAISS向量引擎预加载完成")
    except Exception as e:
        print(f"❌ 预加载失败: {e}")
        feature_extractor = None

preload_ai_models()

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000"], supports_credentials=True)

def extract_features(image_path):
    """使用预加载的深度学习模型提取图像特征"""
    global feature_extractor
    try:
        if feature_extractor is None:
            logger.error("AI模型未预加载，无法提取特征")
            return None

        features = feature_extractor.extract_feature(image_path)
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
    """搜索相似图像 - 使用 FAISS HNSW"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        image_file = request.files['image']
        threshold = float(request.form.get('threshold', 0.6))  # DINOv2需要更高的阈值
        limit = int(request.form.get('limit', 5))  # 返回结果数量，默认5个

        # 调试信息
        print(f"DEBUG: Received threshold: {threshold}")
        print(f"DEBUG: Form data: {list(request.form.keys())}")

        # 保存查询图片到临时文件
        import uuid
        temp_filename = f"{uuid.uuid4()}.jpg"
        image_path = f"/tmp/{temp_filename}"
        image_file.save(image_path)

        try:
            # 提取特征 (使用 DINOv2 + YOLOv8)
            query_features = extract_features(image_path)

            if query_features is None:
                return jsonify({'error': 'Feature extraction failed'}), 500

            # 使用 FAISS HNSW 向量搜索
            print(f"DEBUG: Searching with threshold: {threshold}, vector length: {len(query_features)}")
            # 临时将阈值设为0，确保能返回结果进行调试
            debug_threshold = max(0.0, threshold)  # 确保不为负数
            results = db.search_similar_images(query_features, limit=limit, threshold=debug_threshold)
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
                # 处理多个搜索结果
                processed_results = []
                for i, result in enumerate(results):
                    # 获取完整产品信息
                    product_info = db._get_product_info_by_id(result['id'])

                    result_data = {
                        'rank': i + 1,
                        'similarity': float(result['similarity']),
                        'imageIndex': result['image_index'],
                        'matchedImage': f"/api/image/{result['id']}/{result['image_index']}",
                        'product': {
                            'id': result['id'],
                            'title': product_info['title'] if product_info else result.get('title', ''),
                            'englishTitle': product_info.get('english_title', ''),
                            'weidianUrl': product_info['product_url'] if product_info else result.get('product_url', ''),
                            'cnfansUrl': product_info.get('cnfans_url', ''),
                            'ruleEnabled': product_info.get('ruleEnabled', True) if product_info else True,
                            'images': [f"/api/image/{result['id']}/{j}" for j in range(10)]  # 预估图片数量
                        }
                    }
                    processed_results.append(result_data)

                # 保存最佳匹配的搜索历史
                if processed_results:
                    best_match = processed_results[0]
                    db.add_search_history(
                        query_image_path=image_path,
                        matched_product_id=best_match['product']['id'],
                        matched_image_index=best_match['imageIndex'],
                        similarity=best_match['similarity'],
                        threshold=threshold
                    )

                response_data = {
                    'success': True,
                    'results': processed_results,
                    'totalResults': len(processed_results),
                    'searchTime': datetime.now().isoformat(),
                    'debugInfo': {
                        'totalIndexedImages': db.get_total_indexed_images(),
                        'threshold': threshold,
                        'limit': limit,
                        'searchedVectors': len(results) if results else 0
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
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400

        # 支持两种输入方式：完整URL或商品ID
        url = data.get('url')
        weidian_id = data.get('weidianId')

        if not url and not weidian_id:
            return jsonify({'error': 'URL or weidianId is required'}), 400

        # 如果提供了weidianId，构造URL
        if weidian_id and not url:
            url = f"https://weidian.com/item.html?itemID={weidian_id}"

        # 验证URL格式
        if 'weidian.com' not in url:
            return jsonify({'error': '只支持微店商品链接'}), 400

        logger.info(f"开始抓取商品: {url}")

        # 检查商品是否已存在
        existing = db.get_product_by_url(url)
        if existing:
            return jsonify({'error': '商品已存在', 'existing': True}), 409

        # 使用真正的爬虫
        from weidian_scraper import get_weidian_scraper
        scraper = get_weidian_scraper()

        # 抓取商品信息
        product_info = scraper.scrape_product_info(url)

        if not product_info:
            return jsonify({'error': '商品信息抓取失败，请检查URL是否正确'}), 500

        # 生成acbuy链接
        acbuy_url = ''
        if product_info['weidian_url']:
            # 从weidian_url中提取itemID
            import re
            item_id_match = re.search(r'itemID=(\d+)', product_info['weidian_url'])
            if item_id_match:
                item_id = item_id_match.group(1)
                # 构建acbuy链接
                encoded_url = product_info['weidian_url'].replace(':', '%3A').replace('/', '%2F').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
                acbuy_url = f'https://www.acbuy.com/product?url={encoded_url}&id={item_id}&source=WD'

        # 保存到数据库（使用全局延迟配置）
        product_id = db.insert_product({
            'product_url': product_info['weidian_url'],
            'title': product_info['title'],
            'description': product_info['description'],
            'english_title': product_info.get('english_title') or '',
            'cnfans_url': product_info.get('cnfans_url') or '',
            'acbuy_url': acbuy_url,
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
            # 为每张图片建立向量索引
            # 注意：YOLO裁剪已集成在DINOv2特征提取过程中，无需额外步骤
            # 使用预加载的全局特征提取器
            global feature_extractor
            if feature_extractor is None:
                logger.error("AI模型未预加载，使用单例模式")
                from feature_extractor import get_feature_extractor
                extractor = get_feature_extractor()
            else:
                logger.info("使用预加载的AI模型")
                extractor = feature_extractor

            # 串行建立向量索引 (SQLite不支持多线程写入)
            # 但先使用多线程进行特征提取，然后串行插入数据库
            import concurrent.futures
            from vector_engine import get_vector_engine
            engine = get_vector_engine()

            def extract_features_only(img_path):
                """只提取特征，不插入数据库"""
                try:
                    features = extractor.extract_feature(img_path)
                    return features
                except Exception as e:
                    logger.error(f"特征提取失败 {img_path}: {e}")
                    return None

            # 第一步：多线程特征提取
            logger.info("开始多线程特征提取...")
            features_list = []
            max_workers = min(config.FEATURE_EXTRACT_THREADS, len(saved_image_paths))

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交特征提取任务
                future_to_image = {
                    executor.submit(extract_features_only, img_path): (i, img_path)
                    for i, img_path in enumerate(saved_image_paths)
                }

                # 收集特征提取结果
                for future in concurrent.futures.as_completed(future_to_image):
                    i, img_path = future_to_image[future]
                    try:
                        features = future.result()
                        features_list.append((i, img_path, features))
                    except Exception as e:
                        logger.error(f"特征提取异常 {img_path}: {e}")
                        features_list.append((i, img_path, None))

            # 按索引排序结果
            features_list.sort(key=lambda x: x[0])

            # 第二步：串行插入数据库和FAISS索引
            logger.info("开始串行数据库插入和索引建立...")
            indexed_images = []

            for i, img_path, features in features_list:
                try:
                    if features is None:
                        logger.error(f"跳过图片 {i}: 特征提取失败")
                        continue

                    # 插入数据库记录
                    image_db_id = db.insert_image_record(product_id, img_path, i)
                    if not image_db_id:
                        logger.error(f"图片 {i} 元数据插入失败")
                        continue

                    # 插入FAISS向量索引
                    success = engine.add_vector(image_db_id, features)
                    if success:
                        indexed_images.append(f"{i}.jpg")
                        logger.info(f"图片 {i} 索引建立成功")
                    else:
                        logger.error(f"图片 {i} 索引建立失败")

                except Exception as e:
                    logger.error(f"处理图片 {i} 时出错: {e}")
                    continue

            # 检查是否有图片处理失败
            if len(indexed_images) != len(saved_image_paths):
                failed_count = len(saved_image_paths) - len(indexed_images)
                logger.warning(f"有 {failed_count} 张图片处理失败，但继续执行")

            # 如果一张图片都没成功，认为是错误
            if not indexed_images:
                logger.error("所有图片处理都失败了")
                try:
                    db.delete_product_images(product_id)
                except Exception as del_e:
                    logger.error(f"回滚删除失败: {del_e}")
                return jsonify({'error': 'All image processing failed'}), 500

            # 实时保存FAISS索引
            engine.save()

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
                SELECT id, username, token, status, last_active, created_at, updated_at
                FROM discord_accounts
                ORDER BY created_at DESC
            """)
            accounts = []
            for row in cursor.fetchall():
                accounts.append({
                    'id': row[0],
                    'username': row[1],
                    'token': row[2],
                    'status': row[3],
                    'lastActive': row[4],
                    'createdAt': row[5]
                })
        return jsonify({'accounts': accounts})
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
                prod['acbuyUrl'] = prod.get('acbuy_url') or prod.get('acbuyUrl') or ''
                prod['createdAt'] = prod.get('created_at') or prod.get('createdAt')
                # 移除商品级别延迟，使用全局延迟
                prod.pop('min_delay', None)
                prod.pop('max_delay', None)
                # 映射ruleEnabled到autoReplyEnabled以兼容前端
                prod['autoReplyEnabled'] = prod.get('ruleEnabled', True)
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


@app.route('/api/rebuild_index', methods=['POST'])
def rebuild_index():
    """重建FAISS索引，清理被删除的向量"""
    try:
        from vector_engine import get_vector_engine
        from feature_extractor import get_feature_extractor

        logger.info("开始重建FAISS索引...")

        # 获取所有有效的图片记录（确保图片文件存在）
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pi.id, pi.product_id, pi.image_path, pi.image_index
                FROM product_images pi
                JOIN products p ON pi.product_id = p.id
                ORDER BY pi.id
            """)
            all_records = cursor.fetchall()

        # 过滤出文件存在的记录
        image_records = []
        for record in all_records:
            if os.path.exists(record['image_path']):
                image_records.append(record)
            else:
                logger.warning(f"图片文件不存在，跳过: {record['image_path']}")

        if not image_records:
            return jsonify({'error': '没有找到图片记录'}), 400

        logger.info(f"找到 {len(image_records)} 张图片记录")

        # 重新提取特征并重建索引
        extractor = get_feature_extractor()
        engine = get_vector_engine()

        # 创建新索引
        vectors_data = []
        for record in image_records:
            try:
                image_path = record['image_path']
                if not os.path.exists(image_path):
                    logger.warning(f"图片文件不存在: {image_path}")
                    continue

                # 提取特征
                features = extractor.extract_feature(image_path)
                if features is not None:
                    vectors_data.append((record['id'], features))
                    logger.info(f"重新提取特征: {record['id']}")
                else:
                    logger.warning(f"特征提取失败: {image_path}")

            except Exception as e:
                logger.error(f"处理图片 {record['id']} 失败: {e}")
                continue

        # 重建索引
        success = engine.rebuild_index(vectors_data)
        if success:
            logger.info(f"索引重建完成，包含 {len(vectors_data)} 个向量")
            return jsonify({
                'success': True,
                'message': f'索引重建完成，包含 {len(vectors_data)} 个有效向量',
                'total_vectors': len(vectors_data)
            })
        else:
            return jsonify({'error': '索引重建失败'}), 500

    except Exception as e:
        logger.error(f"重建索引失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rebuild_vectors', methods=['POST'])
def rebuild_vectors():
    """为已有商品（或缺失向量的图片）重建特征并插入 FAISS"""
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

def verify_discord_token(token):
    """验证Discord token并获取用户信息"""
    try:
        headers = {
            'Authorization': f'Bot {token}' if token.startswith('Bot ') else token,
            'User-Agent': 'DiscordBot/1.0'
        }

        # 首先尝试作为Bot token验证
        response = requests.get('https://discord.com/api/v10/users/@me', headers=headers, timeout=10)

        if response.status_code == 401:
            # 如果Bot token失败，尝试作为User token
            if not token.startswith('Bot '):
                headers['Authorization'] = f'Bot {token}'
                response = requests.get('https://discord.com/api/v10/users/@me', headers=headers, timeout=10)

        if response.status_code == 200:
            user_data = response.json()
            return {
                'valid': True,
                'username': f"{user_data.get('username', 'Unknown')}#{user_data.get('discriminator', '0000')}",
                'user_id': user_data.get('id'),
                'avatar': user_data.get('avatar'),
                'bot': user_data.get('bot', False)
            }
        else:
            return {
                'valid': False,
                'error': f'HTTP {response.status_code}: {response.text}'
            }
    except requests.exceptions.RequestException as e:
        return {
            'valid': False,
            'error': f'网络错误: {str(e)}'
        }
    except Exception as e:
        return {
            'valid': False,
            'error': f'验证失败: {str(e)}'
        }

@app.route('/api/accounts', methods=['POST'])
def add_account():
    """添加新的 Discord 账号"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400
        token = data.get('token')
        username = data.get('username', '')

        if not token:
            return jsonify({'error': 'Token is required'}), 400

        # 验证token并获取真实用户名
        logger.info("正在验证Discord token...")
        token_info = verify_discord_token(token)

        if not token_info['valid']:
            return jsonify({'error': f'Token验证失败: {token_info["error"]} 请检查token是否正确'}), 400

        # 如果没有提供用户名，使用从token获取的用户名
        if not username:
            username = token_info['username']
            logger.info(f"自动获取用户名: {username}")

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO discord_accounts (username, token, status)
                VALUES (?, ?, 'offline')
            """, (username, token))
            account_id = cursor.lastrowid

            cursor.execute("SELECT id, username, token, status, last_active FROM discord_accounts WHERE id = ?", (account_id,))
            account = cursor.fetchone()
            conn.commit()

        logger.info(f"账号添加成功: {username}")
        return jsonify({
            'id': account[0],
            'username': account[1],
            'token': account[2],
            'status': account[3],
            'lastActive': account[4],
            'verified': True
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
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400
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

@app.route('/api/accounts/current', methods=['GET'])
def get_current_account():
    """获取当前可用的 Discord 账号 (状态为online的第一个)"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, token, status, last_active
                FROM discord_accounts
                WHERE status = 'online'
                ORDER BY last_active DESC NULLS LAST, created_at ASC
                LIMIT 1
            """)
            account = cursor.fetchone()

            if account:
                return jsonify({
                    'id': account[0],
                    'username': account[1],
                    'token': account[2],
                    'status': account[3],
                    'lastActive': account[4]
                })
            else:
                return jsonify({'error': 'No active account found'}), 404
    except Exception as e:
        logger.error(f"获取当前账号失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/verify-all', methods=['POST'])
def verify_all_accounts():
    """重新验证所有账号"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 获取所有账号
            cursor.execute("SELECT id, username, token FROM discord_accounts")
            accounts = cursor.fetchall()

            verified_count = 0
            invalid_count = 0
            results = []

            for account in accounts:
                account_id, username, token = account
                logger.info(f"正在验证账号: {username}")

                token_info = verify_discord_token(token)

                if token_info['valid']:
                    # 更新用户名（如果有变化）
                    new_username = token_info['username']
                    if new_username != username:
                        cursor.execute("""
                            UPDATE discord_accounts
                            SET username = ?
                            WHERE id = ?
                        """, (new_username, account_id))
                        logger.info(f"用户名已更新: {username} -> {new_username}")

                    verified_count += 1
                    results.append({
                        'id': account_id,
                        'username': new_username,
                        'valid': True
                    })
                else:
                    invalid_count += 1
                    results.append({
                        'id': account_id,
                        'username': username,
                        'valid': False,
                        'error': token_info['error']
                    })

            conn.commit()

        return jsonify({
            'success': True,
            'total': len(accounts),
            'verified': verified_count,
            'invalid': invalid_count,
            'results': results
        })
    except Exception as e:
        logger.error(f"批量验证账号失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/bulk-status', methods=['POST'])
def bulk_update_status():
    """批量开启或停止所有账号"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400

        new_status = data.get('status')
        if new_status not in ['online', 'offline']:
            return jsonify({'error': 'Invalid status. Must be "online" or "offline"'}), 400

        with db.get_connection() as conn:
            cursor = conn.cursor()

            if new_status == 'online':
                cursor.execute("""
                    UPDATE discord_accounts
                    SET status = 'online', last_active = ?
                """, (datetime.now(),))
            else:
                cursor.execute("""
                    UPDATE discord_accounts
                    SET status = 'offline'
                """)

            updated_count = cursor.rowcount
            conn.commit()

        logger.info(f"批量更新账号状态: {updated_count} 个账号设置为 {new_status}")

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'new_status': new_status
        })
    except Exception as e:
        logger.error(f"批量更新账号状态失败: {e}")
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
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400
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

@app.route('/api/products/<int:product_id>/images/<int:image_index>', methods=['DELETE'])
def delete_product_image(product_id, image_index):
    """删除商品的单个图片"""
    try:
        # 获取商品信息
        product = db.get_product_by_id(product_id)
        if not product:
            return jsonify({'error': '商品不存在'}), 404

        images = product.get('images', [])
        if image_index < 0 or image_index >= len(images):
            return jsonify({'error': '图片索引无效'}), 400

        # 删除指定的图片
        removed_image = images.pop(image_index)

        # 更新数据库
        db.update_product_images(product_id, images)

        # 如果启用了规则，重新建立向量索引
        if product.get('rule_enabled', False):
            try:
                from weidian_scraper import get_weidian_scraper
                scraper = get_weidian_scraper()
                # 重新处理商品以更新向量索引
                updated_product = scraper.scrape_product_info(product['weidian_url'])
                if updated_product and updated_product.get('images'):
                    db.update_product_images(product_id, updated_product['images'])
            except Exception as e:
                logger.warning(f"重新建立向量索引失败: {e}")

        return jsonify({'success': True, 'message': f'图片已删除', 'removed_image': removed_image})
    except Exception as e:
        logger.error(f"删除图片失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/discord-threshold', methods=['GET'])
def get_discord_threshold():
    """获取Discord相似度阈值"""
    try:
        sys_config = db.get_system_config()
        threshold = sys_config['discord_similarity_threshold']
        return jsonify({
            'threshold': threshold,
            'threshold_percentage': threshold * 100
        })
    except Exception as e:
        logger.error(f"获取Discord阈值失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/discord-threshold', methods=['POST'])
def update_discord_threshold():
    """更新Discord相似度阈值"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400
        threshold = float(data.get('threshold', 0.4))

        # 验证范围
        if not (0.0 <= threshold <= 1.0):
            return jsonify({'error': '阈值必须在0.0-1.0之间'}), 400

        # 保存到数据库
        if db.update_system_config(discord_similarity_threshold=threshold):
            # 同时更新内存中的配置
            config.DISCORD_SIMILARITY_THRESHOLD = threshold
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

@app.route('/api/debug/faiss_status', methods=['GET'])
def get_faiss_status():
    """获取FAISS向量数据库状态"""
    try:
        from vector_engine import get_vector_engine
        engine = get_vector_engine()
        stats = engine.get_stats()

        # 尝试搜索一个测试向量
        test_vector = np.zeros(config.VECTOR_DIMENSION, dtype='float32')
        test_results = engine.search(test_vector, top_k=1)

        return jsonify({
            'index_exists': True,
            'entity_count': stats['total_vectors'],
            'test_search_works': len(test_results) > 0,
            'vector_dimension': config.VECTOR_DIMENSION,
            'index_type': stats['index_type'],
            'metric_type': stats['metric_type'],
            'memory_usage_mb': stats['memory_usage_mb'],
            'ef_construction': stats['ef_construction'],
            'ef_search': stats['ef_search']
        })
    except Exception as e:
        logger.error(f"获取FAISS状态失败: {e}")
        return jsonify({
            'error': str(e),
            'index_exists': False,
            'entity_count': 0
        }), 500

@app.route('/api/config/threads', methods=['GET'])
def get_thread_config():
    """获取线程配置"""
    try:
        sys_config = db.get_system_config()
        return jsonify({
            'download_threads': sys_config['download_threads'],
            'feature_extract_threads': sys_config['feature_extract_threads']
        })
    except Exception as e:
        logger.error(f"获取线程配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/threads', methods=['POST'])
def update_thread_config():
    """更新线程配置"""
    try:
        data = request.get_json()
        download_threads = data.get('download_threads')
        feature_extract_threads = data.get('feature_extract_threads')

        # 验证参数
        if download_threads is not None and not (1 <= download_threads <= 8):
            return jsonify({'error': '下载线程数必须在1-8之间'}), 400
        if feature_extract_threads is not None and not (1 <= feature_extract_threads <= 8):
            return jsonify({'error': '特征提取线程数必须在1-8之间'}), 400

        # 保存到数据库
        if db.update_system_config(download_threads=download_threads, feature_extract_threads=feature_extract_threads):
            # 同时更新内存中的配置
            sys_config = db.get_system_config()
            config.DOWNLOAD_THREADS = sys_config['download_threads']
            config.FEATURE_EXTRACT_THREADS = sys_config['feature_extract_threads']

            return jsonify({
                'success': True,
                'download_threads': config.DOWNLOAD_THREADS,
                'feature_extract_threads': config.FEATURE_EXTRACT_THREADS
            })
        else:
            return jsonify({'error': '保存失败'}), 500
    except Exception as e:
        logger.error(f"更新线程配置失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/global-reply-delay', methods=['POST'])
def update_global_reply_delay():
    """更新全局回复延迟配置"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400
        min_delay = float(data.get('min_delay', 3))
        max_delay = float(data.get('max_delay', 8))

        # 验证范围
        if min_delay < 0 or max_delay < 0:
            return jsonify({'error': '延迟时间不能为负数'}), 400
        if min_delay > max_delay:
            return jsonify({'error': '最小延迟不能大于最大延迟'}), 400
        if max_delay > 300:
            return jsonify({'error': '最大延迟不能超过300秒'}), 400

        # 保存到数据库
        if db.update_global_reply_config(min_delay, max_delay):
            # 同时更新内存中的配置
            config.GLOBAL_REPLY_MIN_DELAY = min_delay
            config.GLOBAL_REPLY_MAX_DELAY = max_delay

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

@app.route('/api/config/discord-channel', methods=['GET'])
def get_discord_channel():
    """获取Discord频道配置"""
    try:
        sys_config = db.get_system_config()
        return jsonify({
            'channel_id': sys_config['discord_channel_id'],
            'cnfans_channel_id': sys_config['cnfans_channel_id'],
            'acbuy_channel_id': sys_config['acbuy_channel_id']
        })
    except Exception as e:
        logger.error(f"获取Discord频道配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/discord-channel', methods=['POST'])
def update_discord_channel():
    """更新Discord频道配置"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400

        channel_id = data.get('channel_id', '').strip()
        cnfans_channel_id = data.get('cnfans_channel_id', '').strip()
        acbuy_channel_id = data.get('acbuy_channel_id', '').strip()

        # 验证频道ID格式（应该是数字）
        for cid_name, cid_value in [('channel_id', channel_id), ('cnfans_channel_id', cnfans_channel_id), ('acbuy_channel_id', acbuy_channel_id)]:
            if cid_value and not cid_value.isdigit():
                return jsonify({'error': f'{cid_name} 必须是数字'}), 400

        # 保存到数据库
        if db.update_system_config(
            discord_channel_id=channel_id,
            cnfans_channel_id=cnfans_channel_id,
            acbuy_channel_id=acbuy_channel_id
        ):
            # 同时更新环境变量和bot_config
            if channel_id:
                os.environ['DISCORD_CHANNEL_ID'] = channel_id
                import bot_config
                bot_config.config.DISCORD_CHANNEL_ID = int(channel_id)
                logger.info(f"Discord频道ID设置为: {channel_id}")
            else:
                os.environ.pop('DISCORD_CHANNEL_ID', None)
                import bot_config
                bot_config.config.DISCORD_CHANNEL_ID = 0
                logger.info("Discord频道ID已清除")

            return jsonify({
                'success': True,
                'channel_id': channel_id,
                'message': f'Discord频道ID已设置为: {channel_id or "无(监听所有频道)"}'
            })
        else:
            return jsonify({'error': '保存失败'}), 500
    except Exception as e:
        logger.error(f"更新Discord频道配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_history', methods=['GET'])
def get_search_history():
    """获取搜索历史记录（支持分页）"""
    try:
        limit = min(int(request.args.get('limit', 20)), 100)  # 最多100条
        offset = max(int(request.args.get('offset', 0)), 0)
        page = max(int(request.args.get('page', 1)), 1)

        # 如果提供了page参数，计算offset
        if 'page' in request.args and 'offset' not in request.args:
            offset = (page - 1) * limit

        result = db.get_search_history(limit, offset)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取搜索历史失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_similar_text', methods=['POST'])
def search_similar_text():
    """根据文字关键词搜索相似商品"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request body'}), 400

        query = data.get('query', '').strip()
        limit = min(int(data.get('limit', 5)), 20)  # 最多20个结果

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        logger.info(f'文字搜索请求: "{query}", 限制: {limit}')

        # 在数据库中搜索包含关键词的商品
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 使用LIKE查询在标题和英文标题中搜索
            cursor.execute("""
                SELECT id, product_url, title, english_title, description,
                       ruleEnabled, min_delay, max_delay, created_at,
                       cnfans_url
                FROM products
                WHERE (title LIKE ? OR english_title LIKE ? OR description LIKE ?)
                  AND ruleEnabled = 1
                ORDER BY created_at DESC
                LIMIT ?
            """, (f'%{query}%', f'%{query}%', f'%{query}%', limit))

            rows = cursor.fetchall()

            products = []
            for row in rows:
                prod = dict(row)
                # 获取图片
                cursor.execute("SELECT image_path FROM product_images WHERE product_id = ? ORDER BY image_index LIMIT 1", (prod['id'],))
                img_row = cursor.fetchone()
                if img_row:
                    prod['image'] = f"/api/image/{prod['id']}/0"
                else:
                    prod['image'] = None

                # 格式化字段
                prod['weidianUrl'] = prod.get('product_url')
                prod['englishTitle'] = prod.get('english_title') or ''
                prod['cnfansUrl'] = prod.get('cnfans_url') or ''
                prod['autoReplyEnabled'] = prod.get('ruleEnabled', True)
                # 从URL中提取weidian ID
                try:
                    import re
                    m = re.search(r'itemID=(\d+)', prod.get('product_url') or '')
                    prod['weidianId'] = m.group(1) if m else ''
                except:
                    prod['weidianId'] = ''

                products.append(prod)

        logger.info(f'文字搜索完成，找到 {len(products)} 个商品')

        return jsonify({
            'success': True,
            'query': query,
            'products': products,
            'total': len(products)
        })

    except Exception as e:
        logger.error(f"文字搜索失败: {e}")
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

@app.route('/api/logs/stream')
def log_stream():
    """Server-Sent Events 日志流"""
    import json

    def generate():
        # 为这个客户端创建队列
        client_queue = queue.Queue(maxsize=100)  # 限制队列大小
        log_clients.append(client_queue)

        try:
            # 发送最近的日志历史
            for log_entry in all_logs[-20:]:  # 发送最近20条历史日志
                yield f"data: {json.dumps(log_entry)}\n\n"

            # 持续监听新日志
            while True:
                try:
                    # 等待新日志，超时时间设为30秒
                    log_entry = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(log_entry)}\n\n"
                except queue.Empty:
                    # 发送心跳包保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"

        except GeneratorExit:
            # 客户端断开连接
            pass
        finally:
            # 清理客户端队列
            if client_queue in log_clients:
                log_clients.remove(client_queue)

    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache',
                           'Access-Control-Allow-Origin': '*',
                           'Access-Control-Allow-Headers': 'Cache-Control'})

@app.route('/api/logs/recent')
def get_recent_logs():
    """获取最近的日志记录"""
    try:
        # 从日志列表中返回最近50条日志
        return jsonify({
            'logs': all_logs[-50:],
            'total': len(all_logs)
        })
    except Exception as e:
        logger.error(f"获取最近日志失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/add', methods=['POST'])
def add_external_log():
    """接收外部进程发送的日志"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid log data'}), 400

        # 创建日志条目
        log_entry = {
            'timestamp': data.get('timestamp', datetime.now().isoformat()),
            'level': data.get('level', 'INFO'),
            'message': data.get('message', ''),
            'module': data.get('module', 'external'),
            'func': data.get('func', '')
        }

        # 添加到日志列表
        all_logs.append(log_entry)
        if len(all_logs) > 200:
            all_logs.pop(0)

        # 添加到队列
        log_queue.put(log_entry)

        return jsonify({'success': True})
    except Exception as e:
        print(f"添加外部日志失败: {e}")
        return jsonify({'error': str(e)}), 500

def start_discord_bot():
    """启动Discord机器人 - 支持多账号"""
    global bot_clients, bot_tasks

    try:
        import asyncio
        from bot import DiscordBotClient, get_all_accounts_from_backend

        logger.info("正在启动Discord机器人...")

        # 获取所有账号
        accounts = asyncio.run(get_all_accounts_from_backend())
        if not accounts:
            logger.warning("没有找到可用的Discord账号")
            return

        logger.info(f"找到 {len(accounts)} 个Discord账号，开始启动机器人...")

        # 在新的事件循环中运行机器人
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 为每个账号创建机器人实例
        for account in accounts:
            account_id = account['id']
            token = account['token']
            username = account.get('username', f'account_{account_id}')

            logger.info(f"正在启动机器人账号: {username}")

            # 创建机器人实例
            client = DiscordBotClient(account_id=account_id)

            # 启动机器人
            try:
                task = loop.create_task(client.start(token, reconnect=True))
                bot_clients.append(client)
                bot_tasks.append(task)
                logger.info(f"Discord机器人启动成功: {username}")
            except Exception as e:
                logger.error(f"启动机器人失败 {username}: {e}")

        # 在后台线程中运行事件循环
        import threading
        bot_thread = threading.Thread(target=loop.run_forever, daemon=True)
        bot_thread.start()

        logger.info(f"共启动了 {len(bot_clients)} 个Discord机器人")

    except ImportError as e:
        logger.warning(f"Discord机器人模块不可用: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")

def stop_discord_bot():
    """停止Discord机器人"""
    global bot_clients, bot_tasks

    if bot_clients:
        logger.info(f"正在停止 {len(bot_clients)} 个Discord机器人...")
        try:
            import asyncio
            # 创建任务来停止所有机器人
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            for i, client in enumerate(bot_clients):
                try:
                    if client and not client.is_closed():
                        loop.run_until_complete(client.close())
                        logger.info(f"Discord机器人 {i+1} 已停止")
                except Exception as e:
                    logger.error(f"停止机器人 {i+1} 时出错: {e}")

            logger.info("所有Discord机器人已停止")
        except Exception as e:
            logger.error(f"停止机器人时出错: {e}")

    # 取消所有任务
    for task in bot_tasks:
        if task and not task.done():
            task.cancel()

@app.route('/api/shop-info', methods=['GET'])
def get_shop_info():
    """获取店铺信息"""
    try:
        shop_id = request.args.get('shopId')
        if not shop_id:
            return jsonify({'error': '缺少shopId参数'}), 400

        shop_id = shop_id.strip()
        if not shop_id.isdigit():
            return jsonify({'error': 'shopId必须是数字'}), 400

        logger.info(f'获取店铺信息: {shop_id}')

        # 调用微店API获取店铺信息
        try:
            param = json.dumps({"shop_id": shop_id, "page_id": 0})
            encoded_param = quote(param)

            api_url = f"https://thor.weidian.com/decorate/customSharePage.getPageInfo/1.0?param={encoded_param}&wdtoken=8ea9315c&_={int(time.time() * 1000)}"

            response = requests.get(api_url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'Origin': 'https://weidian.com',
                'Referer': 'https://weidian.com/',
                'Sec-Ch-Ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site',
            }, cookies={
                'wdtoken': '8ea9315c',
                '__spider__visitorid': '0dcf6a5b878847ec',
                'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                'v-components/cpn-coupon-dialog@nologinshop': '10',
                '__spider__sessionid': 'e55c6458ac1fdba4'
            }, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get('status', {}).get('code') == 0:
                    shop_name = data.get('result', {}).get('shareTitle', f'店铺 {shop_id}')
                    return jsonify({'shopName': shop_name})
                else:
                    logger.warning(f'API返回错误状态: {data}')
            else:
                logger.warning(f'API请求失败: {response.status_code}')

        except Exception as e:
            logger.error(f'获取店铺信息失败: {e}')

        # 如果API失败，返回默认名称
        return jsonify({'shopName': f'店铺 {shop_id}'})

    except Exception as e:
        logger.error(f'获取店铺信息出错: {e}')
        return jsonify({'error': '获取店铺信息失败'}), 500

# ===== 店铺管理API =====

@app.route('/api/shops', methods=['GET'])
def get_shops():
    """获取所有店铺列表"""
    try:
        shops = db.get_all_shops()
        return jsonify({'shops': shops})
    except Exception as e:
        logger.error(f'获取店铺列表失败: {e}')
        return jsonify({'error': '获取店铺列表失败'}), 500

@app.route('/api/shops', methods=['POST'])
def add_shop():
    """添加新店铺"""
    try:
        data = request.get_json()
        if not data or not data.get('shopId') or not data.get('name'):
            return jsonify({'error': '缺少shopId或name参数'}), 400

        shop_id = data['shopId'].strip()
        name = data['name'].strip()

        if not shop_id.isdigit():
            return jsonify({'error': 'shopId必须是数字'}), 400

        # 获取真实的店铺名称
        shop_info = get_shop_info_from_api(shop_id)
        if shop_info and shop_info.get('shopName'):
            name = shop_info['shopName']

        if db.add_shop(shop_id, name):
            return jsonify({'success': True, 'message': '店铺添加成功'})
        else:
            return jsonify({'error': '店铺已存在或添加失败'}), 400
    except Exception as e:
        logger.error(f'添加店铺失败: {e}')
        return jsonify({'error': '添加店铺失败'}), 500

@app.route('/api/shops/<shop_id>', methods=['DELETE'])
def delete_shop(shop_id):
    """删除店铺"""
    try:
        if db.delete_shop(shop_id):
            return jsonify({'success': True, 'message': '店铺删除成功'})
        else:
            return jsonify({'error': '店铺不存在或删除失败'}), 404
    except Exception as e:
        logger.error(f'删除店铺失败: {e}')
        return jsonify({'error': '删除店铺失败'}), 500

def get_shop_info_from_api(shop_id):
    """从API获取店铺信息"""
    try:
        import json
        from urllib.parse import quote
        import time

        param = json.dumps({"shop_id": shop_id, "page_id": 0})
        encoded_param = quote(param)

        api_url = f"https://thor.weidian.com/decorate/customSharePage.getPageInfo/1.0?param={encoded_param}&wdtoken=8ea9315c&_={int(time.time() * 1000)}"

        response = requests.get(api_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
            'Origin': 'https://weidian.com',
            'Referer': 'https://weidian.com/',
            'Sec-Ch-Ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        }, cookies={
            'wdtoken': '8ea9315c',
            '__spider__visitorid': '0dcf6a5b878847ec',
            'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
            'v-components/cpn-coupon-dialog@nologinshop': '2',
            '__spider__sessionid': 'c7da7d6e06b1f1ac'
        }, timeout=10, proxies={'http': None, 'https': None})

        if response.status_code == 200:
            data = response.json()
            if data.get('status', {}).get('code') == 0:
                result = data.get('result', {})
                shop_name = result.get('shareTitle', '')
                if shop_name:
                    return {'shopName': shop_name}

    except Exception as e:
        logger.warning(f'获取店铺信息失败: {e}')

    return None

@app.route('/api/scrape/shop', methods=['POST'])
def scrape_shop():
    """抓取整个店铺的所有商品"""
    try:
        data = request.get_json()
        if not data or not data.get('shopId'):
            return jsonify({'error': '缺少shopId参数'}), 400

        shop_id = data['shopId'].strip()
        if not shop_id.isdigit():
            return jsonify({'error': 'shopId必须是数字'}), 400

        logger.info(f'开始抓取店铺: {shop_id}')

        # 这里实现店铺抓取逻辑
        # 使用微店API获取店铺所有商品
        result = scrape_shop_products(shop_id)

        logger.info(f'店铺 {shop_id} 抓取完成，共获取 {result["total_products"]} 个商品')

        return jsonify({
            'success': True,
            'totalProducts': result["total_products"],
            'pagesProcessed': result["pages_processed"],
            'message': f'成功抓取 {result["total_products"]} 个商品，共处理 {result["pages_processed"]} 页'
        })

    except Exception as e:
        logger.error(f'店铺抓取失败: {e}')
        return jsonify({'error': str(e)}), 500

def scrape_shop_products(shop_id):
    """抓取店铺所有商品的实现"""
    import requests
    import time

    total_products = 0
    offset = 0
    limit = 20
    page_count = 0

    # 获取店铺名称
    shop_info = get_shop_info_from_api(shop_id)
    shop_name = shop_info.get('shopName', f'店铺 {shop_id}') if shop_info else f'店铺 {shop_id}'
    logger.info(f'开始抓取店铺: {shop_name} (ID: {shop_id})')

    while True:
        try:
            # 构建API URL
            url = f"https://thor.weidian.com/decorate/shopDetail.tab.getItemList/1.0"
            params = {
                "param": f'{{"shopId":"{shop_id}","tabId":0,"sortOrder":"desc","offset":{offset},"limit":{limit},"from":"h5","showItemTag":true}}'
            }

            # 发送请求
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'origin': 'https://weidian.com',
                'priority': 'u=1, i',
                'referer': 'https://weidian.com/',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
            }

            cookies = {
                'wdtoken': '8ea9315c',
                '__spider__visitorid': '0dcf6a5b878847ec',
                'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
                'v-components/cpn-coupon-dialog@nologinshop': '10',
                '__spider__sessionid': 'e55c6458ac1fdba4'
            }

            response = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=10, proxies={'http': None, 'https': None})

            if response.status_code != 200:
                logger.warning(f'API请求失败: {response.status_code}')
                break

            data = response.json()

            if data.get('status', {}).get('code') != 0:
                logger.warning('API响应状态码不为0')
                break

            result = data.get('result', {})
            if not result.get('hasData', False):
                logger.info('没有更多数据，抓取完成')
                break

            items = result.get('itemList', [])
            if not items:
                logger.info('商品列表为空，抓取完成')
                break

            # 批量处理商品详情（多线程）
            products_to_process = []
            for item in items:
                item_id = item.get('itemId', '')
                if item_id:
                    products_to_process.append({
                        'item_id': item_id,
                        'item_url': item.get('itemUrl', ''),
                        'shop_name': shop_name
                    })

            if products_to_process:
                # 多线程获取商品详情
                processed_products = process_products_multithreaded(products_to_process)

                for product_data in processed_products:
                    try:
                        if product_data:
                            # 检查商品是否已存在
                            existing = db.get_product_by_url(product_data['product_url'])
                            if existing:
                                logger.debug(f'商品已存在，跳过: {product_data["title"]}')
                                continue

                            # 插入商品
                            product_id = db.insert_product(product_data)

                            # 下载图片
                            if product_data.get('images'):
                                save_product_images(product_id, product_data['images'])

                            total_products += 1
                            logger.debug(f'成功添加商品: {product_data["title"]}')

                    except Exception as e:
                        logger.error(f'保存商品失败: {e}')
                        continue

            # 增加offset继续抓取
            offset += limit

            # 避免请求过于频繁
            time.sleep(0.5)

        except Exception as e:
            logger.error(f'抓取过程中出错: {e}')
            break

    return {
        "total_products": total_products,
        "pages_processed": page_count
    }

def scrape_product_info(product_url):
    """根据商品URL获取商品详细信息"""
    try:
        from weidian_scraper import get_weidian_scraper

        scraper = get_weidian_scraper()
        product_info = scraper.scrape_product_info(product_url)

        if product_info:
            # 重新格式化返回数据
            return {
                'title': product_info.get('title', ''),
                'description': product_info.get('description', ''),
                'images': product_info.get('images', [])[:5],  # 最多5张图片
                'shop_name': product_info.get('shop_name', '')
            }

        return None

    except Exception as e:
        logger.error(f'获取商品详细信息失败: {e}')
        return None

def generate_acbuy_url(weidian_url):
    """生成AcBuy链接"""
    if not weidian_url:
        return ''

    try:
        import re
        item_id_match = re.search(r'itemID=(\d+)', weidian_url)
        if item_id_match:
            item_id = item_id_match.group(1)
            # 构建acbuy链接
            encoded_url = weidian_url.replace(':', '%3A').replace('/', '%2F').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
            return f'https://www.acbuy.com/product?url={encoded_url}&id={item_id}&source=WD'
    except Exception as e:
        logger.error(f'生成AcBuy链接失败: {e}')

    return ''

def generate_cnfans_url(item_id):
    """生成CNFans链接"""
    if not item_id:
        return ''
    return f"https://cnfans.com/product?id={item_id}&platform=WEIDIAN"

def generate_english_title(chinese_title):
    """将中文标题翻译为英文标题"""
    if not chinese_title:
        return ''

    try:
        import re
        import requests

        # 首先尝试提取已有的英文部分
        english_parts = re.findall(r'[a-zA-Z\s]+', chinese_title)
        if english_parts and len(' '.join(english_parts).strip()) > 5:
            # 如果英文部分足够长，直接返回
            return ' '.join(english_parts).strip()

        # 品牌名称映射（扩展版）
        brand_mappings = {
            'Nike': 'Nike', '阿迪': 'Adidas', 'Adidas': 'Adidas', '李宁': 'LiNing',
            '安踏': 'Anta', '匹克': 'Peak', '乔丹': 'Jordan', 'New Balance': 'New Balance',
            'Converse': 'Converse', 'Vans': 'Vans', 'Supreme': 'Supreme', 'BAPE': 'BAPE',
            'Palace': 'Palace', 'Stone Island': 'Stone Island', 'Off-White': 'Off-White',
            'Balenciaga': 'Balenciaga', 'Gucci': 'Gucci', 'Louis Vuitton': 'Louis Vuitton',
            'Chanel': 'Chanel', 'Dior': 'Dior', 'Yeezy': 'Yeezy', 'Puma': 'Puma',
            'Reebok': 'Reebok', 'Under Armour': 'Under Armour', 'Fila': 'Fila',
            'The North Face': 'The North Face', 'Columbia': 'Columbia', 'Patagonia': 'Patagonia',
            'Arc\'teryx': 'Arc\'teryx', 'Canada Goose': 'Canada Goose', 'Moncler': 'Moncler',
            'Burberry': 'Burberry', 'Prada': 'Prada', 'Versace': 'Versace', 'Fendi': 'Fendi',
            'Hermes': 'Hermes', 'Rolex': 'Rolex', 'Cartier': 'Cartier', 'Omega': 'Omega',
            'IWC': 'IWC', 'Jaeger-LeCoultre': 'Jaeger-LeCoultre', 'Patek Philippe': 'Patek Philippe'
        }

        # 应用品牌映射
        title = chinese_title
        for zh, en in brand_mappings.items():
            title = title.replace(zh, en)

        # 检查是否还有中文字符
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in title)

        if has_chinese:
            # 使用百度翻译API或其他免费翻译服务
            try:
                # 这里使用一个简单的翻译API示例
                # 实际部署时需要替换为稳定的翻译服务
                api_url = "https://api.mymemory.translated.net/get"
                params = {
                    'q': chinese_title,
                    'langpair': 'zh-CN|en-US',
                    'de': 'your-email@example.com'  # MyMemory要求提供邮箱
                }

                response = requests.get(api_url, params=params, timeout=5, proxies={'http': None, 'https': None})
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get('responseData', {}).get('translatedText', '')
                    if translated and translated != chinese_title:
                        # 清理翻译结果
                        translated = re.sub(r'[^\w\s\-]', '', translated)
                        return translated.strip()

            except Exception as e:
                logger.warning(f'在线翻译失败: {e}')

            # 如果翻译失败，返回提取的英文部分或原标题
            english_parts = re.findall(r'[a-zA-Z\s\-]+', title)
            if english_parts:
                result = ' '.join(english_parts).strip()
                if len(result) > 3:
                    return result

        # 如果没有中文或翻译失败，返回处理后的标题
        return re.sub(r'[^\w\s\-]', '', title).strip()

    except Exception as e:
        logger.error(f'生成英文标题失败: {e}')
        return chinese_title

def process_single_product(product_info):
    """处理单个商品的详情抓取"""
    try:
        item_id = product_info['item_id']
        item_url = product_info['item_url']
        shop_name = product_info['shop_name']

        # 获取商品详细信息
        product_details = scrape_product_info(item_url)

        if product_details:
            # 生成英文标题
            english_title = generate_english_title(product_details.get('title', ''))

            return {
                'product_url': item_url,
                'title': product_details.get('title', ''),
                'description': product_details.get('description', ''),
                'english_title': english_title,
                'cnfans_url': generate_cnfans_url(item_id),
                'acbuy_url': generate_acbuy_url(item_url),
                'shop_name': shop_name,
                'images': product_details.get('images', []),
                'ruleEnabled': True
            }
        return None

    except Exception as e:
        logger.error(f'处理商品失败: {e}')
        return None

def process_products_multithreaded(products_list):
    """多线程处理商品详情抓取"""
    import concurrent.futures

    processed_products = []

    # 获取配置的线程数
    max_workers = config.DOWNLOAD_THREADS if hasattr(config, 'DOWNLOAD_THREADS') else 4

    logger.info(f'开始多线程处理 {len(products_list)} 个商品，使用 {max_workers} 个线程')

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_product = {
            executor.submit(process_single_product, product): product
            for product in products_list
        }

        # 收集结果
        for future in concurrent.futures.as_completed(future_to_product):
            try:
                result = future.result()
                if result:
                    processed_products.append(result)
            except Exception as e:
                logger.error(f'商品处理任务失败: {e}')

    logger.info(f'多线程处理完成，共处理 {len(processed_products)} 个商品')
    return processed_products

def save_product_images(product_id, image_urls):
    """保存商品图片"""
    try:
        for index, image_url in enumerate(image_urls[:5]):  # 最多保存5张图片
            if image_url:
                # 下载图片
                response = requests.get(image_url, timeout=10, proxies={'http': None, 'https': None})
                if response.status_code == 200:
                    # 保存图片到本地
                    image_filename = f"{product_id}_{index}.jpg"
                    image_path = os.path.join('data', 'images', image_filename)

                    # 确保目录存在
                    os.makedirs(os.path.dirname(image_path), exist_ok=True)

                    with open(image_path, 'wb') as f:
                        f.write(response.content)

                    # 插入图片记录到数据库
                    db.insert_image_record(product_id, image_path, index)

                    logger.debug(f'保存图片: {image_filename}')

    except Exception as e:
        logger.error(f'保存商品图片失败: {e}')

if __name__ == '__main__':
    import atexit
    import threading
    import time

    # 注册退出时停止机器人的函数
    atexit.register(stop_discord_bot)

    # 本地开发模式 - 总是启用热重载
    print("🚀 Starting Flask API in development mode...")
    print("🤖 Discord bot will start after Flask is ready...")
    print("🔄 Hot reload enabled - modify files and refresh browser")

    # 在后台启动机器人（延迟启动）
    def delayed_bot_start():
        # 等待Flask应用完全启动
        time.sleep(3)
        start_discord_bot()

    bot_startup_thread = threading.Thread(target=delayed_bot_start, daemon=True)
    bot_startup_thread.start()

    try:
        app.run(host='127.0.0.1', port=5001, debug=config.DEBUG, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Received interrupt signal, shutting down...")
    finally:
        stop_discord_bot()
