from flask import Flask, request, jsonify, Response, session
import numpy as np
import os
import logging
import sys
from datetime import datetime
from threading import Lock

# 自动加载.env文件
try:
    from dotenv import load_dotenv
    # 从项目根目录加载.env文件
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ 已加载环境变量文件: {env_path}")
    else:
        print("ℹ️  未找到.env文件，使用系统环境变量")
except ImportError:
    print("ℹ️  python-dotenv未安装，使用系统环境变量")

try:
    from feature_extractor import get_feature_extractor, DINOv2FeatureExtractor
except ImportError:
    from .feature_extractor import get_feature_extractor, DINOv2FeatureExtractor
try:
    from database import db
    from config import config
except ImportError:
    from .database import db
    from .config import config
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

def check_duplicate_image(new_features, existing_features_list, threshold=0.99):
    """
    检查新图片的特征向量是否与现有列表中的图片重复

    :param new_features: 新图片的特征向量 (numpy array)
    :param existing_features_list: 现有图片的特征向量列表 (可以是json字符串列表或numpy列表)
    :param threshold: 相似度阈值，默认99%
    :return: (is_duplicate, similarity_score)
    """
    if not existing_features_list:
        return False, 0.0

    try:
        # 预计算新向量的范数
        norm_new = np.linalg.norm(new_features)
        if norm_new == 0:
            return False, 0.0

        for feat_item in existing_features_list:
            try:
                # 处理输入可能是 JSON 字符串或已经是 numpy 数组的情况
                if isinstance(feat_item, str):
                    feat_vec = np.array(json.loads(feat_item), dtype='float32')
                else:
                    feat_vec = np.array(feat_item, dtype='float32')

                norm_existing = np.linalg.norm(feat_vec)
                if norm_existing == 0:
                    continue

                # 计算余弦相似度
                dot_product = np.dot(new_features, feat_vec)
                similarity = dot_product / (norm_new * norm_existing)

                if similarity > threshold:
                    return True, similarity

            except Exception:
                continue

    except Exception as e:
        logger.error(f"向量比对出错: {e}")

    return False, 0.0

def process_and_save_image_core(product_id, image_url_or_file, index, existing_features=None, save_faiss_immediately=True):
    """
    核心图片处理单元：保存 -> 特征提取 -> 查重 -> 数据库 -> FAISS

    :param product_id: 商品ID
    :param image_url_or_file: 或者是 URL 字符串，或者是 Flask 的 FileStorage 对象
    :param index: 图片索引
    :param existing_features: 现有特征向量列表，用于查重
    :param save_faiss_immediately: 是否立即保存FAISS索引（单张上传时为True，批量处理时为False）
    :return: 处理结果字典
    """
    import os
    import time

    # 1. 确定保存路径（使用配置的目录）
    timestamp = int(time.time() * 1000000)
    filename = f"{product_id}_{index}_{timestamp}.jpg"
    save_path = os.path.join(config.IMAGE_SAVE_DIR, str(product_id), filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    img_db_id = None  # 初始化数据库 ID

    try:
        # 2. 保存文件
        if hasattr(image_url_or_file, 'save'):
            # 是上传的文件对象 (FileStorage)
            image_url_or_file.save(save_path)
        else:
            # 是 URL 字符串
            import requests
            resp = requests.get(image_url_or_file, timeout=config.REQUEST_TIMEOUT, proxies={'http': None, 'https': None})
            if resp.status_code != 200:
                return {'success': False, 'error': f'Download failed: {resp.status_code}'}
            with open(save_path, 'wb') as f:
                f.write(resp.content)

        # 验证文件大小
        if os.path.getsize(save_path) == 0:
            os.remove(save_path)
            return {'success': False, 'error': 'Empty file'}

        # 3. 特征提取 (DINOv2 + YOLO)
        extractor = get_global_feature_extractor()
        if extractor is None:
            os.remove(save_path)
            return {'success': False, 'error': 'Feature extractor not initialized'}

        features = extractor.extract_feature(save_path)
        if features is None:
            os.remove(save_path)
            return {'success': False, 'error': 'Feature extraction failed'}

        # 4. 查重逻辑 (99.5%相似度)
        if existing_features:
            is_dup, score = check_duplicate_image(features, existing_features, threshold=0.995)
            if is_dup:
                os.remove(save_path)
                logger.info(f"🚫 图片高度相似 (相似度: {score:.4f})，已跳过: {filename}")
                return {'success': True, 'skipped': True}  # 标记为成功但跳过，以免报错

        # 5. 入库 (SQLite)
        img_db_id = db.insert_image_record(product_id, save_path, index, features)

        # 6. 入库 (FAISS)
        try:
            from vector_engine import get_vector_engine
            engine = get_vector_engine()

            # === FAISS 线程安全锁 ===
            with faiss_lock:  # 加锁，确保同一时间只有一个线程写入 FAISS
                engine.add_vector(img_db_id, features)
                # 性能优化：单张上传时立即保存，批量处理时延迟保存
                if save_faiss_immediately:
                    engine.save()
        except Exception as faiss_err:
            logger.error(f"FAISS 入库失败: {faiss_err}")
            # FAISS失败时删除数据库记录和文件，回滚操作
            try:
                db.delete_image_record(img_db_id)
            except:
                pass
            if os.path.exists(save_path):
                os.remove(save_path)
            return {'success': False, 'error': f'FAISS error: {faiss_err}'}

        # 7. 更新对比列表，确保下一张图能跟这张比
        if existing_features is not None:
            existing_features.append(features)  # 关键：实时加入列表

        # 8. 完成
        return {
            'success': True,
            'image_path': save_path,
            'features': features,
            'index': index,
            'filename': filename,
            'db_id': img_db_id
        }

    except Exception as e:
        logger.error(f'图片处理总出错，尝试清理: {e}')
        if os.path.exists(save_path):
            os.remove(save_path)
        # 如果已经插入数据库但后续失败，需要回滚
        if img_db_id:
            try:
                db.delete_image_record(img_db_id)
            except:
                pass
        return {'success': False, 'error': str(e)}

# 线程配置现在统一在 config.py 中管理

# 加载系统配置
load_system_config()

# === 重构：店铺抓取状态控制 ===
# 移除全局状态变量，改为数据库持久化存储
# scrape_status现在通过db.get_scrape_status()和db.update_scrape_status()管理

# 线程管理：跟踪当前运行的抓取线程
current_scrape_thread = None
scrape_thread_lock = threading.Lock()
scrape_stop_event = threading.Event()  # 抓取停止事件，用于线程间通信

# FAISS 线程安全锁：防止多线程同时写入向量索引导致崩溃
faiss_lock = Lock()

# 全局关闭事件，用于优雅关闭
shutdown_event = None

# 配置日志
# 1. 获取根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 2. 清除现有的所有处理器（防止 Flask 或 basicConfig 自动添加的导致重复）
if root_logger.handlers:
    root_logger.handlers = []

# 3. 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
root_logger.addHandler(console_handler)

# 4. 创建队列日志处理器 (用于前端 SSE)
log_queue = queue.Queue()
log_clients = []
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

        # 2. 关键修复：允许 weidian_scraper 和 app 的 INFO 日志通过
        # 只要是这些模块，即使是 INFO 级别也允许通过
        whitelist_modules = [
            '__main__', 'app', 'database', 'bot',
            'weidian_scraper', 'feature_extractor',
            'vector_engine', 'migrate_data'
        ]

        if record.module in whitelist_modules:
            return False

        # 对于其他未知模块，只显示WARNING级别以上
        if record.levelno < logging.WARNING:
            return True

        return False

# 5. 添加队列处理器
queue_handler = QueueHandler()
queue_handler.setLevel(logging.INFO)
root_logger.addHandler(queue_handler)

# 控制台处理器已在上面配置完成

# 1. 设置 werkzeug 日志级别为 WARNING，屏蔽 HTTP 请求刷屏
logging.getLogger('werkzeug').setLevel(logging.WARNING)
# 2. 设置其他库的日志级别
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)  # 屏蔽 YOLO 日志

