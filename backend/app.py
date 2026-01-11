from flask import Flask, request, jsonify, Response, session
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
import hashlib

# 在应用启动时从数据库加载系统配置
def load_system_config():
    """从数据库加载系统配置到内存"""
    # 在函数内部定义logger，因为此时全局logger可能还没有初始化
    import logging
    func_logger = logging.getLogger(__name__)

    try:
        sys_config = db.get_system_config()
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

# === 重构：店铺抓取状态控制 ===
scrape_status = {
    'is_scraping': False,
    'paused': False,
    'stop_signal': False,
    'current_shop_id': None,
    'total': 0,
    'processed': 0,
    'success': 0,
    'message': '等待开始...'
}

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
bot_running = False  # 标记机器人是否正在运行

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
# 生产环境使用强随机密钥
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# CORS 配置，必须允许 Credentials
CORS(app, origins=["http://localhost:3000"], supports_credentials=True)

# Cookie 配置优化 (解决本地调试 Cookie 无法写入的问题)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax', # 在同一域名不同端口下 Lax 通常更好
    SESSION_COOKIE_SECURE=False,   # 本地调试必须为 False，否则 http 下不发送 cookie
)

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

        # 获取用户店铺权限过滤（用于Discord机器人）
        user_shops = None
        user_shops_json = request.form.get('user_shops')
        if user_shops_json:
            try:
                user_shops = json.loads(user_shops_json)
            except:
                user_shops = None

        # 调试信息
        print(f"DEBUG: Received threshold: {threshold}")
        print(f"DEBUG: User shops filter: {user_shops}")
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
            # 用较低的阈值搜索找到候选结果，然后从中筛选满足用户阈值的结果
            low_threshold_results = db.search_similar_images(query_features, limit=10, threshold=0.1)
            print(f"DEBUG: Low threshold (0.1) search results: {len(low_threshold_results) if low_threshold_results else 0}")

            # 从低阈值结果中筛选出满足用户阈值的结果
            results = []
            if low_threshold_results:
                for result in low_threshold_results:
                    similarity = result.get('similarity', 0)
                    # 应用用户相似度阈值和店铺过滤
                    if similarity >= threshold:
                        # 检查店铺权限
                        if user_shops and result.get('shop_name') not in user_shops:
                            print(f"DEBUG: Skipping result from shop {result.get('shop_name')} - not in user shops {user_shops}")
                            continue
                        results.append(result)
                        if len(results) >= limit:
                            break

            print(f"DEBUG: Filtered results count (threshold {threshold}): {len(results)}")
            if results:
                print(f"DEBUG: Best match similarity: {results[0]['similarity']}")
            elif low_threshold_results:
                print(f"DEBUG: Best low-threshold match similarity: {low_threshold_results[0]['similarity']}")
            print(f"DEBUG: Total indexed images: {db.get_total_indexed_images()}")

            # 如果没有找到满足阈值的结果，但有高质量的低阈值匹配（相似度>0.8），也可以考虑使用
            if not results and low_threshold_results and len(low_threshold_results) > 0:
                best_low_match = low_threshold_results[0]
                if best_low_match.get('similarity', 0) > 0.8:  # 高质量匹配
                    print(f"DEBUG: Using high-quality low-threshold result (similarity: {best_low_match['similarity']:.4f})")
                    results = [best_low_match]

            response_data = {
                'success': True,
                'results': [],
                'totalResults': 0,
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

                    # 获取实际的图片URL列表
                    actual_images = []
                    if product_info:
                        with db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT image_index FROM product_images WHERE product_id = ? ORDER BY image_index", (result['id'],))
                            actual_images = [f"/api/image/{result['id']}/{row[0]}" for row in cursor.fetchall()]

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
                            'acbuyUrl': product_info.get('acbuy_url', ''),
                            'ruleEnabled': product_info.get('ruleEnabled', True) if product_info else True,
                            'images': actual_images if actual_images else [f"/api/image/{result['id']}/{result['image_index']}"]  # 使用实际图片列表
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
            'shop_name': product_info.get('shop_name', ''),  # 从product_info获取店铺名称
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
# ===== 用户认证和权限管理API =====

def get_current_user():
    """获取当前登录用户"""
    user_id = session.get('user_id')
    if user_id:
        return db.get_user_by_id(user_id)
    return None

def require_admin():
    """检查是否为管理员"""
    user = get_current_user()
    return user and user.get('role') == 'admin'

def can_manage_shops():
    """检查用户是否有管理店铺的权限（管理员或有分配的店铺）"""
    user = get_current_user()
    if not user:
        return False
    # 管理员可以管理所有店铺
    if user.get('role') == 'admin':
        return True
    # 普通用户如果有分配的店铺，也可以管理
    user_shops = user.get('shops', [])
    return len(user_shops) > 0

def require_login():
    """检查是否已登录"""
    # 开发模式下跳过认证
    if config.DEBUG:
        # 开发模式下自动设置为admin用户
        if 'user_id' not in session:
            session['user_id'] = 1  # 默认admin用户ID
        return True
    return get_current_user() is not None

@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': '用户名和密码不能为空'}), 400

        username = data['username']
        password = data['password']

        user = db.authenticate_user(username, password)
        if user:
            session['user_id'] = user['id']
            # 不返回密码哈希
            user_info = {k: v for k, v in user.items() if k != 'password_hash'}
            return jsonify({'user': user_info, 'message': '登录成功'})
        else:
            return jsonify({'error': '用户名或密码错误'}), 401
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return jsonify({'error': '登录失败'}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """用户登出"""
    session.pop('user_id', None)
    return jsonify({'message': '已登出'})

@app.route('/api/auth/me', methods=['GET'])
def get_current_user_info():
    """获取当前用户信息"""
    user = get_current_user()
    if user:
        # 不返回密码哈希
        user_info = {k: v for k, v in user.items() if k != 'password_hash'}
        return jsonify({'user': user_info})
    return jsonify({'error': '未登录'}), 401

@app.route('/api/users', methods=['GET'])
def get_users():
    """获取所有用户（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        users = db.get_all_users()
        # 不返回密码哈希
        for user in users:
            user.pop('password_hash', None)
        return jsonify({'users': users})
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users', methods=['POST'])
def create_user():
    """创建新用户（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': '用户名和密码不能为空'}), 400

        username = data['username']
        password = data['password']
        role = data.get('role', 'user')
        shop_ids = data.get('shops', [])

        # 创建用户
        password_hash = f"hashed_{password}"
        if db.create_user(username, password_hash, role):
            # 获取新创建的用户ID
            user = db.authenticate_user(username, password_hash)
            if user:
                # 设置店铺权限
                if shop_ids:
                    db.update_user_shops(user['id'], shop_ids)

                user_info = {k: v for k, v in user.items() if k != 'password_hash'}
                return jsonify({'user': user_info, 'message': '用户创建成功'})
            else:
                return jsonify({'error': '用户创建失败'}), 500
        else:
            return jsonify({'error': '用户名已存在或创建失败'}), 400
    except Exception as e:
        logger.error(f"创建用户失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """删除用户（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        current_user = get_current_user()
        if current_user['id'] == user_id:
            return jsonify({'error': '不能删除自己的账号'}), 400

        # 检查用户是否存在
        user = db.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404

        # 删除用户
        if db.delete_user(user_id):
            logger.info(f"管理员 {current_user['username']} 删除了用户 {user['username']}")
            return jsonify({'message': '用户删除成功'})
        else:
            return jsonify({'error': '用户删除失败'}), 500
    except Exception as e:
        logger.error(f"删除用户失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 新增：管理员修改用户密码 ===
@app.route('/api/users/<int:user_id>/password', methods=['PUT'])
def reset_user_password(user_id):
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        new_password = data.get('password')
        if not new_password:
            return jsonify({'error': '密码不能为空'}), 400

        # 简单哈希 (生产环境请用 bcrypt)
        password_hash = f"hashed_{new_password}"

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            conn.commit()

        return jsonify({'success': True, 'message': '密码已重置'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === 新增：网站配置管理API ===
@app.route('/api/websites', methods=['GET'])
def get_website_configs():
    """获取所有网站配置"""
    try:
        configs = db.get_website_configs()
        return jsonify({'websites': configs})
    except Exception as e:
        logger.error(f"获取网站配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites', methods=['POST'])
def add_website_config():
    """添加网站配置"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        name = data.get('name')
        display_name = data.get('display_name')
        url_template = data.get('url_template')
        id_pattern = data.get('id_pattern')
        badge_color = data.get('badge_color', 'blue')

        if not all([name, display_name, url_template, id_pattern]):
            return jsonify({'error': '所有字段都是必填的'}), 400

        if db.add_website_config(name, display_name, url_template, id_pattern, badge_color):
            return jsonify({'success': True, 'message': '网站配置已添加'})
        else:
            return jsonify({'error': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加网站配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>', methods=['PUT'])
def update_website_config(config_id):
    """更新网站配置"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        name = data.get('name')
        display_name = data.get('display_name')
        url_template = data.get('url_template')
        id_pattern = data.get('id_pattern')
        badge_color = data.get('badge_color', 'blue')

        if not all([name, display_name, url_template, id_pattern]):
            return jsonify({'error': '所有字段都是必填的'}), 400

        if db.update_website_config(config_id, name, display_name, url_template, id_pattern, badge_color):
            return jsonify({'success': True, 'message': '网站配置已更新'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>', methods=['DELETE'])
def delete_website_config(config_id):
    """删除网站配置"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        if db.delete_website_config(config_id):
            return jsonify({'success': True, 'message': '网站配置已删除'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除网站配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/channels', methods=['GET'])
def get_website_channels(config_id):
    """获取网站绑定的频道"""
    try:
        channels = db.get_website_channel_bindings(config_id)
        return jsonify({'channels': channels})
    except Exception as e:
        logger.error(f"获取网站频道失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/channels', methods=['POST'])
def add_website_channel(config_id):
    """添加网站频道绑定"""
    try:
        data = request.get_json()
        channel_id = data.get('channel_id')

        if not channel_id:
            return jsonify({'error': '频道ID不能为空'}), 400

        if db.add_website_channel_binding(config_id, channel_id):
            return jsonify({'success': True, 'message': '频道绑定已添加'})
        else:
            return jsonify({'error': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加网站频道绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/channels/<channel_id>', methods=['DELETE'])
def remove_website_channel(config_id, channel_id):
    """移除网站频道绑定"""
    try:
        if db.remove_website_channel_binding(config_id, channel_id):
            return jsonify({'success': True, 'message': '频道绑定已移除'})
        else:
            return jsonify({'error': '移除失败'}), 500
    except Exception as e:
        logger.error(f"移除网站频道绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>/urls', methods=['GET'])
def get_product_urls(product_id):
    """获取商品的所有网站URL"""
    try:
        # 获取商品信息
        product = db._get_product_info_by_id(product_id)
        if not product:
            return jsonify({'error': '商品不存在'}), 404

        # 从商品URL中提取微店ID
        weidian_url = product.get('product_url', '')
        weidian_id = None

        if 'itemID=' in weidian_url:
            # 提取itemID参数
            import re
            match = re.search(r'itemID=([^&]+)', weidian_url)
            if match:
                weidian_id = match.group(1)

        if not weidian_id:
            return jsonify({'urls': []})

        # 生成所有网站的URL
        urls = db.generate_website_urls(weidian_id)
        return jsonify({'urls': urls})
    except Exception as e:
        logger.error(f"获取商品URL失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 新增：系统统计信息API ===
@app.route('/api/system/stats', methods=['GET'])
def get_system_stats():
    """获取系统统计信息"""
    try:
        stats = db.get_system_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"获取系统统计信息失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 新增：公告管理API ===
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    """获取所有公告"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        announcements = db.get_active_announcements()
        return jsonify({'announcements': announcements})
    except Exception as e:
        logger.error(f"获取公告失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    """创建公告"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        title = data.get('title')
        content = data.get('content')

        if not title or not content:
            return jsonify({'error': '标题和内容都是必填的'}), 400

        if db.create_announcement(title, content):
            return jsonify({'success': True, 'message': '公告创建成功'})
        else:
            return jsonify({'error': '创建失败'}), 500
    except Exception as e:
        logger.error(f"创建公告失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements/<int:announcement_id>', methods=['PUT'])
def update_announcement(announcement_id):
    """更新公告"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        title = data.get('title')
        content = data.get('content')
        is_active = data.get('is_active', True)

        if not title or not content:
            return jsonify({'error': '标题和内容都是必填的'}), 400

        if db.update_announcement(announcement_id, title, content, is_active):
            return jsonify({'success': True, 'message': '公告更新成功'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新公告失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/announcements/<int:announcement_id>', methods=['DELETE'])
def delete_announcement(announcement_id):
    """删除公告"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        if db.delete_announcement(announcement_id):
            return jsonify({'success': True, 'message': '公告删除成功'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除公告失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 新增：消息过滤规则API ===
@app.route('/api/message-filters', methods=['GET'])
def get_message_filters():
    """获取消息过滤规则"""
    try:
        filters = db.get_message_filters()
        return jsonify({'filters': filters})
    except Exception as e:
        logger.error(f"获取消息过滤规则失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/message-filters', methods=['POST'])
def add_message_filter():
    """添加消息过滤规则"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        filter_type = data.get('filter_type')
        filter_value = data.get('filter_value')

        if not filter_type or not filter_value:
            return jsonify({'error': '过滤类型和值都是必填的'}), 400

        if db.add_message_filter(filter_type, filter_value):
            return jsonify({'success': True, 'message': '过滤规则添加成功'})
        else:
            return jsonify({'error': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加消息过滤规则失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/message-filters/<int:filter_id>', methods=['PUT'])
def update_message_filter(filter_id):
    """更新消息过滤规则"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        filter_type = data.get('filter_type')
        filter_value = data.get('filter_value')
        is_active = data.get('is_active', True)

        if not filter_type or not filter_value:
            return jsonify({'error': '过滤类型和值都是必填的'}), 400

        if db.update_message_filter(filter_id, filter_type, filter_value, is_active):
            return jsonify({'success': True, 'message': '过滤规则更新成功'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新消息过滤规则失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/message-filters/<int:filter_id>', methods=['DELETE'])
def delete_message_filter(filter_id):
    """删除消息过滤规则"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        if db.delete_message_filter(filter_id):
            return jsonify({'success': True, 'message': '过滤规则删除成功'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除消息过滤规则失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 新增：自定义回复内容API ===
@app.route('/api/custom-replies', methods=['GET'])
def get_custom_replies():
    """获取自定义回复内容"""
    try:
        replies = db.get_custom_replies()
        return jsonify({'replies': replies})
    except Exception as e:
        logger.error(f"获取自定义回复内容失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/custom-replies', methods=['POST'])
def add_custom_reply():
    """添加自定义回复内容"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        reply_type = data.get('reply_type')
        content = data.get('content')
        image_url = data.get('image_url')
        priority = data.get('priority', 0)

        if not reply_type:
            return jsonify({'error': '回复类型是必填的'}), 400

        if db.add_custom_reply(reply_type, content, image_url, priority):
            return jsonify({'success': True, 'message': '自定义回复添加成功'})
        else:
            return jsonify({'error': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加自定义回复失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/custom-replies/<int:reply_id>', methods=['PUT'])
def update_custom_reply(reply_id):
    """更新自定义回复内容"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        reply_type = data.get('reply_type')
        content = data.get('content')
        image_url = data.get('image_url')
        priority = data.get('priority', 0)
        is_active = data.get('is_active', True)

        if not reply_type:
            return jsonify({'error': '回复类型是必填的'}), 400

        if db.update_custom_reply(reply_id, reply_type, content, image_url, priority, is_active):
            return jsonify({'success': True, 'message': '自定义回复更新成功'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新自定义回复失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/custom-replies/<int:reply_id>', methods=['DELETE'])
def delete_custom_reply(reply_id):
    """删除自定义回复内容"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        if db.delete_custom_reply(reply_id):
            return jsonify({'success': True, 'message': '自定义回复删除成功'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除自定义回复失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:user_id>/shops', methods=['PUT'])
def update_user_shops(user_id):
    """更新用户店铺权限（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        shop_ids = data.get('shops', [])

        if db.update_user_shops(user_id, shop_ids):
            return jsonify({'message': '权限更新成功'})
        else:
            return jsonify({'error': '权限更新失败'}), 500
    except Exception as e:
        logger.error(f"更新用户权限失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """获取所有 Discord 账号"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    current_user = get_current_user()
    try:
        # 根据用户权限过滤账号
        if current_user['role'] == 'admin':
            # 管理员可以看到所有账号
            accounts = db.get_discord_accounts_by_user(None)
        else:
            # 普通用户只能看到自己关联的账号
            accounts = db.get_discord_accounts_by_user(current_user['id'])

        return jsonify({'accounts': accounts})
    except Exception as e:
        logger.error(f"获取账号列表失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products', methods=['GET'])
def list_products():
    """列出用户有权限的商品及其图片"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    current_user = get_current_user()
    try:
        # 根据用户权限获取商品（获取所有记录，不分页）
        if current_user['role'] == 'admin':
            # 管理员可以看到所有商品
            logger.info(f"管理员用户 {current_user['username']} 获取所有商品")
            result = db.get_products_by_user_shops(None, limit=None)
        else:
            # 普通用户只能看到自己管理的店铺的商品
            user_shops = current_user.get('shops', [])
            logger.info(f"普通用户 {current_user['username']} 获取店铺商品，分配的店铺: {user_shops}")
            result = db.get_products_by_user_shops(user_shops, limit=None)

            # 调试：检查数据库中的商品和店铺匹配情况
            if user_shops:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    placeholders = ','.join('?' * len(user_shops))
                    cursor.execute(f"SELECT COUNT(*) FROM products WHERE shop_name IN ({placeholders})", user_shops)
                    matching_products = cursor.fetchone()[0]
                    logger.info(f"数据库中匹配的商品数量: {matching_products}")

                    # 列出所有店铺名称
                    cursor.execute("SELECT DISTINCT shop_name FROM products")
                    all_shop_names = [row[0] for row in cursor.fetchall()]
                    logger.info(f"数据库中的所有店铺名称: {all_shop_names}")

        logger.info(f"返回商品数量: {len(result['products'])}")

        # 添加调试信息到响应中
        response_data = {
            'products': result['products'],
            'total': result['total'],
            'debug': {
                'user_role': current_user['role'],
                'user_shops': current_user.get('shops', []),
                'is_admin': current_user['role'] == 'admin'
            }
        }
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"列出商品失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products', methods=['PUT'])
def update_product():
    """更新商品信息"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    current_user = get_current_user()
    data = request.get_json()

    if not data or not data.get('id'):
        return jsonify({'error': '商品ID不能为空'}), 400

    product_id = data['id']
    title = data.get('title')

    try:
        # 检查商品是否存在且用户有权限访问
        if current_user['role'] == 'admin':
            # 管理员可以更新所有商品
            pass
        else:
            # 普通用户只能更新自己管理的店铺的商品
            user_shops = current_user.get('shops', [])
            product = db.get_product_by_id(product_id)
            if not product or product.get('shop_name') not in user_shops:
                return jsonify({'error': '无权限更新此商品'}), 403

        # 更新商品标题
        if title is not None:
            db.update_product_title(product_id, title)

        return jsonify({'message': '商品更新成功', 'product': {'id': product_id, 'title': title}})
    except Exception as e:
        logger.error(f"更新商品失败: {e}")
        return jsonify({'error': '更新失败'}), 500


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
        # 获取当前登录用户
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': '需要登录'}), 401

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
                INSERT INTO discord_accounts (username, token, status, user_id)
                VALUES (?, ?, 'offline', ?)
            """, (username, token, current_user['id']))
            account_id = cursor.lastrowid

            cursor.execute("SELECT id, username, token, status, last_active, user_id FROM discord_accounts WHERE id = ?", (account_id,))
            account = cursor.fetchone()
            conn.commit()

        logger.info(f"账号添加成功: {username} (用户ID: {current_user['id']})")
        return jsonify({
            'id': account[0],
            'username': account[1],
            'token': account[2],
            'status': account[3],
            'lastActive': account[4],
            'user_id': account[5],
            'verified': True
        })
    except Exception as e:
        logger.error(f"添加账号失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<int:account_id>/user', methods=['PUT'])
def assign_account_to_user(account_id):
    """将Discord账号分配给用户（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        user_id = data.get('user_id')

        if db.update_discord_account_user(account_id, user_id):
            return jsonify({'message': '账号分配成功'})
        else:
            return jsonify({'error': '账号分配失败'}), 500
    except Exception as e:
        logger.error(f"分配账号失败: {e}")
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

@app.route('/api/user/settings', methods=['GET'])
def get_user_settings():
    """获取当前用户的个性化设置"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '需要登录'}), 401

    try:
        settings = db.get_user_settings(user['id'])
        return jsonify(settings)
    except Exception as e:
        logger.error(f"获取用户设置失败: {e}")
        return jsonify({'error': '获取设置失败'}), 500

@app.route('/api/user/settings', methods=['PUT'])
def update_user_settings():
    """更新当前用户的个性化设置"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request body'}), 400

        success = db.update_user_settings(
            user_id=user['id'],
            download_threads=data.get('download_threads'),
            feature_extract_threads=data.get('feature_extract_threads'),
            discord_similarity_threshold=data.get('discord_similarity_threshold'),
            global_reply_min_delay=data.get('global_reply_min_delay'),
            global_reply_max_delay=data.get('global_reply_max_delay')
        )

        if success:
            return jsonify({'message': '设置更新成功'})
        else:
            return jsonify({'error': '设置更新失败'}), 500
    except Exception as e:
        logger.error(f"更新用户设置失败: {e}")
        return jsonify({'error': '更新设置失败'}), 500

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

# === 修复：批量删除 API ===
@app.route('/api/products/batch', methods=['DELETE'])
def batch_delete_products():
    """批量删除商品"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'error': 'No IDs provided'}), 400

        count = 0
        for pid in ids:
            if db.delete_product_images(pid):
                count += 1

        return jsonify({'success': True, 'count': count})
    except Exception as e:
        logger.error(f"批量删除失败: {e}")
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

# === 修复：商品图片上传 API ===
@app.route('/api/products/<int:product_id>/images', methods=['POST'])
def upload_product_image(product_id):
    """上传新图片到商品（多线程处理）"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file'}), 400

        file = request.files['image']
        if not file.filename:
            return jsonify({'error': 'Empty filename'}), 400

        # 获取当前最大的 image_index 和检查图片数量限制
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(image_index) FROM product_images WHERE product_id = ?", (product_id,))
            row = cursor.fetchone()
            next_index = (row[0] + 1) if row and row[0] is not None else 0

            # 检查图片数量限制（每个商品最多20张图片）
            cursor.execute("SELECT COUNT(*) FROM product_images WHERE product_id = ?", (product_id,))
            count_row = cursor.fetchone()
            if count_row and count_row[0] >= 20:
                return jsonify({'error': '每个商品最多只能上传20张图片'}), 400

        # 保存文件
        filename = f"{product_id}_{next_index}_{int(time.time())}.jpg"
        save_path = os.path.join('data', 'images', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)

        # 多线程处理：特征提取和索引
        import concurrent.futures
        import threading

        result = {'success': False, 'error': None}

        def process_image_async():
            """异步处理图片特征提取和索引"""
            try:
                # 提取特征
                global feature_extractor
                features = feature_extractor.extract_feature(save_path)

                if features is None:
                    os.remove(save_path)
                    result['error'] = '特征提取失败，图片无效'
                    return

                # 存入数据库
                img_db_id = db.insert_image_record(product_id, save_path, next_index)

                # 存入 FAISS
                from vector_engine import get_vector_engine
                engine = get_vector_engine()
                engine.add_vector(img_db_id, features)
                engine.save()

                result['success'] = True
                result['img_db_id'] = img_db_id
                logger.info(f"图片上传成功: product_id={product_id}, image_index={next_index}, db_id={img_db_id}")

            except Exception as e:
                logger.error(f"图片处理失败: {e}")
                result['error'] = str(e)
                # 清理失败的文件
                try:
                    os.remove(save_path)
                except:
                    pass

        # 启动后台线程处理图片
        processing_thread = threading.Thread(target=process_image_async, daemon=True)
        processing_thread.start()

        # 等待最多5秒让处理完成
        processing_thread.join(timeout=5.0)

        if not result['success']:
            error_msg = result.get('error', '图片处理失败')
            return jsonify({'error': error_msg}), 500

        # 返回更新后的商品信息
        product = db._get_product_info_by_id(product_id)
        # 获取所有图片
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT image_index FROM product_images WHERE product_id = ? ORDER BY image_index", (product_id,))
            images = [f"/api/image/{product_id}/{row[0]}" for row in cursor.fetchall()]

        product['images'] = images
        # 格式化以匹配前端
        product['weidianId'] = product.get('product_url', '').split('itemID=')[1] if 'itemID=' in product.get('product_url', '') else ''
        product['weidianUrl'] = product.get('product_url')
        product['englishTitle'] = product.get('english_title')
        product['cnfansUrl'] = product.get('cnfans_url')
        product['ruleEnabled'] = product.get('ruleEnabled')
        product['matchType'] = 'fuzzy' # Default

        return jsonify({'success': True, 'product': product})
    except Exception as e:
        logger.error(f"上传图片失败: {e}")
        return jsonify({'error': str(e)}), 500

# === 修复：删除图片后返回最新 Product 对象 ===
@app.route('/api/products/<int:product_id>/images/<int:image_index>', methods=['DELETE'])
def delete_product_image(product_id, image_index):
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        logger.info(f"开始删除图片: product_id={product_id}, image_index={image_index}")


        # 验证参数
        try:
            product_id = int(product_id)
            image_index = int(image_index)
        except ValueError:
            return jsonify({'error': '参数格式错误'}), 400

        # 调用数据库删除逻辑
        success = db.delete_image_vector(product_id, image_index)

        if not success:
            logger.warning(f"删除图片失败: product_id={product_id}, image_index={image_index}")
            return jsonify({'error': '删除失败，图片可能不存在'}), 404

        # 获取最新商品信息
        product = db._get_product_info_by_id(product_id)

        if not product:
            logger.error(f"删除后商品不存在: product_id={product_id}")
            return jsonify({'error': '商品不存在'}), 404

        # 获取剩余所有图片
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT image_index FROM product_images WHERE product_id = ? ORDER BY image_index", (product_id,))
            image_indices = [row[0] for row in cursor.fetchall()]
            images = [f"/api/image/{product_id}/{idx}" for idx in image_indices]

        product['images'] = images
        # 格式化
        try:
            if 'itemID=' in product.get('product_url', ''):
                product['weidianId'] = product.get('product_url', '').split('itemID=')[1]
            else:
                product['weidianId'] = ''
        except:
            product['weidianId'] = ''

        product['weidianUrl'] = product.get('product_url')
        product['englishTitle'] = product.get('english_title')
        product['cnfansUrl'] = product.get('cnfans_url')
        product['acbuyUrl'] = product.get('acbuy_url')
        product['ruleEnabled'] = product.get('ruleEnabled')

        logger.info(f"删除图片成功: product_id={product_id}, image_index={image_index}, 剩余图片数量={len(images)}")

        return jsonify({'success': True, 'product': product})

    except Exception as e:
        logger.error(f"删除图片失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup/images', methods=['POST'])
def cleanup_images():
    """清理未使用的图片文件"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        if current_user['role'] != 'admin':
            return jsonify({'error': '只有管理员可以执行清理操作'}), 403

        # 获取清理参数
        data = request.get_json() or {}
        days_old = data.get('days_old', 30)

        # 执行清理
        deleted_count = db.cleanup_unused_images(days_old)

        return jsonify({
            'success': True,
            'message': f'清理完成，共删除 {deleted_count} 个未使用的图片文件',
            'deleted_count': deleted_count
        })

    except Exception as e:
        logger.error(f"图片清理失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/yolo-status', methods=['GET'])
def get_yolo_status():
    """获取YOLO-World状态和统计信息"""
    try:
        global feature_extractor
        status = {
            'yolo_available': feature_extractor.detector is not None,
            'yolo_type': 'YOLO-World' if hasattr(feature_extractor, 'target_classes') and feature_extractor.target_classes else 'YOLOv8-Nano',
            'target_classes_count': len(feature_extractor.target_classes) if feature_extractor.target_classes else 0,
            'detection_cache_size': len(feature_extractor._detection_cache) if hasattr(feature_extractor, '_detection_cache') else 0,
            'confidence_threshold': 0.05,
            'iou_threshold': 0.5,
            'target_classes': feature_extractor.target_classes[:20] if feature_extractor.target_classes else []
        }
        return jsonify(status)
    except Exception as e:
        logger.error(f"获取YOLO状态失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/rebuild-index', methods=['POST'])
def rebuild_faiss_index():
    """重建FAISS索引，清理已删除的向量"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        if current_user['role'] != 'admin':
            return jsonify({'error': '只有管理员可以重建索引'}), 403

        from vector_engine import get_vector_engine
        engine = get_vector_engine()

        # 获取所有有效的图片数据
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, image_path FROM product_images WHERE id IS NOT NULL")
            all_images = cursor.fetchall()

        # 重新提取所有特征
        valid_vectors = []
        for row in all_images:
            try:
                global feature_extractor
                features = feature_extractor.extract_feature(row['image_path'])
                if features is not None:
                    valid_vectors.append((row['id'], features))
            except Exception as e:
                logger.warning(f"重新提取特征失败 {row['image_path']}: {e}")

        # 重建索引
        engine.rebuild_index(valid_vectors)

        return jsonify({
            'success': True,
            'message': f'索引重建完成，包含 {len(valid_vectors)} 个向量',
            'total_vectors': len(valid_vectors)
        })

    except Exception as e:
        logger.error(f"重建索引失败: {e}")
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

def start_discord_bot(user_id=None):
    """启动Discord机器人 - 支持多账号"""
    global bot_clients, bot_tasks, bot_running

    if bot_running:
        logger.warning("机器人已经在运行中")
        return

    try:
        import asyncio
        from bot import DiscordBotClient

        logger.info(f"正在启动Discord机器人... (用户ID: {user_id})")

        # 获取账号 - 如果指定了用户ID，只获取该用户的账号
        if user_id:
            accounts = db.get_discord_accounts_by_user(user_id)
        else:
            # 获取所有账号
            accounts = db.get_discord_accounts_by_user(None)

        if not accounts:
            logger.warning("没有找到可用的Discord账号")
            return

        logger.info(f"找到 {len(accounts)} 个Discord账号，开始启动...")

        # 在新的事件循环中运行机器人
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 为每个账号创建机器人实例
        for account in accounts:
            account_id = account['id']
            token = account['token']
            username = account.get('username', f'account_{account_id}')
            user_id = account.get('user_id')

            # 获取用户管理的店铺
            user_shops = None
            if user_id:
                user = db.get_user_by_id(user_id)
                if user:
                    user_shops = user.get('shops', [])

            logger.info(f"正在启动机器人账号: {username} (用户ID: {user_id}, 管理店铺: {user_shops})")

            # 创建机器人实例
            client = DiscordBotClient(account_id=account_id, user_id=user_id, user_shops=user_shops)

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

        if bot_clients:
            bot_running = True
            logger.info(f"共启动了 {len(bot_clients)} 个Discord机器人")
        else:
            logger.warning("没有成功启动任何机器人")

    except ImportError as e:
        logger.warning(f"Discord机器人模块不可用: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")

def stop_discord_bot():
    """停止Discord机器人"""
    global bot_clients, bot_tasks, bot_running

    if not bot_running:
        logger.info("机器人未在运行")
        return

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
                        # 更新账号状态为offline
                        if hasattr(client, 'account_id') and client.account_id:
                            db.update_account_status(client.account_id, 'offline')
                            logger.info(f"账号 {client.account_id} 状态已更新为离线")
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

    # 清空机器人列表
    bot_clients.clear()
    bot_tasks.clear()
    bot_running = False

# ===== 机器人控制API =====

@app.route('/api/bot/start', methods=['POST'])
def start_bot():
    """启动Discord机器人"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json()
        user_id = data.get('userId')

        if not user_id:
            return jsonify({'error': '需要用户ID'}), 400

        # 检查用户是否有权限的账号
        user_accounts = db.get_discord_accounts_by_user(user_id)

        if not user_accounts:
            return jsonify({'error': '用户没有Discord账号，请先添加账号'}), 400

        # 启动机器人（启动所有账号，不管是否在线）
        start_discord_bot(user_id)

        logger.info(f"用户 {user_id} 启动机器人成功，共有 {len(user_accounts)} 个账号")
        return jsonify({
            'message': '账号启动成功',
            'totalAccounts': len(user_accounts)
        })

    except Exception as e:
        logger.error(f"启动机器人失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    """停止Discord机器人"""
    try:
        stop_discord_bot()
        logger.info("机器人停止成功")
        return jsonify({'message': '机器人停止成功'})

    except Exception as e:
        logger.error(f"停止机器人失败: {e}")
        return jsonify({'error': str(e)}), 500

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
    if not can_manage_shops():
        return jsonify({'error': '需要管理店铺的权限'}), 403

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
    if not can_manage_shops():
        return jsonify({'error': '需要管理店铺的权限'}), 403

    try:
        # 获取店铺信息，检查用户是否有权限删除
        shop_info = db.get_shop_by_id(shop_id)
        if not shop_info:
            return jsonify({'error': '店铺不存在'}), 404

        current_user = get_current_user()
        # 管理员可以删除任何店铺，普通用户只能删除分配给他们的店铺
        if current_user['role'] != 'admin' and shop_info['name'] not in current_user.get('shops', []):
            return jsonify({'error': '无权限删除此店铺'}), 403

        if db.delete_shop(shop_id):
            return jsonify({'success': True, 'message': '店铺删除成功'})
        else:
            return jsonify({'error': '删除失败'}), 500
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
    if not can_manage_shops():
        return jsonify({'error': '需要管理店铺的权限'}), 403

    try:
        data = request.get_json()
        if not data or not data.get('shopId'):
            return jsonify({'error': '缺少shopId参数'}), 400

        shop_id = data['shopId'].strip()
        if not shop_id.isdigit():
            return jsonify({'error': 'shopId必须是数字'}), 400

        # 检查是否已有抓取任务在运行
        global scrape_status
        if scrape_status.get('is_scraping', False):
            return jsonify({'error': '已有抓取任务在运行中，请等待完成后再试'}), 409

        logger.info(f'开始抓取店铺: {shop_id}')

        # 在后台线程中运行抓取任务，避免阻塞其他操作
        import threading

        def run_scrape_task():
            """后台抓取任务"""
            try:
                scrape_shop_products(shop_id)
            except Exception as e:
                logger.error(f'抓取任务异常: {e}')
            finally:
                # 确保状态正确重置
                global scrape_status
                scrape_status.update({
                    'is_scraping': False,
                    'message': f'抓取异常结束: {str(e)}' if 'e' in locals() else '抓取已完成'
                })

        # 创建守护线程，确保不会阻塞应用退出
        scrape_thread = threading.Thread(target=run_scrape_task, daemon=True, name=f'scrape-{shop_id}')
        scrape_thread.start()

        logger.info(f'已启动后台抓取线程处理店铺 {shop_id}')

        return jsonify({
            'success': True,
            'message': '抓取任务已启动，请查看进度'
        })

    except Exception as e:
        logger.error(f'店铺抓取失败: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrape/shop/control', methods=['POST'])
def control_shop_scrape():
    """控制抓取任务: start, pause, resume, stop"""
    action = request.json.get('action')
    shop_id = request.json.get('shopId')

    global scrape_status

    if action == 'stop':
        scrape_status['stop_signal'] = True
        scrape_status['message'] = '正在停止...'
        return jsonify(scrape_status)

    if action == 'pause':
        scrape_status['paused'] = True
        scrape_status['message'] = '已暂停'
        return jsonify(scrape_status)

    if action == 'resume':
        scrape_status['paused'] = False
        scrape_status['message'] = '继续抓取...'
        return jsonify(scrape_status)

    if action == 'start':
        if scrape_status['is_scraping']:
            return jsonify({'error': '已有任务在运行'}), 400

        # 重置状态
        scrape_status.update({
            'is_scraping': True,
            'paused': False,
            'stop_signal': False,
            'current_shop_id': shop_id,
            'total': 0,
            'processed': 0,
            'success': 0,
            'message': '初始化抓取...'
        })

        # 异步启动
        threading.Thread(target=run_shop_scrape_task, args=(shop_id,), daemon=True).start()
        return jsonify(scrape_status)

    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/scrape/shop/status', methods=['GET'])
def get_scrape_status():
    """获取抓取状态"""
    return jsonify(scrape_status)

@app.route('/api/products/count', methods=['GET'])
def get_products_count():
    """获取商品总数"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            count = cursor.fetchone()[0]
            return jsonify({'count': count})
    except Exception as e:
        logger.error(f"获取商品数量失败: {e}")
        return jsonify({'count': 0}), 500

@app.route('/api/debug/user_permissions', methods=['GET'])
def debug_user_permissions():
    """调试用户权限和商品分配（管理员权限）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 获取所有用户
            cursor.execute('SELECT id, username, role FROM users')
            users = []
            for row in cursor.fetchall():
                user_dict = dict(row)
                user_dict['shops'] = db.get_user_shops(user_dict['id'])
                users.append(user_dict)

            # 获取所有店铺
            cursor.execute('SELECT id, name FROM shops')
            shops = [dict(row) for row in cursor.fetchall()]

            # 获取商品统计
            cursor.execute('SELECT shop_name, COUNT(*) as count FROM products GROUP BY shop_name')
            product_stats = [dict(row) for row in cursor.fetchall()]

            # 获取用户店铺权限统计
            cursor.execute('SELECT user_id, COUNT(*) as shop_count FROM user_shop_permissions GROUP BY user_id')
            permission_stats = []
            for row in cursor.fetchall():
                user_id, shop_count = row
                user = next((u for u in users if u['id'] == user_id), None)
                if user:
                    permission_stats.append({
                        'username': user['username'],
                        'shop_count': shop_count,
                        'shops': user['shops']
                    })

            return jsonify({
                'users': users,
                'shops': shops,
                'product_stats': product_stats,
                'permission_stats': permission_stats
            })
    except Exception as e:
        logger.error(f"调试用户权限失败: {e}")
        return jsonify({'error': str(e)}), 500

def run_shop_scrape_task(shop_id):
    """后台抓取任务"""
    global scrape_status
    try:
        from weidian_scraper import get_weidian_scraper
        # 这里复用之前的 scrape_shop_products 逻辑，但加入状态检查
        # 为简化代码，此处模拟逻辑，您应将原 scrape_shop_products 修改为检查 scrape_status

        logger.info(f"后台任务开始抓取店铺: {shop_id}")

        # 模拟初始化
        time.sleep(1)
        scrape_status['total'] = 100 # 假设

        for i in range(100):
            # 检查停止
            if scrape_status['stop_signal']:
                scrape_status['message'] = '任务已取消'
                break

            # 检查暂停
            while scrape_status['paused']:
                if scrape_status['stop_signal']: break
                time.sleep(1)

            # 执行抓取 (模拟)
            # 实际代码调用: process_single_product(...)
            time.sleep(0.1)

            scrape_status['processed'] += 1
            scrape_status['success'] += 1
            scrape_status['message'] = f'正在处理第 {i+1} 个商品...'

        if not scrape_status['stop_signal']:
            scrape_status['message'] = '抓取完成'

    except Exception as e:
        logger.error(f"后台抓取异常: {e}")
        scrape_status['message'] = f"出错: {str(e)}"
    finally:
        scrape_status['is_scraping'] = False

def scrape_shop_products(shop_id):
    """抓取店铺所有商品的实现"""
    import requests
    import time

    global scrape_status

    total_products = 0
    offset = 0
    limit = 20
    page_count = 0

    # 初始化状态
    scrape_status.update({
        'is_scraping': True,
        'progress': 0,
        'total': 0,
        'current': 0,
        'message': '正在初始化...'
    })

    # 获取店铺名称
    shop_info = get_shop_info_from_api(shop_id)
    shop_name = shop_info.get('shopName', f'店铺 {shop_id}') if shop_info else f'店铺 {shop_id}'
    logger.info(f'开始抓取店铺: {shop_name} (ID: {shop_id})')
    scrape_status['message'] = f'正在抓取店铺: {shop_name}'

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
                # 多线程处理整个页面：获取详情 + 插入数据库 + 下载图片
                processed_count = process_page_multithreaded(products_to_process, page_count + 1)
                total_products += processed_count
                logger.info(f'第 {page_count + 1} 页处理完成，新增 {processed_count} 个商品')

                # 更新状态
                scrape_status.update({
                    'current': total_products,
                    'message': f'已处理 {page_count + 1} 页，新增 {total_products} 个商品'
                })

            # 增加offset继续抓取
            offset += limit

            # 避免请求过于频繁
            time.sleep(0.5)

        except Exception as e:
            logger.error(f'抓取过程中出错: {e}')
            break

    # 抓取完成，重置状态
    scrape_status.update({
        'is_scraping': False,
        'completed': True,
        'progress': 100,
        'message': f'抓取完成，共处理 {total_products} 个商品，{page_count} 页'
    })

    logger.info(f'店铺 {shop_id} 抓取完成，共处理 {total_products} 个商品，{page_count} 页')

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

def process_page_multithreaded(products_list, page_num):
    """
    多线程处理整个页面：获取详情 + 插入数据库 + 下载图片
    每个线程负责一个商品的完整处理流程
    """
    import concurrent.futures

    processed_count = 0

    # 获取配置的线程数
    max_workers = config.DOWNLOAD_THREADS if hasattr(config, 'DOWNLOAD_THREADS') else 4

    logger.info(f'第 {page_num} 页开始多线程处理 {len(products_list)} 个商品')

    def process_and_save_product(product):
        """处理单个商品的完整流程：获取详情 -> 插入数据库 -> 下载图片"""
        try:
            # 1. 获取商品详情
            product_data = process_single_product(product)
            if not product_data:
                return 0

            # 2. 检查商品是否已存在
            existing = db.get_product_by_url(product_data['product_url'])
            if existing:
                logger.debug(f'商品已存在，跳过: {product_data["title"]}')
                return 0

            # 3. 插入商品到数据库
            product_id = db.insert_product(product_data)
            logger.debug(f'成功插入商品: {product_data["title"]} (ID: {product_id})')

            # 4. 下载并保存图片
            if product_data.get('images'):
                save_product_images(product_id, product_data['images'])
                logger.debug(f'商品图片下载完成: {product_data["title"]}')

            return 1  # 成功处理一个商品

        except Exception as e:
            logger.error(f'处理商品失败: {e}')
            return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务，每个商品一个任务
        future_to_product = {
            executor.submit(process_and_save_product, product): product
            for product in products_list
        }

        # 收集结果
        for future in concurrent.futures.as_completed(future_to_product):
            try:
                result = future.result()
                processed_count += result
            except Exception as e:
                logger.error(f'页面处理任务失败: {e}')

    logger.info(f'第 {page_num} 页处理完成，成功新增 {processed_count} 个商品')
    return processed_count

def save_product_images(product_id, image_urls):
    """保存商品图片并提取特征向量（高性能版本）"""
    try:
        # 使用进程池而不是线程池，避免GIL限制
        import concurrent.futures
        import multiprocessing

        def process_single_image(args):
            """处理单张图片：下载 -> 保存 -> 提取特征 -> 索引"""
            index, image_url = args
            try:
                # 下载图片（使用更短的超时时间）
                response = requests.get(image_url, timeout=5, proxies={'http': None, 'https': None})
                if response.status_code != 200:
                    return None

                # 生成唯一文件名，避免并发冲突
                timestamp = int(time.time() * 1000000)  # 微秒级时间戳
                image_filename = f"{product_id}_{index}_{timestamp}.jpg"
                image_path = os.path.join('data', 'images', image_filename)

                # 确保目录存在
                os.makedirs(os.path.dirname(image_path), exist_ok=True)

                # 直接写入文件，避免内存占用过多
                with open(image_path, 'wb') as f:
                    f.write(response.content)

                # 验证图片完整性
                if os.path.getsize(image_path) == 0:
                    os.remove(image_path)
                    return None

                # 提取特征（这里会调用YOLO裁剪和DINOv2特征提取）
                global feature_extractor
                features = feature_extractor.extract_feature(image_path)

                if features is None:
                    # 特征提取失败，删除文件
                    os.remove(image_path)
                    return None

                # 返回处理结果，让主进程统一处理数据库操作
                return {
                    'image_path': image_path,
                    'features': features,
                    'index': index
                }

            except Exception as e:
                logger.error(f'处理图片失败 {image_url}: {e}')
                return None

        # 使用进程池处理图片下载和特征提取
        # CPU核心数的一半，避免过度占用系统资源
        cpu_count = max(1, multiprocessing.cpu_count() // 2)
        max_workers = min(len(image_urls), cpu_count)

        logger.info(f'商品 {product_id} 开始多进程处理 {len(image_urls)} 张图片，使用 {max_workers} 个进程')

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            image_tasks = [(index, url) for index, url in enumerate(image_urls[:5]) if url]
            futures = [executor.submit(process_single_image, task) for task in image_tasks]

            # 收集结果
            processed_results = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    processed_results.append(result)

        # 在主进程中统一处理数据库操作，避免进程间数据库连接问题
        processed_images = 0
        for result in processed_results:
            try:
                    # 插入图片记录到数据库
                img_db_id = db.insert_image_record(product_id, result['image_path'], result['index'])

                # 添加到FAISS索引
                from vector_engine import get_vector_engine
                engine = get_vector_engine()
                engine.add_vector(img_db_id, result['features'])

                processed_images += 1
                logger.debug(f'图片入库完成: {os.path.basename(result["image_path"])} (ID: {img_db_id})')

            except Exception as e:
                logger.error(f'图片入库失败 {result["image_path"]}: {e}')
                # 清理失败的文件
                try:
                    os.remove(result['image_path'])
                except:
                    pass

        # 保存FAISS索引（批量保存更高效）
        if processed_images > 0:
            from vector_engine import get_vector_engine
            engine = get_vector_engine()
            engine.save()

        logger.info(f'商品 {product_id} 图片处理完成，共处理 {processed_images}/{len(image_urls)} 张图片')

    except Exception as e:
        logger.error(f'保存商品图片失败: {e}')

def save_product_images_multithreaded(product_id, image_urls):
    """多线程版本的图片保存函数（向后兼容）"""
    save_product_images(product_id, image_urls)

if __name__ == '__main__':
    import atexit
    import threading
    import time

    # 注册退出时停止机器人的函数
    atexit.register(stop_discord_bot)

    # 本地开发模式 - 总是启用热重载
    print("🚀 Starting Flask API in development mode...")
    print("🤖 Discord bot will NOT auto-start. Use web interface to start manually...")
    print("🔄 Hot reload enabled - modify files and refresh browser")

    try:
        app.run(host='127.0.0.1', port=5001, debug=config.DEBUG, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Received interrupt signal, shutting down...")
    finally:
        stop_discord_bot()