logger = logging.getLogger(__name__)

# 机器人相关变量
bot_clients = []
bot_tasks = []
bot_running = False  # 标记机器人是否正在运行

# 全局特征提取器实例（在应用启动时创建）
feature_extractor_instance = None

def initialize_feature_extractor():
    """在应用启动时初始化特征提取器，确保单例模式"""
    global feature_extractor_instance
    if feature_extractor_instance is None:
        print("🚀 初始化全局特征提取器实例...")
        try:
            from feature_extractor import DINOv2FeatureExtractor
            feature_extractor_instance = DINOv2FeatureExtractor()
            print("✅ 全局特征提取器实例初始化完成")
        except Exception as e:
            print(f"❌ 特征提取器初始化失败: {e}")
            feature_extractor_instance = None
    return feature_extractor_instance

def get_global_feature_extractor():
    """获取全局特征提取器实例"""
    global feature_extractor_instance
    if feature_extractor_instance is None:
        return initialize_feature_extractor()
    return feature_extractor_instance

# 在应用启动时初始化
initialize_feature_extractor()

# Flask配置初始化（简化版 - 解决HTTP IP访问问题）
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# CORS 配置（允许所有来源）
CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)

# 强制更新配置，覆盖默认的安全设置
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=config.SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,  # 确保是False
    SESSION_COOKIE_DOMAIN=None,
    PERMANENT_SESSION_LIFETIME=config.SESSION_LIFETIME,  # 30天不过期
)

def extract_features(image_path):
    """使用深度学习模型提取图像特征"""
    try:
        extractor = get_global_feature_extractor()
        if extractor is None:
            logger.error("特征提取器未初始化")
            return None
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
    """搜索相似图像 - 使用 FAISS HNSW"""
    try:
        image_url = request.form.get('image_url')
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
        print(f"DEBUG: Files: {list(request.files.keys()) if request.files else 'No files'}")
        print(f"DEBUG: Content-Type: {request.content_type}")
        print(f"DEBUG: Method: {request.method}")
        print(f"DEBUG: image_url parameter: '{image_url}'")

        # 处理图片来源
        import uuid
        import os
        if image_url:
            print(f"DEBUG: Processing image URL: {image_url}")
            # 验证URL格式
            if not image_url.startswith(('http://', 'https://')):
                return jsonify({'error': 'Invalid URL format, must start with http:// or https://'}), 400

            # 从URL下载图片
            import requests
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(image_url, timeout=15, headers=headers, stream=True)
                print(f"DEBUG: URL response status: {response.status_code}")
                print(f"DEBUG: Content-Type: {response.headers.get('content-type', 'unknown')}")

                if response.status_code != 200:
                    return jsonify({'error': f'Failed to download image from URL, status: {response.status_code}'}), 400

                # 检查内容类型
                content_type = response.headers.get('content-type', '').lower()
                if not any(img_type in content_type for img_type in ['image/', 'application/octet-stream']):
                    print(f"DEBUG: Warning - Content-Type '{content_type}' may not be an image")

                temp_filename = f"{uuid.uuid4()}.jpg"
                image_path = f"/tmp/{temp_filename}"

                with open(image_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # 检查文件大小
                file_size = os.path.getsize(image_path)
                print(f"DEBUG: Image downloaded to: {image_path}, size: {file_size} bytes")

                if file_size == 0:
                    os.remove(image_path)
                    return jsonify({'error': 'Downloaded file is empty'}), 400

                if file_size > 10 * 1024 * 1024:  # 10MB limit
                    os.remove(image_path)
                    return jsonify({'error': 'Image file too large (max 10MB)'}), 400

            except requests.exceptions.RequestException as e:
                print(f"DEBUG: Network error downloading image: {str(e)}")
                return jsonify({'error': f'Network error downloading image: {str(e)}'}), 400
            except Exception as e:
                print(f"DEBUG: Failed to download image: {str(e)}")
                return jsonify({'error': f'Failed to download image: {str(e)}'}), 400
        else:
            print("DEBUG: No image_url provided, checking for uploaded file")
            # 从上传的文件获取图片
            if 'image' not in request.files:
                print("DEBUG: No 'image' file found in request.files")
                return jsonify({'error': 'No image provided'}), 400

            image_file = request.files['image']
            print(f"DEBUG: Found uploaded file: {image_file.filename if image_file else 'None'}")
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

                    # 生成所有网站的链接
                    weidian_id = None
                    if product_info and product_info.get('product_url'):
                        import re
                        match = re.search(r'itemID=(\d+)', product_info['product_url'])
                        if match:
                            weidian_id = match.group(1)

                    website_urls = []
                    if weidian_id:
                        website_urls = db.generate_website_urls(weidian_id)

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
                            'images': actual_images if actual_images else [f"/api/image/{result['id']}/{result['image_index']}"],  # 使用实际图片列表
                            'websiteUrls': website_urls  # 添加所有网站的链接
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
        logger.info("收到商品抓取请求")
        data = request.get_json()
        if data is None:
            logger.error("请求体为空")
            return jsonify({'error': 'Invalid request body'}), 400

        logger.info(f"请求数据: {data}")

        # 支持两种输入方式：完整URL或商品ID
        url = data.get('url')
        weidian_id = data.get('weidianId')

        if not url and not weidian_id:
            logger.error("缺少URL或weidianId")
            return jsonify({'error': 'URL or weidianId is required'}), 400

        # 如果提供了weidianId，构造URL
        if weidian_id and not url:
            url = f"https://weidian.com/item.html?itemID={weidian_id}"
            logger.info(f"构造URL: {url}")

        # 验证URL格式
        if 'weidian.com' not in url:
            logger.error(f"不支持的URL格式: {url}")
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
            # 使用全局特征提取器
            extractor = get_global_feature_extractor()
            if extractor is None:
                logger.error("特征提取器未初始化")
                return

            # 串行建立向量索引 (SQLite不支持多线程写入)
            # 但先使用多线程进行特征提取，然后串行插入数据库
            import concurrent.futures
            try:
                from vector_engine import get_vector_engine
            except ImportError:
                from .vector_engine import get_vector_engine
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
                    with faiss_lock:  # FAISS 线程安全锁
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
    """获取所有网站配置及其频道绑定和账号绑定"""
    try:
        configs = db.get_website_configs()

        # 为每个配置添加账号绑定信息
        for config in configs:
            config_id = config['id']
            config['accounts'] = db.get_website_account_bindings(config_id)

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

# ===== 网站账号绑定API =====

@app.route('/api/websites/<int:config_id>/accounts', methods=['GET'])
def get_website_accounts(config_id):
    """获取网站绑定的账号"""
    try:
        accounts = db.get_website_account_bindings(config_id)
        return jsonify({'accounts': accounts})
    except Exception as e:
        logger.error(f"获取网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/accounts', methods=['POST'])
def add_website_account(config_id):
    """为网站绑定账号"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        account_id = data.get('account_id')
        role = data.get('role', 'both')  # 'listener', 'sender', 'both'

        if not account_id or role not in ['listener', 'sender', 'both']:
            return jsonify({'error': '无效的账号ID或角色'}), 400

        if db.add_website_account_binding(config_id, account_id, role):
            return jsonify({'success': True, 'message': f'账号绑定成功，角色: {role}'})
        else:
            return jsonify({'error': '绑定失败'}), 500
    except Exception as e:
        logger.error(f"添加网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/accounts/<int:account_id>', methods=['DELETE'])
def remove_website_account(config_id, account_id):
    """移除网站账号绑定"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        if db.remove_website_account_binding(config_id, account_id):
            return jsonify({'success': True, 'message': '账号绑定已移除'})
        else:
            return jsonify({'error': '移除失败'}), 500
    except Exception as e:
        logger.error(f"移除网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/rotation', methods=['PUT'])
def update_website_rotation(config_id):
    """更新网站轮换配置（间隔和启用状态）"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        updates = []
        messages = []

        # 更新轮换间隔
        if 'rotation_interval' in data:
            rotation_interval = data['rotation_interval']
        if rotation_interval <= 0:
            return jsonify({'error': '轮换间隔必须大于0秒'}), 400

            if db.update_website_config_rotation(config_id, rotation_interval):
                updates.append(True)
                messages.append(f'轮换间隔已设置为 {rotation_interval} 秒')
            else:
                updates.append(False)

        # 更新轮换启用状态
        if 'rotation_enabled' in data:
            rotation_enabled = data['rotation_enabled']
            if rotation_enabled not in [0, 1]:
                return jsonify({'error': '轮换启用状态必须是0或1'}), 400

            if db.update_website_config_rotation_enabled(config_id, rotation_enabled):
                updates.append(True)
                status_text = '启用' if rotation_enabled else '禁用'
                messages.append(f'轮换功能已{status_text}')
            else:
                updates.append(False)

        if all(updates):
            return jsonify({'success': True, 'message': '; '.join(messages)})
        else:
            return jsonify({'error': '部分更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站轮换配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/filters', methods=['GET'])
def get_website_filters(config_id):
    """获取网站的消息过滤条件"""
    try:
        configs = db.get_website_configs()
        config = next((c for c in configs if c['id'] == config_id), None)
        if not config:
            return jsonify({'error': '网站配置不存在'}), 404

        import json
        filters = json.loads(config.get('message_filters', '[]'))
        return jsonify({'filters': filters})
    except Exception as e:
        logger.error(f"获取网站过滤条件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/filters', methods=['PUT'])
def update_website_filters(config_id):
    """更新网站的消息过滤条件"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        data = request.get_json()
        filters = data.get('filters', [])

        # 验证过滤条件格式
        for filter_item in filters:
            if not isinstance(filter_item, dict) or 'filter_type' not in filter_item or 'filter_value' not in filter_item:
                return jsonify({'error': '过滤条件格式无效'}), 400

        import json
        filters_json = json.dumps(filters)

        if db.update_website_message_filters(config_id, filters_json):
            return jsonify({'success': True, 'message': f'已更新 {len(filters)} 个过滤条件'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站过滤条件失败: {e}")
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
        # 获取分页参数
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))  # 默认每页50条
        offset = (page - 1) * limit

        # 根据用户权限获取商品（支持分页）
        if current_user['role'] == 'admin':
            # 管理员可以看到所有商品
            logger.info(f"管理员用户 {current_user['username']} 获取商品列表 (页{page}, 每页{limit}条)")
            result = db.get_products_by_user_shops(None, limit=limit, offset=offset)
        else:
            # 普通用户只能看到自己管理的店铺的商品
            user_shops = current_user.get('shops', [])
            logger.info(f"普通用户 {current_user['username']} 获取店铺商品 (页{page}, 每页{limit}条)，分配的店铺: {user_shops}")
            result = db.get_products_by_user_shops(user_shops, limit=limit, offset=offset)

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

        # 添加缓存头以优化性能（5分钟缓存）
        response = jsonify(response_data)
        response.headers['Cache-Control'] = 'private, max-age=300'
        return response
    except Exception as e:
        logger.error(f"列出商品失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products', methods=['PUT'])
def update_product():
    """更新商品信息"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    current_user = get_current_user()

    # 检查是否是multipart/form-data（包含文件上传）
    if request.content_type and 'multipart/form-data' in request.content_type:
        # 处理文件上传
        product_id = request.form.get('id')
        if not product_id:
            return jsonify({'error': '商品ID不能为空'}), 400

        try:
            # 检查权限
            if current_user['role'] == 'admin':
                pass
            else:
                user_shops = current_user.get('shops', [])
                product = db.get_product_by_id(int(product_id))
                if not product or product.get('shop_name') not in user_shops:
                    return jsonify({'error': '无权限更新此商品'}), 403

            # 处理上传的图片文件
            uploaded_files = []
            if 'uploadedImages' in request.files:
                files = request.files.getlist('uploadedImages')
                for file in files:
                    if file and file.filename:
                        # 保存文件到商品图片目录
                        import uuid
                        import os
                        filename = f"{uuid.uuid4()}_{file.filename}"
                        image_path = os.path.join('data', 'images', str(product_id), filename)

                        # 确保目录存在
                        os.makedirs(os.path.dirname(image_path), exist_ok=True)

                        # 保存文件
                        file.save(image_path)

                        # 添加到数据库
                        db.add_product_image(int(product_id), filename)
                        uploaded_files.append(filename)

            # 构建更新数据
            updates = {}
            for key in ['title', 'englishTitle', 'ruleEnabled', 'customReplyText', 'imageSource']:
                value = request.form.get(key)
                if value is not None:
                    if key == 'englishTitle':
                        updates['english_title'] = value
                    elif key == 'ruleEnabled':
                        updates['ruleEnabled'] = value.lower() == 'true'
                    elif key == 'customReplyText':
                        updates['custom_reply_text'] = value
                    elif key == 'imageSource':
                        updates['image_source'] = value
                    else:
                        updates[key] = value

            # 处理数组数据
            if 'selectedImageIndexes' in request.form:
                import json
                try:
                    updates['custom_reply_images'] = json.loads(request.form.get('selectedImageIndexes'))
                except:
                    pass

            if 'customImageUrls' in request.form:
                try:
                    updates['custom_image_urls'] = json.loads(request.form.get('customImageUrls'))
                except:
                    pass

            # 执行更新
            if updates:
                success = db.update_product(int(product_id), updates)
                if success:
                    updated_product = db.get_product_by_id(int(product_id))
                    return jsonify({'message': '商品更新成功', 'product': updated_product})
                else:
                    return jsonify({'error': '更新失败'}), 500
            else:
                return jsonify({'error': '没有要更新的字段'}), 400

        except Exception as e:
            logger.error(f"更新商品失败: {e}")
            return jsonify({'error': '更新失败'}), 500
    else:
        # 处理JSON数据（原有逻辑）
        data = request.get_json()

    if not data or not data.get('id'):
        return jsonify({'error': '商品ID不能为空'}), 400

    product_id = data['id']

    try:
            # 检查权限
        if current_user['role'] == 'admin':
            pass
        else:
            user_shops = current_user.get('shops', [])
            product = db.get_product_by_id(product_id)
            if not product or product.get('shop_name') not in user_shops:
                return jsonify({'error': '无权限更新此商品'}), 403

            # 构建更新数据
            updates = {}
            if 'title' in data:
                updates['title'] = data['title']
            if 'englishTitle' in data:
                updates['english_title'] = data['englishTitle']
            if 'ruleEnabled' in data:
                updates['ruleEnabled'] = data['ruleEnabled']
            if 'customReplyText' in data:
                updates['custom_reply_text'] = data['customReplyText']
            if 'selectedImageIndexes' in data:
                updates['custom_reply_images'] = data['selectedImageIndexes']
            if 'customImageUrls' in data:
                updates['custom_image_urls'] = data['customImageUrls']
            if 'imageSource' in data:
                updates['image_source'] = data['imageSource']

            # 执行更新
            if updates:
                success = db.update_product(product_id, updates)
                if success:
                    updated_product = db.get_product_by_id(product_id)
                    return jsonify({'message': '商品更新成功', 'product': updated_product})
                else:
                    return jsonify({'error': '更新失败'}), 500
            else:
                return jsonify({'error': '没有要更新的字段'}), 400

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
        try:
            from vector_engine import get_vector_engine
        except ImportError:
            from .vector_engine import get_vector_engine
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

            # 首先检查token是否已存在
            cursor.execute("SELECT id, username, user_id FROM discord_accounts WHERE token = ?", (token,))
            existing_account = cursor.fetchone()

            if existing_account:
                # 如果token已存在，检查是否属于当前用户
                if existing_account[2] == current_user['id']:
                    # 属于当前用户，更新信息
                    cursor.execute("""
                        UPDATE discord_accounts
                        SET username = ?, status = 'offline', updated_at = CURRENT_TIMESTAMP
                        WHERE token = ?
                    """, (username, token))
                    account_id = existing_account[0]
                    logger.info(f"更新现有账号: {username} (用户ID: {current_user['id']})")
                else:
                    # 属于其他用户，返回错误
                    return jsonify({'error': '此Discord token已被其他用户使用'}), 400
            else:
                # token不存在，插入新记录
                cursor.execute("""
                    INSERT INTO discord_accounts (username, token, status, user_id)
                    VALUES (?, ?, 'offline', ?)
                """, (username, token, current_user['id']))
                account_id = cursor.lastrowid
                logger.info(f"添加新账号: {username} (用户ID: {current_user['id']})")

            # 获取账号信息
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
            global_reply_max_delay=data.get('global_reply_max_delay'),
            user_blacklist=data.get('user_blacklist'),
            keyword_filters=data.get('keyword_filters')
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
    """批量删除商品（多线程高性能版）"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'error': 'No IDs provided'}), 400

        logger.info(f"开始批量删除 {len(ids)} 个商品")

        # 使用多线程删除
        import concurrent.futures
        max_threads = min(5, len(ids))  # 删除用较少的线程，避免IO冲突

        deleted_count = 0
        failed_ids = []

        def delete_single_product(product_id):
            """删除单个商品"""
            try:
                # 创建新的数据库实例避免多线程冲突
                from database import Database
                temp_db = Database()
                if temp_db.delete_product_images(product_id):
                    return {'success': True, 'id': product_id}
                else:
                    return {'success': False, 'id': product_id}
            except Exception as e:
                logger.error(f"删除商品 {product_id} 失败: {e}")
                return {'success': False, 'id': product_id}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(delete_single_product, pid) for pid in ids]

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result['success']:
                    deleted_count += 1
                else:
                    failed_ids.append(result['id'])

        logger.info(f"批量删除完成: {deleted_count}/{len(ids)} 个商品成功删除")

        response = {'success': True, 'count': deleted_count, 'total': len(ids)}
        if failed_ids:
            response['failed_ids'] = failed_ids
            response['warning'] = f'{len(failed_ids)} 个商品删除失败'

        return jsonify(response)
    except Exception as e:
        logger.error(f"批量删除失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/batch-delete-all', methods=['DELETE'])
def batch_delete_all_products():
    """删除所有商品（全选删除）"""
    try:
        # 获取所有商品ID
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM products")
            all_ids = [row['id'] for row in cursor.fetchall()]

        if not all_ids:
            return jsonify({'success': True, 'count': 0, 'message': '没有商品需要删除'})

        logger.info(f"开始删除所有 {len(all_ids)} 个商品")

        # 使用多线程删除所有商品
        import concurrent.futures
        max_threads = min(5, len(all_ids))

        deleted_count = 0
        failed_ids = []

        def delete_single_product(product_id):
            try:
                # 创建新的数据库实例避免多线程冲突
                from database import Database
                temp_db = Database()
                if temp_db.delete_product_images(product_id):
                    return {'success': True, 'id': product_id}
                else:
                    return {'success': False, 'id': product_id}
            except Exception as e:
                logger.error(f"删除商品 {product_id} 失败: {e}")
                return {'success': False, 'id': product_id}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(delete_single_product, pid) for pid in all_ids]

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result['success']:
                    deleted_count += 1
                else:
                    failed_ids.append(result['id'])

        logger.info(f"全选删除完成: {deleted_count}/{len(all_ids)} 个商品成功删除")

        response = {
            'success': True,
            'count': deleted_count,
            'total': len(all_ids),
            'message': f'成功删除 {deleted_count} 个商品'
        }

        if failed_ids:
            response['failed_ids'] = failed_ids
            response['warning'] = f'{len(failed_ids)} 个商品删除失败'

        return jsonify(response)
    except Exception as e:
        logger.error(f"全选删除失败: {e}")
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
    """上传新图片到商品（调用完整的核心处理函数）"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    file = request.files.get('image')
    if not file:
        return jsonify({'error': '无文件'}), 400

    try:
        # 获取现有特征用于查重
        existing_images = db.get_product_images(product_id)
        existing_feats = [img['features'] for img in existing_images if img['features']]

        # 获取下一个 index
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

        # 调用核心处理函数（现在包含完整的数据库和FAISS操作）
        result = process_and_save_image_core(product_id, file, next_index, existing_feats)

        if not result['success']:
            return jsonify({'error': result['error']}), 400

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
        product['matchType'] = 'fuzzy'

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

        # 格式化商品信息
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

@app.route('/api/system/ai-status', methods=['GET'])
def get_ai_status():
    """获取AI系统完整状态和诊断信息"""
    try:
        extractor = get_global_feature_extractor()
        if extractor is None:
            return {'error': '特征提取器未初始化'}
        ai_status = extractor.get_status()

        # 获取FAISS状态
        try:
            from vector_engine import get_vector_engine
        except ImportError:
            from .vector_engine import get_vector_engine
        faiss_engine = get_vector_engine()
        faiss_status = faiss_engine.get_stats()

        # 综合状态
        overall_status = {
            'ai_model_status': ai_status,
            'vector_engine_status': faiss_status,
            'system_health': '良好' if ai_status['yolo_available'] and faiss_status['total_vectors'] >= 0 else '需要优化',
            'recommendations': []
        }

        # 生成建议
        recommendations = []
        recommendations.extend(ai_status.get('performance_tips', []))
        recommendations.extend(faiss_status.get('performance_tips', []))

        # 额外的系统级建议
        if not ai_status['yolo_available']:
            recommendations.append("YOLO裁剪功能已禁用，图像识别准确率会降低")
        if faiss_status['total_vectors'] == 0:
            recommendations.append("向量数据库为空，建议添加商品数据")
        if faiss_status['ef_construction'] == '不支持' or faiss_status['ef_search'] == '不支持':
            recommendations.append("FAISS版本较旧，建议升级以获得最佳搜索性能")

        overall_status['recommendations'] = recommendations[:5]  # 最多显示5条建议

        return jsonify(overall_status)
    except Exception as e:
        logger.error(f"获取AI状态失败: {e}")
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

        try:
            from vector_engine import get_vector_engine
        except ImportError:
            from .vector_engine import get_vector_engine
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
                extractor = get_global_feature_extractor()
                if extractor is None:
                    logger.error("特征提取器未初始化")
                    continue
                features = extractor.extract_feature(row['image_path'])
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

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取系统配置信息"""
    try:
        from config import config
        return jsonify({
            'version': '1.0.0',
            'features': {
                'multithread_scraping': True,
                'ai_image_processing': True,
                'discord_bot': True,
                'real_time_monitoring': True
            },
            'limits': {
                'max_scrape_threads': config.SCRAPE_THREADS,
                'max_download_threads': config.DOWNLOAD_THREADS,
                'max_feature_threads': config.FEATURE_EXTRACT_THREADS
            }
        })
    except Exception as e:
        logger.error(f"获取配置信息失败: {e}")
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

            return jsonify({
                'message': f'Discord相似度阈值已更新为 {threshold}',
                'threshold': threshold
            })

        return jsonify({'error': '更新配置失败'}), 500
    except ValueError as e:
        return jsonify({'error': '阈值必须是数字'}), 400
    except Exception as e:
        logger.error(f"更新Discord阈值失败: {e}")
        return jsonify({'error': '更新配置失败'}), 500

@app.route('/api/config/scrape-threads', methods=['GET', 'POST'])
def config_scrape_threads():
    """配置抓取多线程数量"""
    if request.method == 'GET':
        config = db.get_system_config()
        return jsonify({
            'scrape_threads': config.get('scrape_threads', 2)
        })

    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400

        scrape_threads = int(data.get('scrape_threads', 2))

        # 确保线程数在合理范围内
        if scrape_threads < 1 or scrape_threads > 10:
            return jsonify({'error': '抓取线程数必须是1-10之间的整数'}), 400

        # 保存到数据库
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE system_config SET scrape_threads = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1',
                          (scrape_threads,))
            conn.commit()

        return jsonify({
            'message': f'抓取线程数已设置为 {scrape_threads}',
            'scrape_threads': scrape_threads
        })

    except ValueError as e:
        return jsonify({'error': '线程数必须是整数'}), 400
    except Exception as e:
        logger.error(f"更新抓取线程配置失败: {e}")
        return jsonify({'error': '更新配置失败'}), 500

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
        try:
            from vector_engine import get_vector_engine
        except ImportError:
            from .vector_engine import get_vector_engine
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

            # 确定账号角色：检查是否绑定了任何网站配置
            account_bindings = db.get_account_website_bindings(account_id)
            if account_bindings:
                # 检查账号是否有发送或监听角色
                has_sender = any(b['role'] in ['sender', 'both'] for b in account_bindings)
                has_listener = any(b['role'] in ['listener', 'both'] for b in account_bindings)

                if has_sender and has_listener:
                    role = 'both'
                elif has_sender:
                    role = 'sender'
                elif has_listener:
                    role = 'listener'
                else:
                    role = 'both'  # 默认
            else:
                role = 'both'  # 未绑定的账号默认为both

            logger.info(f"正在启动机器人账号: {username} (用户ID: {user_id}, 管理店铺: {user_shops}, 角色: {role})")

            # 创建机器人实例，传入角色参数
            client = DiscordBotClient(account_id=account_id, user_id=user_id, user_shops=user_shops, role=role)

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

@app.route('/api/bot/status', methods=['GET'])
def get_bot_status():
    """获取Discord机器人全局运行状态"""
    try:
        # 通过检查数据库中是否有账号状态为online来确定机器人是否在运行
        # 这样可以避免依赖内存中的全局变量，在多进程环境下更可靠
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM discord_accounts WHERE status = 'online'")
            online_count = cursor.fetchone()[0]
            is_running = online_count > 0
        return jsonify({'running': is_running})
    except Exception as e:
        logger.error(f"获取机器人状态失败: {e}")
        return jsonify({'running': False}), 500

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
        if current_user['role'] != 'admin' and shop_info['shop_id'] not in current_user.get('shops', []):
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
        current_status = db.get_scrape_status()
        if current_status.get('is_scraping', False):
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
                error_msg = f'抓取异常结束: {str(e)}' if 'e' in locals() else '抓取已完成'
                db.update_scrape_status(is_scraping=False, message=error_msg)

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
        return jsonify({'error': str(e)        }), 500


@app.route('/api/scrape/shop/control', methods=['POST'])
def control_shop_scrape():
    """控制抓取任务: start, stop"""
    action = request.json.get('action')
    shop_id = request.json.get('shopId')  # 可选参数

    global current_scrape_thread, scrape_thread_lock, scrape_stop_event

    # 获取当前状态
    current_status = db.get_scrape_status()
    logger.info(f"收到抓取控制请求: action={action}, shop_id={shop_id}, 当前状态: is_scraping={current_status.get('is_scraping')}, stop_signal={current_status.get('stop_signal')}")

    if action == 'stop':
        # 立即停止 - 设置停止事件和数据库状态
        scrape_stop_event.set()  # 设置停止事件，通知线程停止

        success = db.update_scrape_status(
            is_scraping=False,
            stop_signal=True,
            completed=True,
            message='抓取已停止',
            progress=100
        )

        if success:
            logger.info("✅ 抓取任务已强制停止")

            # 等待线程终止（最多等待10秒）
            with scrape_thread_lock:
                if current_scrape_thread and current_scrape_thread.is_alive():
                    logger.info("等待抓取线程终止...")
                    current_scrape_thread.join(timeout=10.0)
                    if current_scrape_thread.is_alive():
                        logger.warning("抓取线程未能在10秒内终止")
                    current_scrape_thread = None

            updated_status = db.get_scrape_status()
            return jsonify(updated_status)
        else:
            return jsonify({'error': '停止抓取失败'}), 500

    if action == 'start':
        if current_status.get('is_scraping', False):
            return jsonify({'error': '已有任务在运行'}), 400

        # 检查是否有线程在运行
        with scrape_thread_lock:
            if current_scrape_thread and current_scrape_thread.is_alive():
                return jsonify({'error': '已有线程在运行'}), 400

        # 清除停止事件，为新任务做准备
        scrape_stop_event.clear()

        # 重置状态
        success = db.update_scrape_status(
            is_scraping=True,
            stop_signal=False,
            current_shop_id=shop_id,
            total=0,
            processed=0,
            success=0,
            progress=0,
            message='初始化抓取...',
            completed=False,
            thread_id=None
        )

        if not success:
            return jsonify({'error': '重置状态失败'}), 500

        # 异步启动
        with scrape_thread_lock:
            current_scrape_thread = threading.Thread(
                target=run_shop_scrape_task,
                args=(shop_id,),
                daemon=True,
                name=f'scrape-{shop_id}'
            )
            current_scrape_thread.start()

            # 更新线程ID到数据库
            db.update_scrape_status(thread_id=current_scrape_thread.ident)

        updated_status = db.get_scrape_status()
        return jsonify(updated_status)

    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/scrape/batch', methods=['POST'])
def batch_scrape_products():
    """批量抓取多个商品（高性能多线程版本）"""
    # 在函数开始就导入所有需要的模块，避免变量作用域问题
    import concurrent.futures
    import time
    import threading

    # 确保threading变量在函数作用域内可用
    threading = threading

    try:
        data = request.get_json()
        if not data or not data.get('productIds'):
            return jsonify({'error': '缺少productIds参数'}), 400

        product_ids = data.get('productIds', [])
        if not isinstance(product_ids, list) or len(product_ids) == 0:
            return jsonify({'error': 'productIds必须是非空数组'}), 400

        # ====================================================
        # 修复：确保SCRAPE_THREADS从config正确获取
        # ====================================================
        max_threads = getattr(config, 'SCRAPE_THREADS', 10)

        # 创建停止事件用于优雅关闭
        shutdown_event = threading.Event()

        logger.info(f"✅ 开始批量抓取 {len(product_ids)} 个商品，使用 {max_threads} 个线程")

        results = {
            'total': len(product_ids),
            'processed': 0,
            'success': 0,
            'skipped': 0,
            'cancelled': 0,
            'partial': 0,
            'errors': 0,
            'start_time': time.time()
        }

        def process_single_product_batch(product_id):
            """处理单个商品（用于线程池）"""
            try:
                # === 检查停止信号 ===
                current_status = db.get_scrape_status()
                if current_status.get('stop_signal', False):
                    logger.info(f"🔴 处理商品前检测到停止信号，取消处理商品 {product_id}")
                    return {'status': 'cancelled', 'product_id': product_id, 'message': '任务已取消'}

                # 调用现有的单个商品处理逻辑
                from app import process_single_product

                # 构建商品信息
                product_info = {
                    'item_id': str(product_id),
                    'item_url': f'https://weidian.com/item.html?itemID={product_id}',
                    'shop_name': '批量上传'
                }

                # 处理商品
                product_data = process_single_product(product_info)

                if product_data:
                    # === 再次检查停止信号 ===
                    current_status = db.get_scrape_status()
                    if current_status.get('stop_signal', False):
                        logger.info(f"🔴 获取商品数据后检测到停止信号，跳过商品 {product_id}")
                        return {'status': 'cancelled', 'product_id': product_id, 'message': '任务已取消'}

                    # 检查是否已存在
                    if db.get_product_by_url(product_data['product_url']):
                        return {'status': 'skipped', 'product_id': product_id, 'message': '商品已存在'}

                    # 入库
                    product_id_db = db.insert_product(product_data)

                    # === 再次检查停止信号 ===
                    current_status = db.get_scrape_status()
                    if current_status.get('stop_signal', False):
                        logger.info(f"🔴 入库后检测到停止信号，商品 {product_id} 已入库但跳过图片处理")
                        return {'status': 'partial', 'product_id': product_id, 'message': '商品已入库，图片处理被取消'}

                    # 处理图片（使用优化后的多线程图片处理）
                    if product_data.get('images'):
                        save_product_images_unified(product_id_db, product_data['images'], shutdown_event=shutdown_event)

                    return {'status': 'success', 'product_id': product_id, 'message': '处理成功'}
                else:
                    return {'status': 'error', 'product_id': product_id, 'message': '获取商品数据失败'}

            except Exception as e:
                logger.error(f"处理商品 {product_id} 失败: {e}")
                return {'status': 'error', 'product_id': product_id, 'message': str(e)}

        # 使用线程池并发处理商品
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            # 提交所有任务
            future_to_product = {
                executor.submit(process_single_product_batch, pid): pid
                for pid in product_ids
            }

            # 收集结果 - 支持优雅停止
            pending_futures = set(future_to_product.keys())
            stop_detected = False

            try:
                while pending_futures:
                    # 检查是否有停止信号或关闭事件
                    current_status = db.get_scrape_status()
                    should_stop = (current_status.get('stop_signal', False) or
                                 (shutdown_event and shutdown_event.is_set()))

                    if should_stop and not stop_detected:
                        logger.info("🔴 检测到停止信号，正在等待已提交的任务完成...")
                        db.update_scrape_status(message='正在等待当前商品完成...')
                        stop_detected = True
                        # 不关闭线程池，让已提交的任务继续完成

                    # 等待任意一个任务完成
                    done, pending_futures = concurrent.futures.wait(
                        pending_futures,
                        timeout=1.0,
                        return_when=concurrent.futures.FIRST_COMPLETED
                    )

                    # 处理已完成的任务
                    for future in done:
                        product_id = future_to_product[future]
                        try:
                            result = future.result()
                            results['processed'] += 1

                            if result['status'] == 'success':
                                results['success'] += 1
                                logger.info(f"商品 {product_id} 处理成功")
                            elif result['status'] == 'skipped':
                                results['skipped'] += 1
                                logger.info(f"商品 {product_id} 已存在，跳过")
                            elif result['status'] == 'cancelled':
                                results['cancelled'] += 1
                                logger.info(f"商品 {product_id} 处理被取消")
                            elif result['status'] == 'partial':
                                results['partial'] += 1
                                logger.info(f"商品 {product_id} 部分完成（已入库，图片处理被取消）")
                            else:
                                results['errors'] += 1
                                logger.error(f"商品 {product_id} 处理失败: {result.get('message', '未知错误')}")

                        except Exception as e:
                            results['processed'] += 1
                            results['errors'] += 1
                            logger.error(f"处理商品 {product_id} 时发生异常: {e}")

                    # 如果检测到停止信号且没有待处理的任务，退出循环
                    if stop_detected and len(pending_futures) == 0:
                        logger.info("✅ 所有已提交的任务已完成，退出批量处理")
                        break

            except KeyboardInterrupt:
                logger.warning("收到键盘中断，正在优雅关闭...")
                executor.shutdown(wait=True, timeout=10.0)
                raise
            finally:
                # 确保线程池被正确关闭
                if not executor._shutdown:
                    executor.shutdown(wait=False)

        # 计算处理时间
        results['end_time'] = time.time()
        results['duration'] = results['end_time'] - results['start_time']

        logger.info(f"批量处理完成: {results}")

        # 注意：批量抓取不应该重置店铺抓取的状态
        # 批量抓取有自己的状态管理，不影响店铺抓取的状态显示

        return jsonify({
            'message': f'批量处理完成，共处理 {results["total"]} 个商品，成功 {results["success"]} 个，跳过 {results["skipped"]} 个，取消 {results["cancelled"]} 个，部分完成 {results["partial"]} 个，失败 {results["errors"]} 个',
            'results': results
        })

    except Exception as e:
        logger.error(f"批量抓取失败: {e}")
        logger.error(f"错误发生在: {e.__class__.__name__}")
        import traceback
        logger.error(f"完整堆栈:\n{traceback.format_exc()}")
        return jsonify({'error': f'批量抓取失败: {str(e)}'}), 500

@app.route('/api/scrape/shop/status', methods=['GET'])
def get_scrape_status():
    """获取抓取状态"""
    try:
        status = db.get_scrape_status()

        # 确保返回必要的字段（兼容前端期望的字段名）
        result = {
            'is_scraping': status.get('is_scraping', False),
            'progress': status.get('progress', 0),
            'total': status.get('total', 0),
            'current': status.get('processed', 0),  # 前端期望current字段
            'processed': status.get('processed', 0),
            'success': status.get('success', 0),
            'message': status.get('message', ''),
            'completed': status.get('completed', False),
            'current_shop_id': status.get('current_shop_id'),
            'thread_id': status.get('thread_id')
        }

        # 调试日志
        logger.debug(f"DEBUG: Scrape status - is_scraping: {result.get('is_scraping')}, message: {result.get('message')}")

        return jsonify(result)
    except Exception as e:
        logger.error(f'获取抓取状态失败: {e}')
        return jsonify({
            'is_scraping': False,
            'progress': 0,
            'total': 0,
            'current': 0,
            'processed': 0,
            'success': 0,
            'message': '获取状态失败',
            'completed': False,
            'current_shop_id': None,
            'thread_id': None
        })

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
    """后台任务包装器 - 调用真正的抓取逻辑"""
    try:
        logger.info(f"🧵 后台抓取线程启动: {shop_id}")
        scrape_shop_products(shop_id)
    except Exception as e:
        logger.error(f"❌ 后台抓取线程崩溃: {e}")
        db.update_scrape_status(message=f"系统错误: {str(e)}")
    finally:
        # 确保状态正确重置
        final_status = db.get_scrape_status()
        db.update_scrape_status(
            is_scraping=False,
            completed=True
        )
        if not final_status.get('stop_signal', False):
            db.update_scrape_status(message='任务结束')
        logger.info("🧵 后台抓取线程结束")

def scrape_shop_products(shop_id):
    """抓取店铺所有商品的实现 (全局线程池高性能版 - 每个商品一个线程)"""
    import requests
    import time
    from weidian_scraper import get_weidian_scraper
    import concurrent.futures

    # 获取配置的线程数
    try:
        from config import config
        max_threads = config.SCRAPE_THREADS
    except:
        max_threads = 2

    # 导入全局停止事件
    global scrape_stop_event

    scraper = get_weidian_scraper()
    unique_product_tasks = {}  # 使用字典去重：item_id -> product_info
    offset = 0
    limit = 20
    page_count = 0

    # 初始化状态
    db.update_scrape_status(
        is_scraping=True,
        paused=False,
        stop_signal=False,
        progress=0,
        total=0,
        processed=0,
        success=0,
        message='正在初始化...'
    )

    # 获取店铺名称
    shop_info = get_shop_info_from_api(shop_id)
    shop_name = shop_info.get('shopName', f'店铺 {shop_id}') if shop_info else f'店铺 {shop_id}'

    db.update_scrape_status(message=f'正在抓取店铺: {shop_name}')
    logger.info(f"开始收集商品列表，店铺: {shop_name}")

    # 第一阶段：收集所有商品信息（单线程，避免API压力）
    while True:
        # 检查停止事件或停止信号
        if scrape_stop_event.is_set():
            logger.info("🔴 停止事件触发，退出收集")
            break

        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.info("🔴 停止信号触发，退出收集")
            break

        try:
            # API 请求商品列表
            url = f"https://thor.weidian.com/decorate/shopDetail.tab.getItemList/1.0"
            param_encoded = quote(f'{{"shopId":"{shop_id}","tabId":0,"sortOrder":"desc","offset":{offset},"limit":{limit},"from":"h5","showItemTag":true}}')
            full_url = f"{url}?param={param_encoded}&wdtoken=8ea9315c&_={int(time.time()*1000)}"

            response = scraper.session.get(full_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f'API请求失败: {response.status_code}')
                break

            data = response.json()
            if data.get('status', {}).get('code') != 0:
                logger.warning('API响应状态码不为0')
                break

            result = data.get('result', {})
            if not result.get('hasData', False):
                logger.info('没有更多数据，收集完成')
                break

            items = result.get('itemList', [])
            if not items:
                logger.info('商品列表为空，收集完成')
                break

            # 收集当前页的商品任务 (内存去重)
            page_new_count = 0
            for item in items:
                item_id = item.get('itemId', '')
                if item_id and item_id not in unique_product_tasks:  # 内存去重
                    # 再次检查数据库是否已存在 (避免处理已抓过的)
                    if not db.get_product_by_item_id(item_id):
                        product_info = {
                            'item_id': item_id,
                            'item_url': item.get('itemUrl', ''),
                            'shop_name': shop_name
                        }
                        unique_product_tasks[item_id] = product_info
                        page_new_count += 1

            # === 新增：实时更新收集进度到数据库，让前端能看到 ===
            current_total = len(unique_product_tasks)
            db.update_scrape_status(
                total=current_total,
                message=f'正在收集商品... 第{page_count + 1}页，已找到 {current_total} 个新商品'
            )
            # =================================================

            logger.info(f'第 {page_count + 1} 页收集了 {len(items)} 个商品，其中 {page_new_count} 个新商品，总计 {len(unique_product_tasks)} 个待处理商品')

            page_count += 1
            offset += limit
            time.sleep(0.5)  # 稍微歇一下防止封IP

        except Exception as e:
            logger.error(f'收集商品列表出错: {e}')
            break

    # 转回列表用于处理
    all_product_tasks = list(unique_product_tasks.values())
    total_products = len(all_product_tasks)
    logger.info(f"✅ 商品收集完成，去重后待处理 {total_products} 个商品，准备使用 {max_threads} 个线程并发处理")

    # 更新状态：开始处理
    db.update_scrape_status(
        total=total_products,
        progress=0, # 重置进度条为0，开始第二阶段
        message=f'收集完成，准备并发处理 {total_products} 个商品...'
    )

    # 第二阶段：使用全局线程池并发处理所有商品
    processed_count = 0
    success_count = 0

    if all_product_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            # 提交所有商品任务到线程池
            future_to_product = {
                executor.submit(process_and_save_single_product_sync, product_info): product_info
                for product_info in all_product_tasks
            }

            # 处理完成的任务
            for future in concurrent.futures.as_completed(future_to_product):
                # 检查停止事件或停止信号
                if scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False):
                    logger.info("🔴 检测到停止事件/信号，正在取消剩余任务...")
                    # 取消所有待处理的任务
                    for f in future_to_product:
                        if not f.done():
                            f.cancel()
                    break

                try:
                    product_info = future_to_product[future]
                    success = future.result()
                    processed_count += 1

                    if success:
                        success_count += 1

                    # 改为每5个更新一次，反馈更及时
                    if processed_count % 5 == 0 or processed_count == total_products:
                        # 计算进度 (避免除以0)
                        progress = int((processed_count / total_products) * 100) if total_products > 0 else 100
                        db.update_scrape_status(
                            processed=processed_count,
                            success=success_count,
                            progress=progress,
                            message=f'正在抓取详情与图片... ({processed_count}/{total_products})'
                        )
                        logger.info(f'已处理 {processed_count}/{total_products} 个商品，成功 {success_count} 个')

                except Exception as e:
                    logger.error(f"商品处理异常: {e}")
                    processed_count += 1

    # 结束
    db.update_scrape_status(
        is_scraping=False,
        completed=True,
        progress=100,
        message=f'抓取完成，共处理 {processed_count} 个商品，成功 {success_count} 个'
    )
    logger.info(f"✅ 店铺 {shop_id} 抓取任务完成: {success_count}/{processed_count} 商品成功处理")

    return {
        "total_products": processed_count,
        "success_count": success_count,
        "pages_processed": page_count
    }

def process_and_save_single_product_sync(product_info):
    """同步处理单个商品，避免重复处理"""
    try:
        item_id = product_info.get('item_id', '')

        # === 检查停止事件或停止信号 ===
        global scrape_stop_event
        if scrape_stop_event.is_set():
            logger.info(f"🔴 处理商品前检测到停止事件，取消处理商品 {item_id}")
            return False

        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.info(f"🔴 处理商品前检测到停止信号，取消处理商品 {item_id}")
            return False

        # === 0. 基于item_id的强力去重 ===
        if db.get_product_by_item_id(item_id):
            logger.info(f"⏭️ 商品 {item_id} 已存在，跳过重复处理")
            return True  # 已存在算处理成功

        # 1. 抓取详情
        from app import process_single_product  # 引用 app.py 中的逻辑
        product_data = process_single_product(product_info)

        if not product_data:
            return False

        # === 再次检查停止状态 ===
        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.info(f"🔴 抓取详情后检测到停止信号，取消处理商品 {item_id}")
            return False

        # 2. 再次查重 (双重保险)
        if db.get_product_by_url(product_data['product_url']):
            logger.info(f"⏭️ 商品URL已存在: {product_data['product_url']}")
            return True  # 已存在算处理成功

        # 3. 入库 (添加item_id字段)
        product_data['item_id'] = item_id  # 确保item_id被保存
        product_id = db.insert_product(product_data)

        logger.info(f"✅ 商品 {item_id} 成功入库，数据库ID: {product_id}")

        # === 再次检查停止状态 ===
        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.info(f"🔴 入库后检测到停止信号，商品 {item_id} 已入库但跳过图片处理")
            return True  # 商品已入库，算成功

        # 4. 图片处理 (使用多线程版本)
        if product_data.get('images'):
            from app import save_product_images_unified
            processed_count = save_product_images_unified(product_id, product_data['images'])
            logger.info(f"🖼️ 商品 {item_id} 图片处理完成，共处理 {processed_count} 张图片")

        return True
    except Exception as e:
        logger.error(f"❌ 处理商品出错 {product_info.get('item_id')}: {e}")
        return False

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
                # 修复：移除 [:5] 限制，返回所有抓取到的图片
                'images': product_info.get('images', []),
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

        # 检查停止事件
        global scrape_stop_event
        if scrape_stop_event.is_set():
            logger.info(f"🔴 处理商品 {item_id} 时检测到停止事件，中止处理")
            return None

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
    max_workers = config.DOWNLOAD_THREADS

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
    max_workers = config.DOWNLOAD_THREADS

    logger.info(f'第 {page_num} 页开始多线程处理 {len(products_list)} 个商品')

    def process_and_save_product(product):
        """处理单个商品的完整流程：获取详情 -> 插入数据库 -> 下载图片"""
        try:
            # 1. 获取商品详情
            product_data = process_single_product(product)
            if not product_data:
                logger.warning(f'商品详情获取失败: {product}')
                return 0

            # 2. 检查商品是否已存在
            existing = db.get_product_by_url(product_data['product_url'])
            if existing:
                logger.info(f'商品已存在，跳过: {product_data["title"]} (URL: {product_data["product_url"]})')
                return 0

            # 3. 插入商品到数据库
            product_id = db.insert_product(product_data)
            logger.info(f'✅ 成功插入新商品: {product_data["title"]} (ID: {product_id})')

            # 4. 下载并保存图片
            if product_data.get('images'):
                save_product_images(product_id, product_data['images'])
                logger.info(f'📸 商品图片下载完成: {product_data["title"]} ({len(product_data["images"])}张)')

            return 1  # 成功处理一个商品

        except Exception as e:
            logger.error(f'处理商品失败: {e}')
            return 0

    # 降低并发数避免内存爆炸，YOLO模型现在是单例模式
    max_workers_page = min(2, len(products_list))  # 最多2个并发
    logger.info(f"页面处理使用 {max_workers_page} 个线程")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_page) as executor:
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
    """
    统一的图片保存入口（向后兼容的别名）
    实际调用 save_product_images_unified
    """
    return save_product_images_unified(product_id, image_urls)

def save_product_images_unified(product_id, image_urls, max_workers=None, shutdown_event=None):
    """
    统一的批量图片处理函数（优化版：延迟FAISS保存，提高性能）
    """
    if not image_urls:
        return 0

    try:
        import concurrent.futures

        # 动态决定线程数 (默认使用配置，但允许覆盖)
        if max_workers is None:
            max_workers = min(config.DOWNLOAD_THREADS, len(image_urls))

        # 获取现有特征向量用于查重
        existing_images = db.get_product_images(product_id)
        existing_feats = [img['features'] for img in existing_images if img['features']]
        logger.info(f'商品 {product_id} 已存在 {len(existing_feats)} 张图片的向量数据')

        # 处理结果计数
        processed_images = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务：注意这里 save_faiss_immediately=False，因为我们要批量保存
            futures = [executor.submit(process_and_save_image_core, product_id, url, idx, existing_feats, save_faiss_immediately=False)
                       for idx, url in enumerate(image_urls)]

            # 等待完成 (支持优雅关闭)
            for future in concurrent.futures.as_completed(futures):
                try:
                    # 检查停止信号
                    if shutdown_event and shutdown_event.is_set():
                        logger.info("检测到停止信号，正在等待图片处理完成...")
                        executor.shutdown(wait=True, timeout=15.0)
                        break

                    result = future.result()
                    if result and result.get('success'):
                        processed_images += 1  # 计数成功处理的图片

                except Exception as e:
                    logger.error(f'一个图片处理失败: {e}')

        # 批量操作结束后统一保存 FAISS（性能极大提升）
        if processed_images > 0:
            try:
                from vector_engine import get_vector_engine
                get_vector_engine().save()
                logger.info(f"FAISS索引已批量保存，本次新增 {processed_images} 张图片")

            except Exception as faiss_err:
                logger.error(f"FAISS保存失败: {faiss_err}")

        logger.info(f"商品 {product_id} 成功处理 {processed_images}/{len(image_urls)} 张图片")
        return processed_images

    except Exception as e:
        logger.error(f"批量保存商品 {product_id} 图片失败: {e}")
        return 0

def save_product_images_multithreaded(product_id, image_urls):
    """向后兼容的别名"""
    return save_product_images_unified(product_id, image_urls)

if __name__ == '__main__':
    import atexit
    import threading
    import signal
    import time

    # 全局变量用于控制优雅关闭
    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        """处理中断信号，优雅关闭"""
        print(f"\n🛑 Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()

        # 设置抓取状态为停止
        current_status = db.get_scrape_status()
        if current_status.get('is_scraping', False):
            db.update_scrape_status(
                stop_signal=True,
                message='系统正在关闭，已停止抓取任务'
            )
            print("⏹️  已停止所有抓取任务")

        # 等待抓取线程结束（最多等待10秒）
        global current_scrape_thread, scrape_thread_lock
        with scrape_thread_lock:
            if current_scrape_thread and current_scrape_thread.is_alive():
                print("⏳ 等待抓取线程结束...")
                current_scrape_thread.join(timeout=10.0)
                if current_scrape_thread.is_alive():
                    print("⚠️ 抓取线程未能在10秒内结束")
                else:
                    print("✅ 抓取线程已结束")

        # 立即停止Discord机器人
        stop_discord_bot()

        # 短暂等待让其他线程有机会清理
        time.sleep(0.2)
        print("💥 Force exiting...")
        import os
        os._exit(0)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 注册退出时停止机器人的函数
    atexit.register(stop_discord_bot)

    # ====================================================
    # 新增修复：启动时强制重置数据库抓取状态
    # ====================================================
    print("🧹 [系统] 正在重置抓取任务状态...")
    try:
        # 强制将所有正在运行的状态重置为停止
        db.update_scrape_status(
            is_scraping=False,
            stop_signal=False,
            message='系统重启，任务状态已重置'
        )
        print("✅ [系统] 抓取状态已重置，随时可以开始新任务")
    except Exception as e:
        print(f"⚠️ [系统] 状态重置失败 (可能是第一次运行数据库未初始化): {e}")

    # 3. 在主线程预加载模型 (关键)
    print("🤖 [系统] 正在预热 AI 引擎，请稍候...")
    try:
        from feature_extractor import get_feature_extractor
        # 强制获取一次实例，触发初始化
        get_feature_extractor()
        print("✅ [系统] AI 引擎预热完成，多线程任务将共享此实例")
    except Exception as e:
        print(f"⚠️ [系统] AI 预热失败: {e}")

    # 4. 启动 Flask
    print("🚀 服务启动中...")
    try:
        # 关闭 debug 模式，避免 Flask 重载器导致双重初始化
        app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 Received KeyboardInterrupt, shutting down...")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        signal_handler(signal.SIGINT, None)
    finally:
        print("👋 Flask API shutdown complete")
