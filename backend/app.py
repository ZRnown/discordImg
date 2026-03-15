# ============================================================
# 【启动稳定性修复】必须在 import torch 之前设置线程/代理环境变量
# 避免 OpenMP 与多线程冲突导致 Socket 关闭
# ============================================================
import os
import multiprocessing  # Windows多进程兼容性必需

if 'AI_INTRA_THREADS' not in os.environ:
    os.environ['AI_INTRA_THREADS'] = '1'
_ai_threads = os.environ.get('AI_INTRA_THREADS', '1')
os.environ["OMP_NUM_THREADS"] = _ai_threads
os.environ["MKL_NUM_THREADS"] = _ai_threads
os.environ["OPENBLAS_NUM_THREADS"] = _ai_threads
os.environ["VECLIB_MAXIMUM_THREADS"] = _ai_threads
os.environ["NUMEXPR_NUM_THREADS"] = _ai_threads
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("TORCH_CPP_LOG_LEVEL", "ERROR")
os.environ.setdefault("TORCH_SHOW_CPP_STACKTRACES", "0")
os.environ.setdefault("GLOG_minloglevel", "2")

from flask import Flask, request, jsonify, Response, session
import numpy as np
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
except ModuleNotFoundError as e:
    if e.name == 'feature_extractor':
        from .feature_extractor import get_feature_extractor, DINOv2FeatureExtractor
    else:
        raise
try:
    from database import db
    from config import config
except ModuleNotFoundError as e:
    if e.name in {'database', 'config'}:
        from .database import db
        from .config import config
    else:
        raise
import requests
import json
from flask_cors import CORS
import queue
import threading
import time
from urllib.parse import quote
import hashlib
import uuid

# === 全局状态变量 ===
ai_model_ready = False  # AI模型是否已就绪
# 全局 AI 并发控制（跨商品），避免 CPU 被同时推理任务打满
GLOBAL_AI_SEMAPHORE = threading.Semaphore(4)

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
        # 确保 new_features 是 1D 数组
        new_features = np.array(new_features, dtype='float32').flatten()

        # 预计算新向量的范数
        norm_new = float(np.linalg.norm(new_features))
        if norm_new == 0:
            return False, 0.0

        for feat_item in existing_features_list:
            try:
                # 处理输入可能是 JSON 字符串或已经是 numpy 数组的情况
                if isinstance(feat_item, str):
                    feat_vec = np.array(json.loads(feat_item), dtype='float32').flatten()
                else:
                    feat_vec = np.array(feat_item, dtype='float32').flatten()

                norm_existing = float(np.linalg.norm(feat_vec))
                if norm_existing == 0:
                    continue

                # 计算余弦相似度
                dot_product = float(np.dot(new_features, feat_vec))
                similarity = dot_product / (norm_new * norm_existing)

                if similarity > threshold:
                    return True, float(similarity)

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

# 【修复】移除全局 load_system_config() 调用，防止子进程重复初始化
# load_system_config() 现在在 initialize_runtime() 中调用

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

# 【修复】移除全局日志配置，防止子进程重复初始化
# 日志配置现在在 initialize_runtime() 中执行

# 日志队列和客户端列表（数据结构，需要在全局）
# 注意：日志队列仅用于调试缓冲，必须避免无限增长导致内存膨胀
log_queue = queue.Queue(maxsize=5000)
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
            if len(all_logs) > 500:  # 最多保存500条日志
                all_logs.pop(0)

            try:
                log_queue.put_nowait(log_entry)
            except queue.Full:
                # 队列满时丢弃最旧日志，确保日志处理不阻塞主业务线程
                try:
                    log_queue.get_nowait()
                    log_queue.put_nowait(log_entry)
                except Exception:
                    pass

            # 通知所有连接的客户端
            for client_queue in log_clients[:]:  # 复制列表以避免修改时的问题
                try:
                    client_queue.put_nowait(log_entry)
                except queue.Full:
                    # 客户端消费过慢，移除该连接避免阻塞
                    if client_queue in log_clients:
                        log_clients.remove(client_queue)
                except Exception:
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

# 【修复】移除全局队列处理器和日志级别设置，防止子进程重复初始化
# 这些配置现在在 initialize_runtime() 中执行

logger = logging.getLogger(__name__)

# 机器人相关变量
# [修改] 从 bot 模块导入列表，确保 app.py 和 bot.py 操作同一个列表对象
from bot import bot_clients, bot_tasks, get_all_cooldowns
bot_running = False  # 标记机器人是否正在运行
bot_loop = None  # 机器人事件循环
bot_thread = None  # 机器人事件循环线程

def build_user_shop_scope(user_id):
    """构建用户可访问店铺集合（同时包含店铺ID与店铺名）"""
    if not user_id:
        return []

    user = db.get_user_by_id(user_id)
    if not user:
        return []

    user_shops = user.get('shops', []) or []
    allowed_shops = set()
    for shop_id in user_shops:
        if not shop_id:
            continue
        allowed_shops.add(str(shop_id))
        shop_info = db.get_shop_by_id(str(shop_id))
        if shop_info and shop_info.get('name'):
            allowed_shops.add(str(shop_info['name']))

    return list(allowed_shops)

def refresh_running_bot_user_shops(user_id):
    """更新运行中 Bot 的 user_shops，避免修改绑定后需要重启进程"""
    scoped_shops = build_user_shop_scope(user_id)
    updated_clients = 0

    for client in bot_clients:
        if getattr(client, 'user_id', None) == user_id:
            client.user_shops = scoped_shops
            updated_clients += 1

    return updated_clients, scoped_shops

# 全局特征提取器实例（在应用启动时创建）
feature_extractor_instance = None
feature_extractor_lock = threading.Lock()
feature_extractor_failed_at = 0.0

def initialize_feature_extractor():
    """在应用启动时初始化特征提取器，确保单例模式"""
    global feature_extractor_instance, feature_extractor_failed_at
    if feature_extractor_instance is None:
        with feature_extractor_lock:
            if feature_extractor_instance is None:
                if feature_extractor_failed_at:
                    now = time.time()
                    if now - feature_extractor_failed_at < 60:
                        print("⚠️ 特征提取器初始化失败后冷却中，稍后再试")
                        return None
                print("🚀 初始化全局特征提取器实例...")
                try:
                    from feature_extractor import DINOv2FeatureExtractor
                    feature_extractor_instance = DINOv2FeatureExtractor()
                    print("✅ 全局特征提取器实例初始化完成")
                except Exception as e:
                    print(f"❌ 特征提取器初始化失败: {e}")
                    feature_extractor_instance = None
                    feature_extractor_failed_at = time.time()
    return feature_extractor_instance

def get_global_feature_extractor():
    """获取全局特征提取器实例"""
    global feature_extractor_instance
    if feature_extractor_instance is None:
        return initialize_feature_extractor()
    return feature_extractor_instance

# 在应用启动时初始化
# 【修复】注释掉模块级别的初始化，避免多进程环境下重复初始化
# 实际的初始化在 if __name__ == '__main__' 块中的预热阶段执行
# initialize_feature_extractor()

# 【新增】定义项目内的临时文件目录 (在 backend/data/tmp)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, 'data', 'tmp')
# 确保目录存在
os.makedirs(TEMP_DIR, exist_ok=True)

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

def initialize_runtime():
    """
    初始化运行时环境 (日志、配置等)
    只在主进程中执行，防止子进程重复初始化
    """
    print(f"🔧 [系统] 正在初始化运行时环境 (PID: {os.getpid()})...")

    # 1. 加载系统配置
    load_system_config()

    # 2. 配置日志系统
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 清除现有的所有处理器（防止重复）
    if root_logger.handlers:
        root_logger.handlers = []

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 创建并添加队列处理器
    queue_handler = QueueHandler()
    queue_handler.setLevel(logging.INFO)
    root_logger.addHandler(queue_handler)

    # 屏蔽噪音日志
    for lib in ['werkzeug', 'requests', 'ultralytics', 'aiohttp']:
        logging.getLogger(lib).setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)

    # 3. 重置数据库状态
    print("🧹 [系统] 正在重置抓取任务状态...")
    try:
        db.update_scrape_status(
            is_scraping=False,
            stop_signal=False,
            message='系统重启，任务状态已重置'
        )
        # 重置所有Discord账号状态为离线
        with db.get_connection() as conn:
            conn.execute("UPDATE discord_accounts SET status = 'offline'")
            conn.commit()
        print("✅ [系统] 数据库状态已重置")
    except Exception as e:
        print(f"⚠️ [系统] 状态重置失败: {e}")

    # 4. 【异步】预热AI模型（不阻塞Flask启动）
    import threading
    def async_warmup_ai():
        global ai_model_ready
        try:
            print("🤖 [后台] 正在预热AI模型...")
            get_global_feature_extractor()
            ai_model_ready = True
            print("✅ [后台] AI模型预热完成，系统已就绪")
        except Exception as e:
            print(f"⚠️ [后台] AI预热失败: {e}")
            ai_model_ready = False

    ai_warmup_thread = threading.Thread(target=async_warmup_ai, daemon=True)
    ai_warmup_thread.start()
    print("🚀 [系统] AI模型正在后台预热，Flask服务即将启动...")

    # 5. 启动后台清理线程
    cleanup_thread = threading.Thread(target=run_cleanup_task, daemon=True)
    cleanup_thread.start()
    logger.info("🚀 后台清理任务已启动")

    print(f"✅ [系统] 运行时环境初始化完成")

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
        debug_enabled = bool(getattr(config, 'DEBUG', False))

        user_id = request.form.get('user_id')
        if user_id:
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                user_id = None

        # 获取用户店铺权限过滤（用于Discord机器人）
        user_shops = None
        user_shops_json = request.form.get('user_shops')
        if user_shops_json:
            try:
                user_shops = json.loads(user_shops_json)
            except:
                user_shops = None
        if user_shops is None and user_id:
            user_shops = build_user_shop_scope(user_id)

        if debug_enabled:
            logger.debug(f"Received threshold: {threshold}")
            logger.debug(f"User shops filter: {user_shops}")
            logger.debug(f"Form data: {list(request.form.keys())}")
            logger.debug(f"Files: {list(request.files.keys()) if request.files else 'No files'}")
            logger.debug(f"Content-Type: {request.content_type}")
            logger.debug(f"Method: {request.method}")
            logger.debug(f"image_url parameter: '{image_url}'")

        # 处理图片来源
        import uuid
        import os
        image_file = None  # 初始化变量，避免作用域问题

        if image_url:
            if debug_enabled:
                logger.debug(f"Processing image URL: {image_url}")
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
                if debug_enabled:
                    logger.debug(f"URL response status: {response.status_code}")
                    logger.debug(f"Content-Type: {response.headers.get('content-type', 'unknown')}")

                if response.status_code != 200:
                    return jsonify({'error': f'Failed to download image from URL, status: {response.status_code}'}), 400

                # 检查内容类型
                content_type = response.headers.get('content-type', '').lower()
                if not any(img_type in content_type for img_type in ['image/', 'application/octet-stream']):
                    if debug_enabled:
                        logger.debug(f"Warning - Content-Type '{content_type}' may not be an image")

                temp_filename = f"{uuid.uuid4()}.jpg"
                # 【修改】使用项目目录下的 TEMP_DIR
                image_path = os.path.join(TEMP_DIR, temp_filename)

                with open(image_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # 检查文件大小
                file_size = os.path.getsize(image_path)
                if debug_enabled:
                    logger.debug(f"Image downloaded to: {image_path}, size: {file_size} bytes")

                if file_size == 0:
                    os.remove(image_path)
                    return jsonify({'error': 'Downloaded file is empty'}), 400

                if file_size > 10 * 1024 * 1024:  # 10MB limit
                    os.remove(image_path)
                    return jsonify({'error': 'Image file too large (max 10MB)'}), 400

            except requests.exceptions.RequestException as e:
                if debug_enabled:
                    logger.debug(f"Network error downloading image: {str(e)}")
                return jsonify({'error': f'Network error downloading image: {str(e)}'}), 400
            except Exception as e:
                if debug_enabled:
                    logger.debug(f"Failed to download image: {str(e)}")
                return jsonify({'error': f'Failed to download image: {str(e)}'}), 400
        elif 'image' in request.files:
            if debug_enabled:
                logger.debug("No image_url provided, checking for uploaded file")
            image_file = request.files['image']
            if debug_enabled:
                logger.debug(f"Found uploaded file: {image_file.filename if image_file else 'None'}")

            temp_filename = f"{uuid.uuid4()}.jpg"
            # 【修改】使用项目目录下的 TEMP_DIR
            image_path = os.path.join(TEMP_DIR, temp_filename)
            image_file.save(image_path)

        else:
            if debug_enabled:
                logger.debug("No image_url and no uploaded file")
            return jsonify({'error': 'No image provided (url or file)'}), 400

        try:
            # 提取特征 (使用 DINOv2 + YOLOv8)
            query_features = extract_features(image_path)

            if query_features is None:
                return jsonify({'error': 'Feature extraction failed'}), 500

            query_vec = np.array(query_features, dtype='float32')
            q_norm = np.linalg.norm(query_vec)
            if q_norm > 0:
                query_vec = query_vec / q_norm

            # === 图片过滤规则匹配（基于上传图片） ===
            blocked_filter_match = None
            blocked_website_filter_matches = []
            try:
                image_filters = db.get_message_filters()
                image_filters = [f for f in (image_filters or []) if f.get('filter_type') == 'image_filter']
                if image_filters:
                    best_match = None
                    best_similarity = -1.0
                    for filter_rule in image_filters:
                        try:
                            threshold_val = float(filter_rule.get('filter_value') or 0.95)
                        except (TypeError, ValueError):
                            threshold_val = 0.95
                        filter_images = db.get_message_filter_images(filter_rule.get('id'), include_features=True)
                        if not filter_images:
                            continue
                        local_best = None
                        local_best_sim = -1.0
                        for item in filter_images:
                            feats = item.get('features') or []
                            if not feats:
                                continue
                            vec = np.array(feats, dtype='float32')
                            v_norm = np.linalg.norm(vec)
                            if v_norm > 0:
                                vec = vec / v_norm
                            sim = float(np.dot(query_vec, vec))
                            if sim > local_best_sim:
                                local_best_sim = sim
                                local_best = item
                        if local_best is not None and local_best_sim >= threshold_val:
                            if local_best_sim > best_similarity:
                                best_similarity = local_best_sim
                                best_match = {
                                    'filter_id': filter_rule.get('id'),
                                    'image_id': local_best.get('id'),
                                    'similarity': local_best_sim,
                                    'threshold': threshold_val
                                }
                    blocked_filter_match = best_match
            except Exception as e:
                logger.error(f"图片过滤匹配失败: {e}")

            # === 网站级图片过滤规则匹配 ===
            try:
                if user_id:
                    website_settings = db.get_all_user_website_filters(user_id)
                    best_by_website = {}
                    for setting in website_settings or []:
                        website_id = setting.get('website_id')
                        try:
                            filters = json.loads(setting.get('message_filters', '[]'))
                        except Exception:
                            filters = []

                        for filter_rule in filters:
                            if not isinstance(filter_rule, dict):
                                continue
                            if filter_rule.get('filter_type') != 'image_filter':
                                continue
                            filter_id = filter_rule.get('id')
                            if not filter_id:
                                continue
                            try:
                                threshold_val = float(filter_rule.get('filter_value') or 0.95)
                            except (TypeError, ValueError):
                                threshold_val = 0.95

                            filter_images = db.get_website_filter_images(
                                user_id,
                                website_id,
                                str(filter_id),
                                include_features=True
                            )
                            if not filter_images:
                                continue

                            local_best = None
                            local_best_sim = -1.0
                            for item in filter_images:
                                feats = item.get('features') or []
                                if not feats:
                                    continue
                                vec = np.array(feats, dtype='float32')
                                v_norm = np.linalg.norm(vec)
                                if v_norm > 0:
                                    vec = vec / v_norm
                                sim = float(np.dot(query_vec, vec))
                                if sim > local_best_sim:
                                    local_best_sim = sim
                                    local_best = item

                            if local_best is not None and local_best_sim >= threshold_val:
                                prev = best_by_website.get(website_id)
                                if not prev or local_best_sim > prev.get('similarity', -1):
                                    best_by_website[website_id] = {
                                        'website_id': website_id,
                                        'filter_id': filter_id,
                                        'image_id': local_best.get('id'),
                                        'similarity': local_best_sim,
                                        'threshold': threshold_val
                                    }

                    blocked_website_filter_matches = list(best_by_website.values())
            except Exception as e:
                logger.error(f"网站图片过滤匹配失败: {e}")

            # 记录用户搜索次数（未登录则跳过，不影响机器人调用）
            try:
                current_user = get_current_user()
                if current_user:
                    db.increment_user_image_search_count(current_user['id'])
            except Exception as e:
                logger.error(f"记录用户搜索次数失败: {e}")

            # 【优化】使用 FAISS HNSW 向量搜索 + 综合评分重排序
            if debug_enabled:
                logger.debug(f"Searching with threshold: {threshold}, vector length: {len(query_features)}")

            # 1. 扩大召回范围：FAISS 先找前 50 个候选 (Primary Search)
            # 使用较低的阈值召回，防止漏掉可能的匹配
            candidates_limit = 50
            raw_results = db.search_similar_images(query_features, limit=candidates_limit, threshold=0.05)
            if debug_enabled:
                logger.debug(f"FAISS recalled {len(raw_results) if raw_results else 0} candidates")

            # 2. 重排序 (Re-ranking) - 综合评分
            refined_results = []

            if raw_results:
                # 获取全局特征提取器实例用来计算颜色/结构
                extractor = get_global_feature_extractor()
                query_signature = extractor.prepare_hybrid_query(image_path) if extractor else None

                for res in raw_results:
                    # 获取候选图片的本地路径
                    candidate_img_path = res.get('image_path')

                    # 如果文件不存在，只能用原始 DINO 分数
                    if not candidate_img_path or not os.path.exists(candidate_img_path):
                        final_score = res['similarity']
                        breakdown = {}
                        if debug_enabled:
                            logger.debug(f"Candidate image not found, using DINO score: {final_score:.3f}")
                    else:
                        # 计算综合评分
                        hybrid_data = extractor.calculate_hybrid_similarity(
                            image_path,  # 上传的查询图 (临时文件)
                            candidate_img_path,  # 数据库里的图
                            res['similarity'],  # 原始 DINO 分数
                            query_signature
                        )
                        final_score = hybrid_data['score']
                        breakdown = hybrid_data.get('details', {})

                    # 更新分数
                    res['original_similarity'] = res['similarity']  # 保留原分用于调试
                    res['similarity'] = final_score  # 更新为综合分
                    res['score_breakdown'] = breakdown

                    refined_results.append(res)

                # 3. 按新的综合分数重新排序
                refined_results.sort(key=lambda x: x['similarity'], reverse=True)
                if debug_enabled:
                    logger.debug(f"Re-ranking completed, best score: {refined_results[0]['similarity']:.3f}")

            # 4. 应用用户阈值和店铺过滤
            results = []
            for result in refined_results:
                similarity = result.get('similarity', 0)
                # 应用用户相似度阈值
                if similarity >= threshold:
                    # 检查店铺权限
                    if user_shops and result.get('shop_name') not in user_shops:
                        if debug_enabled:
                            logger.debug(f"Skipping result from shop {result.get('shop_name')} - not in user shops {user_shops}")
                        continue
                    results.append(result)
                    if len(results) >= limit:
                        break

            if debug_enabled:
                logger.debug(f"Filtered results count (threshold {threshold}): {len(results)}")
                if results:
                    logger.debug(
                        f"Best match similarity: {results[0]['similarity']:.3f} (original DINO: {results[0].get('original_similarity', 0):.3f})"
                    )
                logger.debug(f"Total indexed images: {db.get_total_indexed_images()}")

            # 严格执行阈值：如果没有满足阈值的结果，则返回空结果
            # 不再使用任何硬编码阈值兜底（例如 >0.8）

            response_data = {
                'success': True,
                'results': [],
                'totalResults': 0,
                'message': f'未找到相似度超过{threshold*100:.0f}%的商品',
                'searchTime': datetime.now().isoformat(),
                'blocked_filter_match': blocked_filter_match,
                'blocked_website_filter_matches': blocked_website_filter_matches,
                'debugInfo': {
                    'totalIndexedImages': db.get_total_indexed_images(),
                    'threshold': threshold,
                    'searchedVectors': len(results) if results else 0
                }
            }

            if results:
                # 处理多个搜索结果
                processed_results = []

                # 预先导入 json，防止循环中报错
                import json

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

                    selected_indexes = []
                    custom_urls = []
                    uploaded_reply_images = []
                    try:
                        if product_info and product_info.get('custom_reply_images'):
                            selected_indexes = json.loads(product_info.get('custom_reply_images') or '[]')
                        if product_info and product_info.get('custom_image_urls'):
                            custom_urls = json.loads(product_info.get('custom_image_urls') or '[]')
                        if product_info and product_info.get('uploaded_reply_images'):
                            uploaded_reply_images = json.loads(product_info.get('uploaded_reply_images') or '[]')
                    except Exception:
                        selected_indexes = []
                        custom_urls = []
                        uploaded_reply_images = []

                    result_data = {
                        'rank': i + 1,
                        'similarity': float(result['similarity']),
                        'originalSimilarity': float(result.get('original_similarity', result['similarity'])),  # 原始DINO分数
                        'scoreBreakdown': result.get('score_breakdown', {}),  # 评分详情
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
                            # 修复：机器人需要 imageSource 和 uploaded_reply_images 才能发送本地图片
                            'imageSource': product_info.get('image_source', 'product') if product_info else 'product',
                            'custom_reply_text': product_info.get('custom_reply_text', '') if product_info else '',
                            'replyScope': product_info.get('reply_scope', 'all') if product_info else 'all',
                            'uploaded_reply_images': uploaded_reply_images,
                            'selectedImageIndexes': selected_indexes,
                            'customImageUrls': custom_urls,
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
                    'blocked_filter_match': blocked_filter_match,
                    'blocked_website_filter_matches': blocked_website_filter_matches,
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
        data = request.get_json(silent=True) or {}
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

        item_id = None
        if weidian_id:
            item_id = str(weidian_id)
        else:
            try:
                import re
                item_id_match = re.search(r'itemID=(\d+)', url)
                if item_id_match:
                    item_id = item_id_match.group(1)
            except Exception:
                item_id = None

        # 先按item_id去重，避免无效抓取
        if item_id and db.get_product_by_item_id(item_id):
            return jsonify({'error': '商品已存在', 'existing': True}), 409

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

@app.route('/api/bot/cooldowns', methods=['GET'])
def get_bot_cooldowns():
    """获取当前所有账号的冷却状态"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        cooldowns = get_all_cooldowns()
        return jsonify({'cooldowns': cooldowns})
    except Exception as e:
        logger.error(f"获取冷却状态失败: {e}")
        return jsonify({'cooldowns': []}), 500

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

        username = data['username'].strip()
        password = data['password'].strip()
        role = data.get('role', 'user')
        shop_ids = data.get('shops', [])

        if len(password) < 6:
            return jsonify({'error': '密码长度至少6位'}), 400

        from werkzeug.security import generate_password_hash
        password_hash = generate_password_hash(password)

        if db.create_user(username, password_hash, role):
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, username, role, is_active, image_search_count, created_at FROM users WHERE username = ?", (username,))
                user = cursor.fetchone()

            if user:
                user_dict = dict(user)
                if shop_ids:
                    db.update_user_shops(user_dict['id'], shop_ids)
                return jsonify({'user': user_dict, 'message': '用户创建成功'})
            else:
                return jsonify({'error': '用户创建后无法检索信息'}), 500
        else:
            return jsonify({'error': '用户名已存在或数据库错误'}), 400
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

        from werkzeug.security import generate_password_hash
        password_hash = generate_password_hash(new_password)

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
    """获取所有网站配置及其用户相关的频道绑定和账号绑定"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        configs = db.get_website_configs()

        # 为每个配置添加绑定信息
        for config in configs:
            config_id = config['id']

            # 1) 账号绑定：只返回当前用户自己的绑定
            config['accounts'] = db.get_website_account_bindings(config_id, current_user['id'])

            # 2) 频道绑定：只返回当前用户自己的绑定
            config['channels'] = db.get_website_channel_bindings(config_id, current_user['id'])

            # 3) 用户级别的轮换设置
            user_settings = db.get_user_website_settings(current_user['id'], config_id)
            config['rotation_interval'] = user_settings.get('rotation_interval', 180)
            config['rotation_enabled'] = user_settings.get('rotation_enabled', 1)
            config['keyword_reply_batch_size'] = user_settings.get('keyword_reply_batch_size', 0)
            try:
                raw_filters = user_settings.get('message_filters', '[]') if user_settings else '[]'
                config['message_filters'] = json.loads(raw_filters) if isinstance(raw_filters, str) else (raw_filters or [])
            except Exception:
                config['message_filters'] = []
            user_threshold = user_settings.get('image_similarity_threshold') if user_settings else None
            if user_threshold is not None:
                config['image_similarity_threshold'] = user_threshold

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
        reply_template = data.get('reply_template') or '{url}'
        image_similarity_threshold = data.get('image_similarity_threshold', None)
        blocked_role_ids = data.get('blocked_role_ids', None)

        if not all([name, display_name, url_template, id_pattern]):
            return jsonify({'error': '所有字段都是必填的'}), 400

        def _normalize_similarity(value):
            if value is None or value == '':
                return None
            try:
                val = float(value)
            except (TypeError, ValueError):
                raise ValueError('相似度必须是数字')
            if not (0.0 <= val <= 1.0):
                raise ValueError('相似度必须在0.0-1.0之间')
            return val

        def _normalize_blocked_roles(value):
            if value is None:
                return '[]'
            roles = []
            if isinstance(value, list):
                roles = [str(r).strip() for r in value if str(r).strip()]
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        roles = [str(r).strip() for r in parsed if str(r).strip()]
                    else:
                        roles = [s.strip() for s in value.split(',') if s.strip()]
                except Exception:
                    roles = [s.strip() for s in value.split(',') if s.strip()]
            return json.dumps(roles, ensure_ascii=False)

        try:
            image_similarity_threshold = _normalize_similarity(image_similarity_threshold)
            blocked_role_ids = _normalize_blocked_roles(blocked_role_ids)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        if db.add_website_config(
            name,
            display_name,
            url_template,
            id_pattern,
            badge_color,
            reply_template,
            image_similarity_threshold,
            blocked_role_ids
        ):
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
        reply_template = data.get('reply_template') or '{url}'
        image_similarity_threshold = data.get('image_similarity_threshold', None)
        blocked_role_ids = data.get('blocked_role_ids', None)

        if not all([name, display_name, url_template, id_pattern]):
            return jsonify({'error': '所有字段都是必填的'}), 400

        def _normalize_similarity(value):
            if value is None or value == '':
                return None
            try:
                val = float(value)
            except (TypeError, ValueError):
                raise ValueError('相似度必须是数字')
            if not (0.0 <= val <= 1.0):
                raise ValueError('相似度必须在0.0-1.0之间')
            return val

        def _normalize_blocked_roles(value):
            if value is None:
                return '[]'
            roles = []
            if isinstance(value, list):
                roles = [str(r).strip() for r in value if str(r).strip()]
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        roles = [str(r).strip() for r in parsed if str(r).strip()]
                    else:
                        roles = [s.strip() for s in value.split(',') if s.strip()]
                except Exception:
                    roles = [s.strip() for s in value.split(',') if s.strip()]
            return json.dumps(roles, ensure_ascii=False)

        try:
            image_similarity_threshold = _normalize_similarity(image_similarity_threshold)
            blocked_role_ids = _normalize_blocked_roles(blocked_role_ids)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        if db.update_website_config(
            config_id,
            name,
            display_name,
            url_template,
            id_pattern,
            badge_color,
            reply_template,
            image_similarity_threshold,
            blocked_role_ids
        ):
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
    """获取网站绑定的频道（按用户过滤）"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        channels = db.get_website_channel_bindings(config_id, current_user['id'])
        return jsonify({'channels': channels})
    except Exception as e:
        logger.error(f"获取网站频道失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/channels', methods=['POST'])
def add_website_channel(config_id):
    """添加网站频道绑定"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json()
        channel_id = data.get('channel_id')

        if not channel_id:
            return jsonify({'error': '频道ID不能为空'}), 400

        # 【修复】如果输入的是完整的Discord URL，提取频道ID
        # Discord URL格式: https://discord.com/channels/{server_id}/{channel_id}
        if 'discord.com/channels/' in channel_id:
            # 提取URL中的最后一部分作为频道ID
            parts = channel_id.rstrip('/').split('/')
            if len(parts) >= 1:
                channel_id = parts[-1]

        # 验证频道ID是否为纯数字
        if not channel_id.isdigit():
            return jsonify({'error': '无效的频道ID格式'}), 400

        current_user = get_current_user()
        if db.add_website_channel_binding(config_id, channel_id, current_user['id']):
            return jsonify({'success': True, 'message': '频道绑定已添加'})
        else:
            return jsonify({'error': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加网站频道绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/channels/<channel_id>', methods=['DELETE'])
def remove_website_channel(config_id, channel_id):
    """移除网站频道绑定"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        # 【修复】如果channel_id是完整的Discord URL，提取频道ID
        # Discord URL格式: https://discord.com/channels/{server_id}/{channel_id}
        if 'discord.com/channels/' in channel_id:
            # 提取URL中的最后一部分作为频道ID
            parts = channel_id.rstrip('/').split('/')
            if len(parts) >= 1:
                channel_id = parts[-1]

        current_user = get_current_user()

        # 【修复】管理员可以删除任何频道，普通用户只能删除自己的
        if current_user.get('role') == 'admin':
            # 管理员：删除该频道的所有绑定
            success = db.remove_website_channel_binding_admin(config_id, channel_id)
        else:
            # 普通用户：只删除自己的绑定
            success = db.remove_website_channel_binding(config_id, channel_id, current_user['id'])

        if success:
            return jsonify({'success': True, 'message': '频道绑定已移除'})
        else:
            return jsonify({'error': '移除失败'}), 500
    except Exception as e:
        logger.error(f"移除网站频道绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

# ===== 网站账号绑定API =====

@app.route('/api/websites/<int:config_id>/accounts', methods=['GET'])
def get_website_accounts(config_id):
    """获取网站绑定的账号（按用户过滤）"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        accounts = db.get_website_account_bindings(config_id, current_user['id'])
        return jsonify({'accounts': accounts})
    except Exception as e:
        logger.error(f"获取网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/accounts', methods=['POST'])
def add_website_account(config_id):
    """为网站绑定账号"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json()
        account_id = data.get('account_id')
        role = data.get('role', 'both')  # 'listener', 'sender', 'both'

        if not account_id or role not in ['listener', 'sender', 'both']:
            return jsonify({'error': '无效的账号ID或角色'}), 400

        # 权限检查：确保该账号属于当前用户
        current_user = get_current_user()
        # 获取该账号的详情
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM discord_accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': '账号不存在'}), 404

            account_owner_id = row[0]

            # 如果不是管理员，且账号不属于当前用户，拒绝
            if current_user['role'] != 'admin' and account_owner_id != current_user['id']:
                return jsonify({'error': '您无权操作此账号'}), 403

        if db.add_website_account_binding(config_id, account_id, role, current_user['id']):
            return jsonify({'success': True, 'message': f'账号绑定成功，角色: {role}'})
        else:
            return jsonify({'error': '绑定失败'}), 500
    except Exception as e:
        logger.error(f"添加网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/accounts/<int:account_id>', methods=['DELETE'])
def remove_website_account(config_id, account_id):
    """移除网站账号绑定"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        if db.remove_website_account_binding(config_id, account_id, current_user['id']):
            return jsonify({'success': True, 'message': '账号绑定已移除'})
        else:
            return jsonify({'error': '移除失败'}), 500
    except Exception as e:
        logger.error(f"移除网站账号绑定失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/rotation', methods=['GET'])
def get_website_rotation(config_id):
    """获取用户的网站轮换配置"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        settings = db.get_user_website_settings(current_user['id'], config_id)
        return jsonify({
            'rotation_interval': settings['rotation_interval'],
            'rotation_enabled': settings['rotation_enabled'],
            'keyword_reply_batch_size': settings.get('keyword_reply_batch_size', 0)
        })
    except Exception as e:
        logger.error(f"获取网站轮换配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/rotation', methods=['PUT'])
def update_website_rotation(config_id):
    """更新用户的网站轮换配置（间隔和启用状态）"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        data = request.get_json()
        messages = []

        rotation_interval = data.get('rotation_interval')
        rotation_enabled = data.get('rotation_enabled')
        keyword_reply_batch_size = data.get('keyword_reply_batch_size')

        # 验证参数
        if rotation_interval is not None and rotation_interval <= 0:
            return jsonify({'error': '轮换间隔必须大于0秒'}), 400
        if rotation_enabled is not None and rotation_enabled not in [0, 1]:
            return jsonify({'error': '轮换启用状态必须是0或1'}), 400
        if keyword_reply_batch_size is not None and keyword_reply_batch_size < 0:
            return jsonify({'error': '每轮关键词回复数不能小于0'}), 400

        # 使用用户级别的设置方法
        if db.update_user_website_rotation(
            current_user['id'],
            config_id,
            rotation_interval,
            rotation_enabled,
            keyword_reply_batch_size,
        ):
            if rotation_interval is not None:
                messages.append(f'轮换间隔已设置为 {rotation_interval} 秒')
            if rotation_enabled is not None:
                status_text = '启用' if rotation_enabled else '禁用'
                messages.append(f'轮换功能已{status_text}')
            if keyword_reply_batch_size is not None:
                if keyword_reply_batch_size == 0:
                    messages.append('每轮关键词回复数已设为不限')
                else:
                    messages.append(f'每轮关键词回复数已设为 {keyword_reply_batch_size}')
            return jsonify({'success': True, 'message': '; '.join(messages) if messages else '设置已更新'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站轮换配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/similarity', methods=['PUT'])
def update_website_similarity(config_id):
    """更新用户的网站图片相似度阈值"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401
    try:
        current_user = get_current_user()
        data = request.get_json() or {}
        raw_value = data.get('image_similarity_threshold', None)

        if raw_value is None or raw_value == '':
            threshold = None
        else:
            try:
                threshold = float(raw_value)
            except (TypeError, ValueError):
                return jsonify({'error': '相似度必须是数字'}), 400
            if not (0.0 <= threshold <= 1.0):
                return jsonify({'error': '相似度必须在0.0-1.0之间'}), 400

        if db.update_user_website_similarity(current_user['id'], config_id, threshold):
            return jsonify({'success': True, 'message': '相似度阈值已更新'})
        return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站相似度阈值失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/filters', methods=['GET'])
def get_website_filters(config_id):
    """获取用户的网站消息过滤条件"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        settings = db.get_user_website_settings(current_user['id'], config_id)

        import json
        import uuid
        filters = json.loads(settings.get('message_filters', '[]'))
        updated = False
        for item in filters:
            if isinstance(item, dict) and not item.get('id'):
                item['id'] = uuid.uuid4().hex
                updated = True
        if updated:
            db.update_user_website_filters(current_user['id'], config_id, json.dumps(filters))
        return jsonify({'filters': filters})
    except Exception as e:
        logger.error(f"获取网站过滤条件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/filters', methods=['PUT'])
def update_website_filters(config_id):
    """更新用户的网站消息过滤条件"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        data = request.get_json()
        filters = data.get('filters', [])

        # 验证过滤条件格式
        import json
        import uuid
        settings = db.get_user_website_settings(current_user['id'], config_id)
        existing_filters = json.loads(settings.get('message_filters', '[]'))
        existing_by_id = {f.get('id'): f for f in existing_filters if isinstance(f, dict) and f.get('id')}

        normalized_filters = []
        seen_ids = set()
        for filter_item in filters:
            if not isinstance(filter_item, dict) or 'filter_type' not in filter_item:
                return jsonify({'error': '过滤条件格式无效'}), 400

            filter_type = filter_item.get('filter_type')
            filter_value = filter_item.get('filter_value', '')
            filter_id = filter_item.get('id') or uuid.uuid4().hex
            if filter_id in seen_ids:
                filter_id = uuid.uuid4().hex
            seen_ids.add(filter_id)

            if not filter_type or (filter_type not in {'image', 'image_filter'} and filter_value in (None, '')):
                return jsonify({'error': '过滤类型和值都是必填的'}), 400

            if filter_type == 'image' and not filter_value:
                filter_value = ''
            if filter_type == 'user_repeat':
                try:
                    seconds_val = float(filter_value)
                except (TypeError, ValueError):
                    return jsonify({'error': '秒必须是数字'}), 400
                if seconds_val <= 0:
                    return jsonify({'error': '秒必须大于0'}), 400
                filter_value = str(seconds_val)
            if filter_type == 'image_filter':
                try:
                    val = float(filter_value) if filter_value not in (None, '') else 0.95
                except (TypeError, ValueError):
                    return jsonify({'error': '相似度必须是数字'}), 400
                if not (0.0 <= val <= 1.0):
                    return jsonify({'error': '相似度必须在0.0-1.0之间'}), 400
                filter_value = str(val)

            normalized_filters.append({
                'id': filter_id,
                'filter_type': filter_type,
                'filter_value': filter_value
            })

        new_by_id = {f.get('id'): f for f in normalized_filters if f.get('id')}
        removed_ids = set(existing_by_id.keys()) - set(new_by_id.keys())

        def _cleanup_filter_images(filter_id: str):
            image_paths = db.delete_website_filter_images_by_filter(current_user['id'], config_id, filter_id)
            for path in image_paths:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception as cleanup_error:
                    logger.warning(f"删除网站过滤图片文件失败: {cleanup_error}")

        for filter_id in removed_ids:
            _cleanup_filter_images(filter_id)

        for filter_id, old_filter in existing_by_id.items():
            new_filter = new_by_id.get(filter_id)
            if not new_filter:
                continue
            if old_filter.get('filter_type') == 'image_filter' and new_filter.get('filter_type') != 'image_filter':
                _cleanup_filter_images(filter_id)

        filters_json = json.dumps(normalized_filters)

        if db.update_user_website_filters(current_user['id'], config_id, filters_json):
            return jsonify({'success': True, 'message': f'已更新 {len(normalized_filters)} 个过滤条件'})
        else:
            return jsonify({'error': '更新失败'}), 500
    except Exception as e:
        logger.error(f"更新网站过滤条件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/websites/<int:config_id>/filters/<filter_id>/images', methods=['GET'])
def get_website_filter_images(config_id, filter_id):
    """获取网站过滤规则的图片列表"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        settings = db.get_user_website_settings(current_user['id'], config_id)
        import json
        filters = json.loads(settings.get('message_filters', '[]'))
        matched_filter = next((f for f in filters if str(f.get('id')) == str(filter_id)), None)
        if not matched_filter:
            return jsonify({'error': '过滤规则不存在'}), 404

        images = db.get_website_filter_images(current_user['id'], config_id, str(filter_id))
        for img in images:
            img['url'] = f"/api/websites/filters/images/{img['id']}/file"
        return jsonify({'images': images})
    except Exception as e:
        logger.error(f"获取网站过滤图片失败: {e}")
        return jsonify({'error': '获取失败'}), 500


@app.route('/api/websites/<int:config_id>/filters/<filter_id>/images', methods=['POST'])
def add_website_filter_image(config_id, filter_id):
    """上传并添加网站过滤图片"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()
        settings = db.get_user_website_settings(current_user['id'], config_id)
        import json
        filters = json.loads(settings.get('message_filters', '[]'))
        matched_filter = next((f for f in filters if str(f.get('id')) == str(filter_id)), None)
        if not matched_filter:
            return jsonify({'error': '过滤规则不存在'}), 404
        if matched_filter.get('filter_type') != 'image_filter':
            return jsonify({'error': '仅图片过滤支持上传图片'}), 400

        if 'image' not in request.files:
            return jsonify({'error': '缺少图片文件'}), 400

        image_file = request.files['image']
        if not image_file or not image_file.filename:
            return jsonify({'error': '无效的图片文件'}), 400

        import uuid
        from PIL import Image

        save_dir = os.path.join(
            config.WEBSITE_FILTER_IMAGE_DIR,
            str(current_user['id']),
            str(config_id),
            str(filter_id)
        )
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        save_path = os.path.join(save_dir, filename)
        image_file.save(save_path)

        try:
            if os.path.getsize(save_path) == 0:
                os.remove(save_path)
                return jsonify({'error': '图片文件为空'}), 400
            with Image.open(save_path) as img:
                img.verify()
        except Exception:
            try:
                os.remove(save_path)
            except Exception:
                pass
            return jsonify({'error': '图片文件无效或损坏'}), 400

        features = extract_features(save_path)
        if features is None:
            try:
                os.remove(save_path)
            except Exception:
                pass
            return jsonify({'error': '特征提取失败'}), 500

        image_id = db.add_website_filter_image(current_user['id'], config_id, str(filter_id), save_path, features)
        return jsonify({
            'success': True,
            'image': {
                'id': image_id,
                'url': f"/api/websites/filters/images/{image_id}/file"
            }
        })
    except Exception as e:
        logger.error(f"添加网站过滤图片失败: {e}")
        return jsonify({'error': '添加失败'}), 500


@app.route('/api/websites/<int:config_id>/filters/<filter_id>/images/<int:image_id>', methods=['DELETE'])
def delete_website_filter_image(config_id, filter_id, image_id):
    """删除网站过滤图片"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401
    try:
        current_user = get_current_user()
        record = db.get_website_filter_image_by_id(image_id)
        if not record:
            return jsonify({'error': '图片不存在'}), 404
        if record.get('user_id') != current_user['id'] or record.get('website_id') != config_id:
            return jsonify({'error': '无权限'}), 403
        if str(record.get('filter_id')) != str(filter_id):
            return jsonify({'error': '过滤规则不匹配'}), 400

        image_path = db.delete_website_filter_image(image_id)
        if image_path:
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception as e:
                logger.warning(f"删除网站过滤图片文件失败: {e}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除网站过滤图片失败: {e}")
        return jsonify({'error': '删除失败'}), 500


@app.route('/api/websites/filters/images/<int:image_id>/file', methods=['GET'])
def serve_website_filter_image(image_id):
    """返回网站过滤图片文件"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401
    try:
        current_user = get_current_user()
        record = db.get_website_filter_image_by_id(image_id)
        if not record:
            return jsonify({'error': 'Image not found'}), 404
        if record.get('user_id') != current_user['id']:
            return jsonify({'error': '无权限'}), 403
        image_path = record['image_path']
        if not os.path.exists(image_path):
            return jsonify({'error': 'Image file missing'}), 404
        from flask import send_file
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"serve_website_filter_image 失败: {e}")
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

# === 健康检查端点（不需要认证，快速响应）===
@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查端点，返回后端和AI模型状态"""
    return jsonify({
        'status': 'ok',
        'backend': 'running',
        'ai_ready': ai_model_ready,
        'timestamp': datetime.now().isoformat()
    })

# === 新增：系统统计信息API ===
@app.route('/api/system/stats', methods=['GET'])
def get_system_stats():
    """获取系统统计信息 (带权限隔离)"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({
                'shop_count': 0,
                'product_count': 0,
                'image_count': 0,
                'user_count': 0,
                'total_replies': 0,
                'daily_replies_total': 0
            })
        stats = db.get_system_stats(user['id'], user['role'])
        return jsonify(stats)
    except Exception as e:
        logger.error(f"获取系统统计信息失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/cleanup-orphaned-images', methods=['POST'])
def cleanup_orphaned_images():
    """清理孤立的图片记录"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403

    try:
        deleted_count = db.cleanup_orphaned_images()
        return jsonify({
            'message': f'清理完成，删除了 {deleted_count} 条孤立记录',
            'deleted_count': deleted_count
        })
    except Exception as e:
        logger.error(f"清理孤立图片记录失败: {e}")
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

        if not filter_type or (filter_type not in {'image', 'image_filter'} and not filter_value):
            return jsonify({'error': '过滤类型和值都是必填的'}), 400

        if filter_type == 'image' and not filter_value:
            filter_value = ''
        if filter_type == 'user_repeat':
            try:
                seconds_val = float(filter_value)
            except (TypeError, ValueError):
                return jsonify({'error': '秒必须是数字'}), 400
            if seconds_val <= 0:
                return jsonify({'error': '秒必须大于0'}), 400
            filter_value = str(seconds_val)
        if filter_type in {'image_similarity', 'image_filter'}:
            try:
                val = float(filter_value) if filter_value not in (None, '') else 0.95
            except (TypeError, ValueError):
                return jsonify({'error': '相似度必须是数字'}), 400
            if not (0.0 <= val <= 1.0):
                return jsonify({'error': '相似度必须在0.0-1.0之间'}), 400
            filter_value = str(val)

        filter_id = db.add_message_filter(filter_type, filter_value)
        if filter_id:
            return jsonify({'success': True, 'message': '过滤规则添加成功', 'id': filter_id})
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

        if not filter_type or (filter_type not in {'image', 'image_filter'} and not filter_value):
            return jsonify({'error': '过滤类型和值都是必填的'}), 400

        if filter_type == 'image' and not filter_value:
            filter_value = ''
        if filter_type == 'user_repeat':
            try:
                seconds_val = float(filter_value)
            except (TypeError, ValueError):
                return jsonify({'error': '秒必须是数字'}), 400
            if seconds_val <= 0:
                return jsonify({'error': '秒必须大于0'}), 400
            filter_value = str(seconds_val)
        if filter_type in {'image_similarity', 'image_filter'}:
            try:
                val = float(filter_value) if filter_value not in (None, '') else 0.95
            except (TypeError, ValueError):
                return jsonify({'error': '相似度必须是数字'}), 400
            if not (0.0 <= val <= 1.0):
                return jsonify({'error': '相似度必须在0.0-1.0之间'}), 400
            filter_value = str(val)

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
        image_paths = db.delete_message_filter_images_by_filter_id(filter_id)
        if db.delete_message_filter(filter_id):
            for path in image_paths:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"删除过滤图片文件失败: {e}")
            return jsonify({'success': True, 'message': '过滤规则删除成功'})
        else:
            return jsonify({'error': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除消息过滤规则失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/message-filters/<int:filter_id>/images', methods=['GET'])
def get_message_filter_images(filter_id: int):
    """获取过滤规则的图片列表"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403
    try:
        images = db.get_message_filter_images(filter_id)
        for img in images:
            img['url'] = f"/api/message-filters/images/{img['id']}/file"
        return jsonify({'images': images})
    except Exception as e:
        logger.error(f"获取过滤图片失败: {e}")
        return jsonify({'error': '获取失败'}), 500


@app.route('/api/message-filters/<int:filter_id>/images', methods=['POST'])
def add_message_filter_image(filter_id: int):
    """上传并添加过滤图片"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403
    try:
        if 'image' not in request.files:
            return jsonify({'error': '缺少图片文件'}), 400

        image_file = request.files['image']
        if not image_file or not image_file.filename:
            return jsonify({'error': '无效的图片文件'}), 400

        import uuid
        from PIL import Image

        save_dir = os.path.join(config.MESSAGE_FILTER_IMAGE_DIR, str(filter_id))
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        save_path = os.path.join(save_dir, filename)
        image_file.save(save_path)

        try:
            if os.path.getsize(save_path) == 0:
                os.remove(save_path)
                return jsonify({'error': '图片文件为空'}), 400
            with Image.open(save_path) as img:
                img.verify()
        except Exception:
            try:
                os.remove(save_path)
            except Exception:
                pass
            return jsonify({'error': '图片文件无效或损坏'}), 400

        features = extract_features(save_path)
        if features is None:
            try:
                os.remove(save_path)
            except Exception:
                pass
            return jsonify({'error': '特征提取失败'}), 500

        image_id = db.add_message_filter_image(filter_id, save_path, features)
        return jsonify({
            'success': True,
            'image': {
                'id': image_id,
                'url': f"/api/message-filters/images/{image_id}/file"
            }
        })
    except Exception as e:
        logger.error(f"添加过滤图片失败: {e}")
        return jsonify({'error': '添加失败'}), 500


@app.route('/api/message-filters/<int:filter_id>/images/<int:image_id>', methods=['DELETE'])
def delete_message_filter_image(filter_id: int, image_id: int):
    """删除过滤图片"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403
    try:
        image_path = db.delete_message_filter_image(image_id)
        if not image_path:
            return jsonify({'error': '图片不存在'}), 404
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            logger.warning(f"删除过滤图片文件失败: {e}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除过滤图片失败: {e}")
        return jsonify({'error': '删除失败'}), 500


@app.route('/api/message-filters/images/<int:image_id>/file', methods=['GET'])
def serve_message_filter_image(image_id: int):
    """返回过滤图片文件"""
    if not require_admin():
        return jsonify({'error': '需要管理员权限'}), 403
    try:
        record = db.get_message_filter_image_by_id(image_id)
        if not record:
            return jsonify({'error': 'Image not found'}), 404
        image_path = record['image_path']
        if not os.path.exists(image_path):
            return jsonify({'error': 'Image file missing'}), 404
        from flask import send_file
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"serve_message_filter_image 失败: {e}")
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
            updated_clients, scoped_shops = refresh_running_bot_user_shops(user_id)
            logger.info(
                f"用户 {user_id} 店铺权限已更新，已刷新 {updated_clients} 个运行中Bot实例的店铺上下文: {scoped_shops}"
            )
            return jsonify({
                'message': '权限更新成功',
                'refreshed_bot_clients': updated_clients
            })
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
        # 所有用户（包括管理员）只能看到自己的账号
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
        # 获取分页参数（增加边界保护，避免非法入参破坏分页稳定性）
        page = max(int(request.args.get('page', 1)), 1)
        limit = int(request.args.get('limit', 50))  # 默认每页50条
        limit = max(1, min(limit, 500))
        offset = (page - 1) * limit
        keyword = (request.args.get('keyword') or '').strip()
        search_type = request.args.get('search_type', 'all')
        shop_name = (request.args.get('shop_name') or '').strip() or None

        # 根据用户权限获取商品（支持分页）
        if current_user['role'] == 'admin':
            # 管理员可以看到所有商品
            # 避免刷屏：不记录常规列表查询
            result = db.get_products_by_user_shops(
                None,
                limit=limit,
                offset=offset,
                keyword=keyword,
                search_type=search_type,
                shop_name=shop_name
            )
        else:
            # 普通用户只能看到自己管理的店铺的商品
            user_shops = current_user.get('shops', [])
            logger.info(f"普通用户 {current_user['username']} 获取店铺商品 (页{page}, 每页{limit}条)，分配的店铺: {user_shops}")
            result = db.get_products_by_user_shops(
                user_shops,
                limit=limit,
                offset=offset,
                keyword=keyword,
                search_type=search_type,
                shop_name=shop_name
            )

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

        # 避免刷屏：不记录常规列表查询结果

        # 添加调试信息到响应中
        response_data = {
            'products': result['products'],
            'total': result['total'],
            'debug': {
                'user_role': current_user['role'],
                'user_shops': current_user.get('shops', []),
                'is_admin': current_user['role'] == 'admin',
                'keyword': keyword,
                'search_type': search_type,
                'shop_name': shop_name
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

    # 提取公共权限检查逻辑
    def check_permission(product_id):
        """检查用户是否有权限更新指定商品"""
        if current_user['role'] == 'admin':
            return True

        user_shop_ids = current_user.get('shops', [])
        product = db.get_product_by_id(int(product_id))

        if not product:
            return False

        # 将店铺ID转换为店铺名称进行对比
        allowed_shop_names = []
        for shop_id in user_shop_ids:
            shop_info = db.get_shop_by_id(shop_id)
            if shop_info:
                allowed_shop_names.append(shop_info['name'])

        # 对比商品所属店铺名是否在用户允许的店铺名列表中
        if product.get('shop_name') in allowed_shop_names:
            return True

        return False

    def get_full_product_data(pid):
        """获取并格式化完整的商品数据，用于前端状态更新"""
        product = db._get_product_info_by_id(pid)
        if not product:
            return None

        # 获取所有图片
        images_data = db.get_product_images(pid)
        # 按索引排序并生成URL
        sorted_images = sorted(images_data, key=lambda x: x['image_index'])
        image_urls = [f"/api/image/{pid}/{img['image_index']}" for img in sorted_images]

        # 格式化字段以匹配前端需求 (CamelCase)
        weidian_id = ''
        try:
            if 'itemID=' in product.get('product_url', ''):
                weidian_id = product.get('product_url', '').split('itemID=')[1]
            elif product.get('item_id'):
                weidian_id = product.get('item_id')
        except:
            pass

        # 解析自定义图片URL和索引
        selected_indexes = []
        custom_urls = []
        uploaded_reply_image_urls = []
        try:
            if product.get('custom_reply_images'):
                selected_indexes = json.loads(product.get('custom_reply_images'))
            if product.get('custom_image_urls'):
                custom_urls = json.loads(product.get('custom_image_urls'))
            # 解析上传的自定义回复图片
            if product.get('uploaded_reply_images'):
                uploaded_filenames = json.loads(product.get('uploaded_reply_images'))
                # 生成图片URL数组
                uploaded_reply_image_urls = [f"/api/custom_reply_image/{pid}/{filename}" for filename in uploaded_filenames]
        except:
            pass

        # 关键：必须返回前端需要的每一个字段，否则前端会变白
        return {
            'id': product['id'],
            'title': product.get('title', ''),
            'englishTitle': product.get('english_title', ''),
            'weidianUrl': product.get('product_url', ''),
            'cnfansUrl': product.get('cnfans_url', ''),
            'acbuyUrl': product.get('acbuy_url', ''),
            'shopName': product.get('shop_name', '未知店铺'),
            'description': product.get('description', ''),

            # 规则相关
            'ruleEnabled': bool(product.get('ruleEnabled', True)),
            'customReplyText': product.get('custom_reply_text', ''),
            'imageSource': product.get('image_source', 'product'),
            'replyScope': product.get('reply_scope', 'all'),

            # 图片相关
            'selectedImageIndexes': selected_indexes,
            'customImageUrls': custom_urls,
            'images': image_urls, # 包含所有商品图片
            'uploadedImages': uploaded_reply_image_urls, # 上传的自定义回复图片URL数组

            'weidianId': weidian_id,
            'createdAt': product.get('created_at')
        }

    # ---------------------------------------------------------
    # 场景 A: 包含文件上传 (Multipart)
    # ---------------------------------------------------------
    if request.content_type and 'multipart/form-data' in request.content_type:
        product_id = request.form.get('id')
        if not product_id:
            return jsonify({'error': '商品ID不能为空'}), 400

        try:
            pid_int = int(product_id)
            if not check_permission(pid_int):
                return jsonify({'error': '无权限更新此商品'}), 403

            # 1. 处理上传的自定义回复图片
            # 注意：这些图片只用于自定义回复，不添加到商品图集和FAISS索引

            # 1.1 获取要保留的已有图片文件名列表（从前端传来）
            existing_filenames_to_keep = []
            if 'existingUploadedImageUrls' in request.form:
                try:
                    # 前端发送的是URL数组的JSON字符串，需要提取文件名
                    existing_urls = json.loads(request.form.get('existingUploadedImageUrls'))
                    for url in existing_urls:
                        # URL格式: /api/custom_reply_image/{product_id}/{filename}
                        # 提取最后一部分作为文件名
                        filename = url.split('/')[-1]
                        existing_filenames_to_keep.append(filename)
                except:
                    pass

            # 1.2 处理新上传的文件
            new_uploaded_filenames = []
            if 'uploadedImages' in request.files:
                import uuid
                import os

                # 创建自定义回复图片目录
                custom_reply_dir = os.path.join('data', 'custom_reply_images', str(pid_int))
                os.makedirs(custom_reply_dir, exist_ok=True)

                files = request.files.getlist('uploadedImages')
                for file in files:
                    if file and file.filename:
                        # 生成唯一文件名
                        filename = f"{uuid.uuid4()}_{file.filename}"
                        file_path = os.path.join(custom_reply_dir, filename)

                        # 保存文件（不添加到商品图集，不提取特征，不加入FAISS）
                        file.save(file_path)
                        new_uploaded_filenames.append(filename)

                if new_uploaded_filenames:
                    logger.info(f"保存了 {len(new_uploaded_filenames)} 张新的自定义回复图片到 {custom_reply_dir}")

            # 1.3 合并已有图片和新上传的图片
            all_uploaded_filenames = existing_filenames_to_keep + new_uploaded_filenames
            if existing_filenames_to_keep:
                logger.info(f"保留了 {len(existing_filenames_to_keep)} 张已有的自定义回复图片")

            # 2. 构建更新数据
            updates = {}

            # 如果有上传的自定义回复图片（已有的或新上传的），将文件名列表存储到数据库
            if all_uploaded_filenames:
                updates['uploaded_reply_images'] = json.dumps(all_uploaded_filenames)
            for key in ['title', 'englishTitle', 'ruleEnabled', 'customReplyText', 'imageSource', 'replyScope']:
                value = request.form.get(key)
                if value is not None:
                    if key == 'englishTitle':
                        updates['english_title'] = value
                    elif key == 'ruleEnabled':
                        # 兼容字符串 'true'/'false' 和 '1'/'0'
                        if str(value).lower() in ['true', '1']:
                            updates['ruleEnabled'] = 1
                        else:
                            updates['ruleEnabled'] = 0
                    elif key == 'customReplyText':
                        updates['custom_reply_text'] = value
                    elif key == 'imageSource':
                        updates['image_source'] = value
                    elif key == 'replyScope':
                        updates['reply_scope'] = value
                    else:
                        updates[key] = value

            # 3. 处理数组数据 (JSON)
            if 'selectedImageIndexes' in request.form:
                updates['custom_reply_images'] = request.form.get('selectedImageIndexes') # 已经是JSON字符串

            if 'customImageUrls' in request.form:
                updates['custom_image_urls'] = request.form.get('customImageUrls') # 已经是JSON字符串

            # 4. 执行更新
            if updates:
                db.update_product(pid_int, updates)

            # 5. 返回完整数据 (解决闪烁问题)
            full_product = get_full_product_data(pid_int)
            return jsonify({'message': '商品更新成功', 'product': full_product})

        except Exception as e:
            logger.error(f"更新商品失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({'error': '更新失败'}), 500
    # ---------------------------------------------------------
    # 场景 B: 仅 JSON 数据更新
    # ---------------------------------------------------------
    else:
        data = request.get_json()
        if not data or not data.get('id'):
            return jsonify({'error': '商品ID不能为空'}), 400

        product_id = data['id']

        try:
            if not check_permission(product_id):
                return jsonify({'error': '无权限更新此商品'}), 403

            updates = {}
            if 'title' in data:
                updates['title'] = data['title']
            if 'englishTitle' in data:
                updates['english_title'] = data['englishTitle']
            if 'ruleEnabled' in data:
                updates['ruleEnabled'] = 1 if data['ruleEnabled'] else 0
            if 'customReplyText' in data:
                updates['custom_reply_text'] = data['customReplyText']
            if 'replyScope' in data:
                updates['reply_scope'] = data['replyScope']
            if 'selectedImageIndexes' in data:
                updates['custom_reply_images'] = json.dumps(data['selectedImageIndexes'])
            if 'customImageUrls' in data:
                updates['custom_image_urls'] = json.dumps(data['customImageUrls'])
            if 'imageSource' in data:
                updates['image_source'] = data['imageSource']

            if updates:
                db.update_product(product_id, updates)

            # 返回完整数据
            full_product = get_full_product_data(product_id)
            return jsonify({'message': '商品更新成功', 'product': full_product})

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


@app.route('/api/custom_reply_image/<int:product_id>/<filename>', methods=['GET'])
def serve_custom_reply_image(product_id: int, filename: str):
    """返回指定商品的自定义回复图片文件"""
    try:
        # 从数据库读取 uploaded_reply_images 字段，验证文件名
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT uploaded_reply_images FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return jsonify({'error': 'Product not found or no uploaded images'}), 404

            # 解析 JSON 数组
            try:
                uploaded_filenames = json.loads(row[0])
            except:
                return jsonify({'error': 'Invalid image data'}), 500

            # 安全检查：验证文件名是否在列表中
            if filename not in uploaded_filenames:
                return jsonify({'error': 'Image not found'}), 404

        # 构建文件路径
        import os
        image_path = os.path.join('data', 'custom_reply_images', str(product_id), filename)

        # 安全检查并返回文件
        from flask import send_file
        if not os.path.exists(image_path):
            return jsonify({'error': 'Image file missing'}), 404
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"serve_custom_reply_image 失败: {e}")
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
    """批量开启或停止用户自己的账号"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid request body'}), 400

        new_status = data.get('status')
        if new_status not in ['online', 'offline']:
            return jsonify({'error': 'Invalid status. Must be "online" or "offline"'}), 400

        current_user = get_current_user()

        with db.get_connection() as conn:
            cursor = conn.cursor()

            if new_status == 'online':
                cursor.execute("""
                    UPDATE discord_accounts
                    SET status = 'online', last_active = ?
                    WHERE user_id = ?
                """, (datetime.now(), current_user['id']))
            else:
                cursor.execute("""
                    UPDATE discord_accounts
                    SET status = 'offline'
                    WHERE user_id = ?
                """, (current_user['id'],))

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

        # 调试延迟设置
        min_delay = data.get('global_reply_min_delay')
        max_delay = data.get('global_reply_max_delay')
        logger.info(f"用户设置延迟 - 最小: {min_delay}, 最大: {max_delay}")

        # 处理开关设置（boolean 转 integer）
        keyword_reply = data.get('keyword_reply_enabled')
        image_reply = data.get('image_reply_enabled')
        bark_enabled = data.get('bark_enabled')
        if keyword_reply is not None:
            keyword_reply = 1 if keyword_reply else 0
        if image_reply is not None:
            image_reply = 1 if image_reply else 0
        if bark_enabled is not None:
            bark_enabled = 1 if bark_enabled else 0

        success = db.update_user_settings(
            user_id=user['id'],
            download_threads=data.get('download_threads'),
            feature_extract_threads=data.get('feature_extract_threads'),
            discord_similarity_threshold=data.get('discord_similarity_threshold'),
            global_reply_min_delay=min_delay,
            global_reply_max_delay=max_delay,
            user_blacklist=data.get('user_blacklist'),
            keyword_filters=data.get('keyword_filters'),
            keyword_reply_enabled=keyword_reply,
            image_reply_enabled=image_reply,
            global_reply_template=data.get('global_reply_template'),
            numeric_filter_keyword=data.get('numeric_filter_keyword'),
            filter_size_min=data.get('filter_size_min'),
            filter_size_max=data.get('filter_size_max'),
            bark_enabled=bark_enabled,
            bark_server_url=data.get('bark_server_url'),
            bark_device_key=data.get('bark_device_key'),
        )

        if success:
            return jsonify({'message': '设置更新成功'})
        else:
            return jsonify({'error': '设置更新失败'}), 500
    except Exception as e:
        logger.error(f"更新用户设置失败: {e}")
        return jsonify({'error': '更新设置失败'}), 500

@app.route('/api/user/bark-test', methods=['POST'])
def send_bark_test_notification():
    """发送 Bark 测试推送"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '需要登录'}), 401

    try:
        data = request.get_json(silent=True) or {}
        user_settings = db.get_user_settings(user['id']) or {}

        bark_server_url = (
            data.get('bark_server_url')
            or user_settings.get('bark_server_url')
            or 'https://api.day.app'
        ).strip()
        bark_device_key = (
            data.get('bark_device_key')
            or user_settings.get('bark_device_key')
            or ''
        ).strip()

        if not bark_device_key:
            return jsonify({'error': '请先填写 Bark 设备 Key'}), 400

        if not bark_server_url:
            bark_server_url = 'https://api.day.app'
        bark_server_url = bark_server_url.rstrip('/')
        if not bark_server_url.startswith(('http://', 'https://')):
            bark_server_url = f'https://{bark_server_url}'

        peer_content = '@jerry_selfbot_01 这双AJ4有39码吗？'
        title = peer_content
        now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body = (
            f"账号: jerry_selfbot_01\n"
            f"类型: 被@提及\n"
            f"发送者: mike_buyer\n"
            f"位置: PandaBuy Group / #sneaker-qa\n"
            f"内容: {peer_content}\n"
            f"时间: {now_text}"
        )

        push_url = (
            f"{bark_server_url}/"
            f"{quote(bark_device_key, safe='')}/"
            f"{quote(title, safe='')}/"
            f"{quote(body, safe='')}"
        )

        params = {
            'group': 'Discord营销系统',
            'isArchive': '1',
            'sound': 'gotosleep',
        }

        with requests.Session() as session_obj:
            session_obj.trust_env = False
            response = session_obj.get(
                push_url,
                params=params,
                timeout=8,
                proxies={'http': None, 'https': None}
            )

        response_text = response.text[:500]
        if response.status_code >= 400:
            logger.warning(
                f"Bark测试推送失败: status={response.status_code}, body={response_text}"
            )
            return jsonify({
                'error': f'Bark 推送失败（HTTP {response.status_code}）',
                'details': response_text
            }), 502

        logger.info(
            f"📱 Bark测试推送成功: user={user.get('username')}({user.get('id')})"
        )
        return jsonify({
            'success': True,
            'message': '测试推送已发送，请检查 iPhone 的 Bark 通知',
            'server_url': bark_server_url
        })
    except Exception as e:
        logger.error(f"Bark测试推送异常: {e}")
        return jsonify({'error': f'发送测试推送失败: {e}'}), 500

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
    """批量删除商品（优化版）"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'error': 'No IDs provided'}), 400

        logger.info(f"开始批量删除 {len(ids)} 个商品")

        result = db.delete_products_bulk(ids)
        deleted_count = result.get('deleted_count', 0)
        failed_ids = result.get('missing_ids', [])
        file_failed_count = result.get('file_failed_count', 0)

        logger.info(f"批量删除完成: {deleted_count}/{len(ids)} 个商品成功删除")

        response = {'success': True, 'count': deleted_count, 'total': len(ids)}
        warnings = []
        if failed_ids:
            response['failed_ids'] = failed_ids
            warnings.append(f'{len(failed_ids)} 个商品不存在')
        if file_failed_count:
            warnings.append(f'{file_failed_count} 个图片文件删除失败')
        if warnings:
            response['warning'] = '，'.join(warnings)

        return jsonify(response)
    except Exception as e:
        logger.error(f"批量删除失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/batch-delete-all', methods=['DELETE'])
def batch_delete_all_products():
    """删除所有商品（全选删除）"""
    try:
        if not require_login():
            return jsonify({'error': '需要登录'}), 401

        current_user = get_current_user()
        data = request.get_json(silent=True) or {}
        keyword = (request.args.get('keyword') or data.get('keyword') or '').strip()
        search_type = request.args.get('search_type') or data.get('search_type') or 'all'
        shop_name = (request.args.get('shop_name') or data.get('shop_name') or '').strip() or None

        if current_user['role'] == 'admin':
            all_ids = db.get_product_ids_by_user_shops(
                None,
                keyword=keyword,
                search_type=search_type,
                shop_name=shop_name
            )
        else:
            user_shops = current_user.get('shops', [])
            all_ids = db.get_product_ids_by_user_shops(
                user_shops,
                keyword=keyword,
                search_type=search_type,
                shop_name=shop_name
            )

        if not all_ids:
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM product_images")
                    remaining_images = cursor.fetchone()[0] or 0

                if remaining_images == 0:
                    try:
                        from vector_engine import get_vector_engine
                    except ImportError:
                        from .vector_engine import get_vector_engine
                    engine = get_vector_engine()
                    if engine.count() > 0:
                        engine.rebuild_index([])
            except Exception as e:
                logger.warning(f"清理空索引失败: {e}")

            return jsonify({'success': True, 'count': 0, 'message': '没有商品需要删除'})

        logger.info(f"开始删除所有 {len(all_ids)} 个商品")

        result = db.delete_products_bulk(all_ids)
        deleted_count = result.get('deleted_count', 0)
        failed_ids = result.get('missing_ids', [])
        file_failed_count = result.get('file_failed_count', 0)

        logger.info(f"全选删除完成: {deleted_count}/{len(all_ids)} 个商品成功删除")

        response = {
            'success': True,
            'count': deleted_count,
            'total': len(all_ids),
            'message': f'成功删除 {deleted_count} 个商品'
        }

        warnings = []
        if failed_ids:
            response['failed_ids'] = failed_ids
            warnings.append(f'{len(failed_ids)} 个商品不存在')
        if file_failed_count:
            warnings.append(f'{file_failed_count} 个图片文件删除失败')
        if warnings:
            response['warning'] = '，'.join(warnings)

        return jsonify(response)
    except Exception as e:
        logger.error(f"全选删除失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """获取单个商品的详细信息"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        product = db._get_product_info_by_id(product_id)
        if not product:
            return jsonify({'error': '商品不存在'}), 404

        # 获取商品图片
        images = db.get_product_images(product_id)
        product['images'] = [f"/api/image/{product_id}/{img['image_index']}" for img in images]

        return jsonify(product)
    except Exception as e:
        logger.error(f"获取商品失败: {e}")
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
        existing_feats = [img['features'] for img in existing_images if img.get('features') is not None]

        # 获取下一个 index
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(image_index) FROM product_images WHERE product_id = ?", (product_id,))
            row = cursor.fetchone()
            next_index = (row[0] + 1) if row and row[0] is not None else 0

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
        limit = int(request.args.get('limit', 20))
        limit = max(1, min(limit, 100))  # 1~100
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
        import re
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request body'}), 400

        query = data.get('query', '').strip()
        requested_limit = int(data.get('limit', 80))
        # 放宽上限，支持大库分页场景；同时保留边界保护避免一次性拉取过大数据
        limit = max(1, min(requested_limit, 1000))
        user_id = data.get('user_id')
        raw_user_shops = data.get('user_shops')

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        try:
            user_id = int(user_id) if user_id is not None else None
        except (TypeError, ValueError):
            user_id = None

        def _normalize_shop(value):
            if value is None:
                return ''
            return re.sub(r'\s+', ' ', str(value)).strip().lower()

        scoped_shops = set()
        if isinstance(raw_user_shops, list):
            scoped_shops.update(_normalize_shop(v) for v in raw_user_shops if v is not None)
        if user_id:
            scoped_shops.update(_normalize_shop(v) for v in build_user_shop_scope(user_id))
        scoped_shops.discard('')
        scoped_shop_list = sorted(scoped_shops)

        logger.info(f'文字搜索请求: "{query}", 限制: {limit}')

        if user_id is not None and not scoped_shop_list:
            logger.info(f'文字搜索被店铺权限拦截: user_id={user_id} 无可用店铺')
            return jsonify({
                'success': True,
                'query': query,
                'products': [],
                'total': 0
            })

        with db.get_connection() as conn:
            cursor = conn.cursor()
            query_lower = query.lower()
            query_normalized = re.sub(r'\s+', ' ', query_lower).strip()

            scoped_clause = ""
            scoped_params = ()
            if scoped_shop_list:
                placeholders = ",".join("?" for _ in scoped_shop_list)
                scoped_clause = f" AND LOWER(TRIM(COALESCE(shop_name, ''))) IN ({placeholders})"
                scoped_params = tuple(scoped_shop_list)

            def fetch_by_terms(terms, remaining_limit, exclude_ids=None):
                if not terms or remaining_limit <= 0:
                    return []
                conditions = []
                params = []
                for term in terms:
                    like = f"%{term}%"
                    conditions.append("(LOWER(english_title) LIKE ? OR LOWER(title) LIKE ?)")
                    params.extend([like, like])
                where_clause = " OR ".join(conditions)
                exclude_clause = ""
                exclude_params = []
                if exclude_ids:
                    placeholders = ",".join("?" for _ in exclude_ids)
                    exclude_clause = f" AND id NOT IN ({placeholders})"
                    exclude_params = list(exclude_ids)
                cursor.execute(f"""
                    SELECT id, product_url, title, english_title, description,
                           ruleEnabled, min_delay, max_delay, created_at,
                           cnfans_url, shop_name, custom_reply_text,
                           custom_reply_images, custom_image_urls, image_source,
                           reply_scope,
                           uploaded_reply_images
                    FROM products
                    WHERE ({where_clause}){exclude_clause}{scoped_clause}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                """, (*params, *exclude_params, *scoped_params, remaining_limit))
                return cursor.fetchall()

            rows = fetch_by_terms([query_normalized], limit)
            found_ids = {row['id'] for row in rows}

            raw_tokens = re.findall(r'\w+', query_normalized)
            tokens = [kw for kw in raw_tokens if len(kw) >= 2 or kw.isdigit()]
            extra_terms = []
            numeric_terms = []
            if tokens:
                seen_numeric = set()
                for idx, token in enumerate(tokens):
                    if not any(ch.isdigit() for ch in token):
                        continue
                    if idx - 1 >= 0:
                        phrase = f"{tokens[idx - 1]} {token}"
                        if phrase not in seen_numeric:
                            numeric_terms.append(phrase)
                            seen_numeric.add(phrase)
                    if idx - 2 >= 0:
                        phrase = f"{tokens[idx - 2]} {tokens[idx - 1]} {token}"
                        if phrase not in seen_numeric:
                            numeric_terms.append(phrase)
                            seen_numeric.add(phrase)
            if len(tokens) >= 2:
                for i in range(len(tokens) - 1):
                    term = f"{tokens[i]} {tokens[i + 1]}"
                    if term not in extra_terms:
                        extra_terms.append(term)
            for token in tokens:
                if any(ch.isdigit() for ch in token) and len(token) >= 2 and token not in extra_terms:
                    extra_terms.append(token)

            if numeric_terms and len(rows) < limit:
                remaining = limit - len(rows)
                extra_rows = fetch_by_terms(numeric_terms, remaining, found_ids)
                rows.extend(extra_rows)
                found_ids.update({row['id'] for row in extra_rows})

            if extra_terms and len(rows) < limit:
                remaining = limit - len(rows)
                extra_rows = fetch_by_terms(extra_terms, remaining, found_ids)
                rows.extend(extra_rows)
                found_ids.update({row['id'] for row in extra_rows})

            if not rows:
                tokens = tokens[:6]
                if tokens:
                    rows = fetch_by_terms(tokens, limit)

            if not rows:
                cursor.execute("""
                    SELECT id, product_url, title, english_title, description,
                           ruleEnabled, min_delay, max_delay, created_at,
                           cnfans_url, shop_name, custom_reply_text,
                           custom_reply_images, custom_image_urls, image_source,
                           reply_scope,
                           uploaded_reply_images
                    FROM products
                    WHERE ((
                        english_title IS NOT NULL
                        AND LENGTH(TRIM(english_title)) >= 2
                        AND INSTR(?, LOWER(english_title)) > 0
                    )
                    OR (
                        title IS NOT NULL
                        AND LENGTH(TRIM(title)) >= 2
                        AND INSTR(?, LOWER(title)) > 0
                    ))""" + scoped_clause + """
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                """, (query_normalized, query_normalized, *scoped_params, limit))
                rows = cursor.fetchall()

            products = []
            for row in rows:
                prod = dict(row)
                # 简单获取第一张图作为预览
                cursor.execute("SELECT image_index FROM product_images WHERE product_id = ? ORDER BY image_index LIMIT 1", (prod['id'],))
                img_row = cursor.fetchone()
                # 构造符合 Bot 逻辑的 image 路径
                if img_row:
                    prod['images'] = [f"/api/image/{prod['id']}/{img_row[0]}"]
                else:
                    prod['images'] = []

                # 补充 Bot 需要的字段
                prod['weidianUrl'] = prod.get('product_url')
                prod['autoReplyEnabled'] = bool(prod.get('ruleEnabled', True))
                prod['replyScope'] = prod.get('reply_scope') or 'all'

                # 解析 JSON 字段供 Bot 使用
                try:
                    if prod.get('custom_reply_images'):
                        prod['selectedImageIndexes'] = json.loads(prod['custom_reply_images'])
                    if prod.get('custom_image_urls'):
                        prod['customImageUrls'] = json.loads(prod['custom_image_urls'])
                    # 解析上传的自定义回复图片
                    if prod.get('uploaded_reply_images'):
                        prod['uploaded_reply_images'] = json.loads(prod['uploaded_reply_images'])
                except:
                    pass

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
            for log_entry in all_logs[-50:]:  # 发送最近50条历史日志
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
        # 从日志列表中返回最近500条日志
        return jsonify({
            'logs': all_logs[-500:],
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
        if len(all_logs) > 500:
            all_logs.pop(0)

        # 添加到队列（非阻塞，防止日志洪峰卡住请求线程）
        try:
            log_queue.put_nowait(log_entry)
        except queue.Full:
            try:
                log_queue.get_nowait()
                log_queue.put_nowait(log_entry)
            except Exception:
                pass

        return jsonify({'success': True})
    except Exception as e:
        print(f"添加外部日志失败: {e}")
        return jsonify({'error': str(e)}), 500

def start_discord_bot(user_id=None):
    """启动Discord机器人 - 支持多账号"""
    global bot_running, bot_loop, bot_thread

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
            return 0

        if bot_running:
            logger.info("机器人已在运行中，尝试补启动未运行账号")

        logger.info(f"找到 {len(accounts)} 个Discord账号，开始启动...")

        # 确保事件循环存在并运行
        if bot_loop is None or bot_thread is None or not bot_thread.is_alive():
            bot_loop = asyncio.new_event_loop()
            bot_thread = threading.Thread(target=bot_loop.run_forever, daemon=True)
            bot_thread.start()
            logger.info("已创建新的机器人事件循环")
        loop = bot_loop

        # 为每个账号创建机器人实例
        existing_account_ids = {client.account_id for client in bot_clients}
        started_count = 0
        for account in accounts:
            account_id = account['id']
            token = account['token']
            username = account.get('username', f'account_{account_id}')
            user_id = account.get('user_id')

            if account_id in existing_account_ids:
                logger.info(f"机器人账号已在运行: {username} (ID: {account_id})")
                continue

            # 获取用户管理的店铺（包含店铺ID与店铺名）
            user_shops = build_user_shop_scope(user_id) if user_id else None

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
                task = asyncio.run_coroutine_threadsafe(client.start(token, reconnect=True), loop)
                bot_clients.append(client)
                bot_tasks.append(task)
                started_count += 1
                logger.info(f"Discord机器人启动成功: {username}")
            except Exception as e:
                logger.error(f"启动机器人失败 {username}: {e}")

        if bot_clients:
            bot_running = True
            logger.info(f"共启动了 {len(bot_clients)} 个Discord机器人")
        else:
            logger.warning("没有成功启动任何机器人")
        return started_count

    except ImportError as e:
        logger.warning(f"Discord机器人模块不可用: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")
        return 0
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        logger.info("Flask应用将继续运行，但机器人功能不可用")
        return 0

def stop_discord_bot(user_id=None):
    """停止Discord机器人 (支持按用户停止)"""
    global bot_running, bot_loop

    # 如果没有客户端，直接返回
    if not bot_clients:
        logger.info("没有正在运行的机器人")
        bot_running = False
        return

    logger.info(f"正在停止机器人... {'(特定用户: ' + str(user_id) + ')' if user_id else '(所有用户)'}")

    try:
        import asyncio
        # 获取当前的事件循环，如果是在 Flask 线程中可能需要处理
        loop = bot_loop
        if loop is None:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        # 筛选需要停止的客户端索引
        indices_to_remove = []

        for i, client in enumerate(bot_clients):
            # 如果指定了 user_id，只停止该用户的机器人
            # client.user_id 是我们在 DiscordBotClient 初始化时传入的
            if user_id is not None and getattr(client, 'user_id', None) != user_id:
                continue

            try:
                if client and not client.is_closed():
                    # 更新账号状态为offline
                    if hasattr(client, 'account_id') and client.account_id:
                        db.update_account_status(client.account_id, 'offline')
                        logger.info(f"账号 {client.account_id} 状态已更新为离线")

                    # 停止机器人
                    if loop:
                        asyncio.run_coroutine_threadsafe(client.close(), loop)
                    logger.info(f"Discord机器人 {i} (用户 {getattr(client, 'user_id', 'unknown')}) 已停止信号发送")
            except Exception as e:
                logger.error(f"停止机器人 {i} 时出错: {e}")

            indices_to_remove.append(i)

        # 从列表中移除已停止的机器人和任务
        # 从后往前删，避免索引偏移
        for i in sorted(indices_to_remove, reverse=True):
            if i < len(bot_clients):
                bot_clients.pop(i)
            if i < len(bot_tasks):
                # 尝试取消任务
                task = bot_tasks[i]
                if task and not task.done():
                    task.cancel()
                bot_tasks.pop(i)

        if not bot_clients:
            bot_running = False
            logger.info("所有机器人已停止")
        else:
            logger.info(f"剩余 {len(bot_clients)} 个机器人仍在运行")

    except Exception as e:
        logger.error(f"停止机器人流程出错: {e}")

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
        started_count = start_discord_bot(user_id)

        if started_count == 0:
            logger.info(f"用户 {user_id} 的机器人已在运行中，共有 {len(user_accounts)} 个账号")
        else:
            logger.info(f"用户 {user_id} 启动机器人成功，新增 {started_count} 个账号，共有 {len(user_accounts)} 个账号")
        return jsonify({
            'message': '账号启动成功' if started_count > 0 else '账号已在运行',
            'totalAccounts': len(user_accounts),
            'startedAccounts': started_count
        })

    except Exception as e:
        logger.error(f"启动机器人失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    """停止Discord机器人"""
    if not require_login():
        return jsonify({'error': '需要登录'}), 401

    try:
        current_user = get_current_user()

        # 如果是管理员，且请求中包含 targetUserId，则停止指定用户的
        # 否则停止当前用户的
        # 这里简化逻辑：用户只能停止自己的
        user_id = current_user['id']

        stop_discord_bot(user_id)

        logger.info(f"用户 {user_id} 的机器人已停止")
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
    """获取店铺列表（根据用户权限过滤）"""
    try:
        # 获取所有店铺
        all_shops = db.get_all_shops()

        current_user = get_current_user()
        if not current_user:
            # 如果未登录，返回空
            return jsonify({'shops': []})

        # 如果是管理员，返回所有
        if current_user['role'] == 'admin':
            return jsonify({'shops': all_shops})

        # 如果是普通用户，只筛选出他有权限的店铺
        user_permitted_shop_ids = current_user.get('shops', [])
        filtered_shops = [s for s in all_shops if s['shop_id'] in user_permitted_shop_ids]

        return jsonify({'shops': filtered_shops})
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

        headers = {
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
        }
        cookies = {
            'wdtoken': '8ea9315c',
            '__spider__visitorid': '0dcf6a5b878847ec',
            'visitor_id': '4d36e980-4128-451c-8178-a976b6303114',
            'v-components/cpn-coupon-dialog@nologinshop': '2',
            '__spider__sessionid': 'c7da7d6e06b1f1ac'
        }

        for attempt in range(1, 5):
            try:
                response = requests.get(
                    api_url,
                    headers=headers,
                    cookies=cookies,
                    timeout=10,
                    proxies={'http': None, 'https': None}
                )
                response.raise_for_status()
                data = response.json()
                if data.get('status', {}).get('code') == 0:
                    result = data.get('result', {})
                    shop_name = result.get('shareTitle', '')
                    if shop_name:
                        return {'shopName': shop_name}
            except Exception as e:
                if attempt < 4:
                    time.sleep(0.4 * attempt)
                    continue
                raise e

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
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    shop_id = data.get('shopId')  # 可选参数

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
            completed=False,
            message='正在停止抓取...',
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
            thread_id=None,
            failed_items=[]
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
        details = []

        def process_single_product_batch(product_id):
            """处理单个商品（用于线程池）"""
            try:
                current_status = db.get_scrape_status()
                if current_status.get('stop_signal', False):
                    logger.info(f"🔴 处理商品前检测到停止信号，取消处理商品 {product_id}")
                    return {'status': 'cancelled', 'product_id': product_id, 'message': '任务已取消'}

                product_info = {
                    'item_id': str(product_id),
                    'item_url': f'https://weidian.com/item.html?itemID={product_id}',
                    'shop_name': '批量上传'
                }

                result = process_and_save_single_product_sync(product_info) or {}
                status = result.get('status', 'failed')

                return {
                    'status': status,
                    'product_id': product_id,
                    'message': result.get('message', ''),
                    'failed_details': result.get('failed_details', [])
                }

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

                            details.append({
                                'id': product_id,
                                'status': result.get('status'),
                                'message': result.get('message', ''),
                                'failed_details': result.get('failed_details', [])
                            })

                            if result['status'] == 'success':
                                results['success'] += 1
                                logger.info(f"商品 {product_id} 处理成功")
                            elif result['status'] == 'skipped':
                                results['skipped'] += 1
                                logger.debug(f"商品 {product_id} 已存在，跳过")
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
                            details.append({
                                'id': product_id,
                                'status': 'error',
                                'message': str(e)
                            })
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
            'results': results,
            'details': details
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
            'stop_signal': status.get('stop_signal', False),
            'progress': status.get('progress', 0),
            'total': status.get('total', 0),
            'current': status.get('processed', 0),  # 前端期望current字段
            'processed': status.get('processed', 0),
            'success': status.get('success', 0),
            'failed_items': status.get('failed_items', []),
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
            'stop_signal': False,
            'progress': 0,
            'total': 0,
            'current': 0,
            'processed': 0,
            'success': 0,
            'message': '获取状态失败',
            'failed_items': [],
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

def get_all_category_ids(shop_id, session):
    """
    获取店铺所有分类ID (包括子分类)
    API: decorate/itemCate.getCateTree
    """
    try:
        import time
        from urllib.parse import quote

        url = "https://thor.weidian.com/decorate/itemCate.getCateTree/1.0"
        param = json.dumps({
            "shopId": str(shop_id),
            "attrQuery": [],
            "from": "h5"
        })
        full_url = f"{url}?param={quote(param)}&wdtoken=8ea9315c&_={int(time.time()*1000)}"

        logger.info(f"正在获取店铺分类树: {shop_id}")
        response = session.get(full_url, timeout=10)
        data = response.json()

        cate_ids = []

        if data.get('status', {}).get('code') == 0:
            cate_list = data.get('result', {}).get('cateList', [])

            def extract_ids(nodes):
                for node in nodes:
                    cid = node.get('cateId')
                    cname = node.get('cateName')
                    count = node.get('speCateItemNum', 0)

                    if cid:
                        cate_ids.append({'id': cid, 'name': cname, 'count': count})

                    children = node.get('childCateList', [])
                    if children:
                        extract_ids(children)

            extract_ids(cate_list)
            logger.info(f"✅ 成功获取 {len(cate_ids)} 个分类: {[c['name'] for c in cate_ids]}")
        else:
            logger.warning(f"获取分类树失败: {data}")

        return cate_ids

    except Exception as e:
        logger.error(f"获取分类树异常: {e}")
        return []

def fetch_category_items(shop_id, cate_id, cate_name, session, limit=20):
    """
    生成器：抓取指定分类下的所有商品
    API: decorate/itemCate.getCateItemList
    """
    import time
    from urllib.parse import quote

    offset = 0

    while True:
        try:
            url = "https://thor.weidian.com/decorate/itemCate.getCateItemList/1.0"
            param = json.dumps({
                "cateId": str(cate_id),
                "shopId": str(shop_id),
                "offset": offset,
                "limit": limit,
                "sortField": "all",
                "sortType": "desc",
                "isQdFx": False,
                "isHideSold": False,
                "hideItemRealAmount": False,
                "from": "h5"
            })
            full_url = f"{url}?param={quote(param)}&wdtoken=8ea9315c&_={int(time.time()*1000)}"

            response = session.get(full_url, timeout=10)
            data = response.json()

            if data.get('status', {}).get('code') != 0:
                logger.warning(f"分类[{cate_name}] Offset {offset} API错误: {data.get('status')}")
                break

            result = data.get('result', {})
            items = result.get('itemList', [])

            if not items:
                break

            for item in items:
                yield item

            if len(items) < limit:
                break

            offset += limit
            time.sleep(0.3)

        except Exception as e:
            logger.error(f"抓取分类[{cate_name}]异常: {e}")
            break

def scrape_shop_products(shop_id):
    """抓取店铺所有商品的实现 (分类树方案 - 突破2000条限制)"""
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
    failed_items = []

    # 初始化状态
    db.update_scrape_status(
        is_scraping=True,
        paused=False,
        stop_signal=False,
        progress=0,
        total=0,
        processed=0,
        success=0,
        failed=0,
        image_failed=0,
        index_failed=0,
        failed_items=[],
        message='正在初始化...'
    )

    # 获取店铺名称
    shop_info = get_shop_info_from_api(shop_id)
    shop_name = shop_info.get('shopName', f'店铺 {shop_id}') if shop_info else f'店铺 {shop_id}'

    db.update_scrape_status(message=f'正在抓取店铺: {shop_name}')
    logger.info(f"开始收集商品列表，店铺: {shop_name}")

    # 【性能优化】一次性获取所有已存在的商品ID，避免逐个查询数据库
    logger.info("正在加载已存在的商品ID...")
    existing_item_ids = db.get_all_existing_item_ids()
    logger.info(f"已加载 {len(existing_item_ids)} 个已存在的商品ID，将快速跳过")

    # =========================================================================
    # 阶段 1: 通过分类树抓取所有商品 (多线程优化版)
    # =========================================================================
    logger.info("=== 阶段 1: 通过分类树并发抓取商品 ===")

    db.update_scrape_status(message='正在获取店铺分类树...')

    if not (scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False)):
        try:
            # 1. 获取所有分类 ID
            categories = get_all_category_ids(shop_id, scraper.session)

            if not categories:
                logger.warning("未获取到任何分类，尝试使用Tab 0备用方案...")
                db.update_scrape_status(message='未找到分类，使用备用方案...')
            else:
                logger.info(f"获取到 {len(categories)} 个分类，准备并发扫描...")

                # 定义单个分类的处理函数
                def process_category(cate):
                    if scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False):
                        return 0

                    cate_id = cate['id']
                    cate_name = cate['name']
                    # 跳过空分类
                    if cate['count'] == 0:
                        return 0

                    local_new_count = 0
                    # 注意：fetch_category_items 内部会有分页请求，这里是 IO 密集型
                    for item in fetch_category_items(shop_id, cate_id, cate_name, scraper.session):
                        item_id = str(item.get('itemId', ''))

                        # 检查停止信号
                        if scrape_stop_event.is_set():
                            break

                        if item_id:
                            # 字典操作的线程安全性：Python字典的key唯一性天然去重
                            if item_id not in unique_product_tasks:
                                # 检查数据库去重
                                if item_id in existing_item_ids:
                                    continue

                                unique_product_tasks[item_id] = {
                                    'item_id': item_id,
                                    'item_url': item.get('itemUrl', f"https://weidian.com/item.html?itemID={item_id}"),
                                    'shop_name': shop_name
                                }
                                local_new_count += 1
                    return local_new_count

                # 使用线程池并发扫描分类
                # 分类扫描主要是网络请求，可以开较高的并发
                cate_workers = min(10, len(categories))
                cate_executor = concurrent.futures.ThreadPoolExecutor(max_workers=cate_workers)
                cate_stop_requested = False
                try:
                    # 提交任务
                    future_to_cate = {cate_executor.submit(process_category, cate): cate for cate in categories}
                    pending_futures = set(future_to_cate.keys())

                    completed_cates = 0
                    while pending_futures:
                        if scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False):
                            cate_stop_requested = True
                            for future in pending_futures:
                                future.cancel()
                            db.update_scrape_status(message="正在停止任务...")
                            cate_executor.shutdown(wait=False, cancel_futures=True)
                            pending_futures.clear()
                            break

                        done, pending_futures = concurrent.futures.wait(
                            pending_futures,
                            timeout=1.0,
                            return_when=concurrent.futures.FIRST_COMPLETED
                        )

                        for future in done:
                            cate = future_to_cate[future]
                            try:
                                count = future.result()
                                completed_cates += 1
                                logger.debug(f"[{completed_cates}/{len(categories)}] 分类 '{cate['name']}' 扫描完成，新增 {count} 个商品")
                                # 实时更新前端显示的总数
                                db.update_scrape_status(
                                    total=len(unique_product_tasks),
                                    message=f"正在并发扫描分类 ({completed_cates}/{len(categories)})..."
                                )
                            except Exception as e:
                                logger.error(f"扫描分类 '{cate['name']}' 失败: {e}")
                finally:
                    if not cate_stop_requested:
                        cate_executor.shutdown(wait=True)

        except Exception as e:
            logger.error(f"分类遍历过程异常: {e}")

    logger.info(f"✅ 分类树抓取完成，共收集 {len(unique_product_tasks)} 个商品")

    # =========================================================================
    # 阶段 2: 并发处理
    # =========================================================================

    # 转回列表用于处理
    all_product_tasks = list(unique_product_tasks.values())
    total_products = len(all_product_tasks)
    logger.info(f"✅ 商品收集阶段结束，去重后最终待处理: {total_products} 个商品")

    # 更新状态：开始处理
    db.update_scrape_status(
        total=total_products,
        progress=0, # 重置进度条为0，开始第二阶段
        message=f'收集完成，准备并发处理 {total_products} 个商品...'
    )

    # 第二阶段：使用全局线程池并发处理所有商品
    processed_count = 0
    success_count = 0
    failed_count = 0
    image_failed_count = 0
    index_failed_count = 0

    stop_requested = False
    if all_product_tasks:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)
        try:
            # 提交所有商品任务到线程池
            future_to_product = {
                executor.submit(process_and_save_single_product_sync, product_info): product_info
                for product_info in all_product_tasks
            }

            pending_futures = set(future_to_product.keys())

            # 轮询等待，确保可中断
            while pending_futures:
                # 检查停止事件或停止信号
                if scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False):
                    logger.info("🔴 检测到停止事件/信号，正在取消剩余任务...")
                    stop_requested = True
                    for future in pending_futures:
                        future.cancel()
                    db.update_scrape_status(message="正在停止任务...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    pending_futures.clear()
                    break

                done, pending_futures = concurrent.futures.wait(
                    pending_futures,
                    timeout=1.0,
                    return_when=concurrent.futures.FIRST_COMPLETED
                )

                for future in done:
                    product_info = future_to_product.get(future, {})
                    try:
                        result = future.result() or {}
                        processed_count += 1

                        if not result:
                            failed_count += 1
                            failed_items.append({
                                'id': str(product_info.get('item_id', '')),
                                'reason': '未知错误'
                            })
                        elif result.get('failed'):
                            failed_count += 1
                            if result.get('image_failed'):
                                image_failed_count += 1
                            if result.get('index_failed'):
                                index_failed_count += 1
                            failed_items.append({
                                'id': str(result.get('item_id') or product_info.get('item_id') or ''),
                                'reason': result.get('message') or '未知错误',
                                'details': result.get('failed_details', [])
                            })
                        else:
                            success_count += 1

                        # 改为每5个更新一次，反馈更及时
                        if processed_count % 5 == 0 or processed_count == total_products:
                            # 计算进度 (避免除以0)
                            progress = int((processed_count / total_products) * 100) if total_products > 0 else 100
                            db.update_scrape_status(
                                processed=processed_count,
                                success=success_count,
                                failed=failed_count,
                                image_failed=image_failed_count,
                                index_failed=index_failed_count,
                                progress=progress,
                                message=f'正在抓取详情与图片... ({processed_count}/{total_products})'
                            )
                    except Exception as e:
                        logger.error(f"商品处理异常: {e}")
                        processed_count += 1
                        failed_count += 1
                        failed_items.append({
                            'id': str(product_info.get('item_id', '')),
                            'reason': str(e)
                        })
        finally:
            if not stop_requested:
                executor.shutdown(wait=True)

    # 结束
    if stop_requested or scrape_stop_event.is_set() or db.get_scrape_status().get('stop_signal', False):
        final_message = f'抓取已停止，已处理 {processed_count} 个商品'
    else:
        if failed_count > 0 or image_failed_count > 0 or index_failed_count > 0:
            final_message = (
                f'抓取完成，共处理 {processed_count} 个商品，成功 {success_count} 个，'
                f'失败 {failed_count} 个 (图片失败 {image_failed_count} / 索引失败 {index_failed_count})'
            )
        else:
            final_message = f'抓取完成，共处理 {processed_count} 个商品，成功 {success_count} 个'

    db.update_scrape_status(
        is_scraping=False,
        completed=True,
        progress=100,
        processed=processed_count,
        success=success_count,
        failed=failed_count,
        image_failed=image_failed_count,
        index_failed=index_failed_count,
        failed_items=failed_items,
        message=final_message
    )
    if failed_count > 0 or image_failed_count > 0 or index_failed_count > 0:
        logger.info(
            f"✅ 店铺 {shop_id} 抓取任务完成: 成功 {success_count} / 失败 {failed_count} / 总计 {processed_count}"
        )
    else:
        logger.info(
            f"✅ 店铺 {shop_id} 抓取任务完成: 成功 {success_count} / 总计 {processed_count}"
        )

    return {
        "total_products": processed_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "image_failed_count": image_failed_count,
        "index_failed_count": index_failed_count
    }

def process_and_save_single_product_sync(product_info):
    """同步处理单个商品，避免重复处理"""
    try:
        item_id = product_info.get('item_id', '')

        # === 检查停止事件或停止信号 ===
        global scrape_stop_event
        if scrape_stop_event.is_set():
            logger.debug(f"🔴 处理商品前检测到停止事件，取消处理商品 {item_id}")
            return {
                'status': 'cancelled',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '任务已取消'
            }

        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.debug(f"🔴 处理商品前检测到停止信号，取消处理商品 {item_id}")
            return {
                'status': 'cancelled',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '任务已取消'
            }

        # === 0. 基于item_id的强力去重 ===
        if db.get_product_by_item_id(item_id):
            logger.debug(f"⏭️ 商品 {item_id} 已存在，跳过重复处理")
            return {
                'status': 'skipped',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '商品已存在'
            }

        # 1. 抓取详情
        from app import process_single_product  # 引用 app.py 中的逻辑
        product_data = process_single_product(product_info)

        if not product_data:
            logger.warning(f"❌ 商品 {item_id} 抓取失败：未获取到商品详情")
            return {
                'status': 'failed',
                'item_id': item_id,
                'failed': True,
                'image_failed': False,
                'index_failed': False,
                'message': '未获取到商品详情'
            }

        product_title = product_data.get('title', '')
        # === 再次检查停止状态 ===
        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.debug(f"🔴 抓取详情后检测到停止信号，取消处理商品 {item_id}")
            return {
                'status': 'cancelled',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '任务已取消'
            }

        # 2. 再次查重 (双重保险)
        if db.get_product_by_url(product_data['product_url']):
            logger.debug(f"⏭️ 商品URL已存在: {product_data['product_url']}")
            return {
                'status': 'skipped',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '商品已存在'
            }

        # 3. 入库 (添加item_id字段)
        product_data['item_id'] = item_id  # 确保item_id被保存
        product_id = db.insert_product(product_data)

        logger.debug(f"商品 {item_id} 入库完成，数据库ID: {product_id}")

        # === 再次检查停止状态 ===
        current_status = db.get_scrape_status()
        if current_status.get('stop_signal', False):
            logger.debug(f"🔴 入库后检测到停止信号，商品 {item_id} 已入库但跳过图片处理")
            return {
                'status': 'partial',
                'item_id': item_id,
                'failed': False,
                'image_failed': False,
                'index_failed': False,
                'message': '商品已入库，图片处理被取消'
            }

        # 4. 图片处理
        image_stats = {
            'total_urls': 0,
            'download_failed': 0,
            'processed': 0,
            'faiss_failed': False,
            'failed_details': []
        }
        processed_count = 0
        if product_data.get('images'):
            from app import save_product_images_unified
            processed_count, image_stats = save_product_images_unified(
                product_id,
                product_data['images'],
                shutdown_event=scrape_stop_event
            )

        image_total = len(product_data.get('images') or [])
        failed_details = image_stats.get('failed_details', [])
        download_failed = len(failed_details)

        if image_total == 0:
            logger.error(f"❌ 商品 {item_id} {product_title} 未找到任何图片，回滚删除")
            try:
                db.delete_product_images(product_id)
            except Exception as delete_error:
                logger.error(f"回滚删除商品失败: {delete_error}")
            return {
                'status': 'failed',
                'item_id': item_id,
                'title': product_title,
                'images_total': image_total,
                'images_processed': processed_count,
                'failed': True,
                'image_failed': True,
                'message': '未找到任何图片'
            }

        if processed_count == 0:
            logger.error(f"❌ 商品 {item_id} {product_title} 所有图片获取失败，回滚删除")
            try:
                db.delete_product_images(product_id)
            except Exception as delete_error:
                logger.error(f"回滚删除商品失败: {delete_error}")
            return {
                'status': 'failed',
                'item_id': item_id,
                'title': product_title,
                'images_total': image_total,
                'images_processed': processed_count,
                'failed': True,
                'image_failed': True,
                'failed_details': failed_details,
                'message': f"30次尝试后所有 {image_total} 张图片均失败"
            }

        if processed_count < image_total:
            missing_indices = [str(detail.get('index')) for detail in failed_details if detail.get('index') is not None]
            warn_msg = f"部分成功: 缺 {len(missing_indices)} 张 (索引: {','.join(missing_indices)})"
            logger.warning(f"⚠️ 商品 {item_id} {product_title} {warn_msg}，保留已获取数据")
            return {
                'status': 'success',
                'item_id': item_id,
                'title': product_title,
                'images_total': image_total,
                'images_processed': processed_count,
                'download_failed': download_failed,
                'failed': False,
                'failed_details': failed_details,
                'message': warn_msg
            }

        stored_count = image_stats.get('stored', 0)
        duplicate_count = image_stats.get('duplicates', 0)
        existing_count = image_stats.get('existing', 0)

        if stored_count == image_total:
            logger.info(f"✅ 商品 {item_id} {product_title} 完美抓取 ({processed_count}/{image_total})")
        else:
            logger.info(
                f"✅ 商品 {item_id} {product_title} 抓取完成 "
                f"(总 {image_total}, 写入 {stored_count}, 重复 {duplicate_count}, 已有 {existing_count})"
            )
        return {
            'status': 'success',
            'item_id': item_id,
            'title': product_title,
            'images_total': image_total,
            'images_processed': processed_count,
            'failed': False,
            'failed_details': failed_details
        }
    except Exception as e:
        logger.error(f"❌ 处理商品出错 {product_info.get('item_id')}: {e}")
        return {
            'status': 'failed',
            'item_id': product_info.get('item_id'),
            'failed': True,
            'image_failed': False,
            'index_failed': False,
            'message': str(e)
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

            # 优先使用从商品详情中获取的店铺名称，如果没有则使用传入的
            actual_shop_name = product_details.get('shop_name', '') or shop_name

            return {
                'product_url': item_url,
                'title': product_details.get('title', ''),
                'description': product_details.get('description', ''),
                'english_title': english_title,
                'cnfans_url': generate_cnfans_url(item_id),
                'acbuy_url': generate_acbuy_url(item_url),
                'shop_name': actual_shop_name,
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

def save_product_images_unified(product_id, image_urls, max_workers=None, shutdown_event=None):
    """
    【最终增强版】统一批量图片处理
    特性：
    1. 深度校验图片文件头（防止 0 字节文件或 HTML 伪装成图片）。
    2. 特征提取失败直接视为致命错误（避免对坏图无效重试）。
    3. HTTP 404/403 视为致命错误。
    3. 返回详细的失败原因报告。
    """
    import time
    import concurrent.futures
    import requests
    import os
    import random
    from PIL import Image, UnidentifiedImageError

    stats = {
        'total_urls': len(image_urls),
        'processed': 0,
        'stored': 0,
        'duplicates': 0,
        'existing': 0,
        'fatal': 0,
        'retry_failed': 0,
        'failed_details': [],
        'download_failed': 0,
        'faiss_failed': False
    }

    if not image_urls:
        return 0, stats

    try:
        existing_images = db.get_product_images(product_id)
        existing_indices = {img['image_index'] for img in existing_images}
        existing_feats = [img['features'] for img in existing_images if img.get('features') is not None]
    except Exception:
        existing_indices = set()
        existing_feats = []

    pending_items = []
    for idx, url in enumerate(image_urls):
        if idx not in existing_indices:
            pending_items.append((idx, url))
        else:
            stats['processed'] += 1
            stats['existing'] += 1

    if not pending_items:
        return stats['processed'], stats

    max_retries = 30

    def verify_image_file(file_path):
        try:
            if os.path.getsize(file_path) < 100:
                return False, "文件过小"
            with Image.open(file_path) as img:
                img.verify()
            return True, None
        except UnidentifiedImageError:
            return False, "无法识别的图片格式"
        except Exception as e:
            return False, f"图片文件损坏: {str(e)}"

    def process_batch(items_to_process):
        current_downloaded = []
        retry_list = []
        fatal_list = []

        workers = min(getattr(config, 'DOWNLOAD_THREADS', 8), len(items_to_process))

        def download_task(item):
            idx, url = item
            if shutdown_event and shutdown_event.is_set():
                return ('RETRY', item, 'Cancelled')

            save_dir = os.path.join(config.IMAGE_SAVE_DIR, str(product_id))
            os.makedirs(save_dir, exist_ok=True)
            timestamp = int(time.time() * 1000000)
            filename = f"{product_id}_{idx}_{timestamp}.jpg"
            save_path = os.path.join(save_dir, filename)

            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://weidian.com/'
                }

                resp = requests.get(
                    url,
                    timeout=(10, 20),
                    proxies={'http': None, 'https': None},
                    headers=headers
                )

                if resp.status_code in [403, 404]:
                    return ('FATAL', item, f"HTTP {resp.status_code} (死链接)")

                if resp.status_code != 200:
                    return ('RETRY', item, f"HTTP {resp.status_code}")

                with open(save_path, 'wb') as f:
                    f.write(resp.content)

                is_valid, reason = verify_image_file(save_path)
                if not is_valid:
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                    if reason and "无法识别" in reason:
                        return ('FATAL', item, f"无效图片: {reason}")
                    return ('RETRY', item, f"文件损坏: {reason}")

                return ('SUCCESS', (idx, save_path), None)
            except Exception as e:
                return ('RETRY', item, str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(download_task, item) for item in items_to_process]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if not result:
                    continue
                status, data, error = result
                if status == 'SUCCESS':
                    current_downloaded.append(data)
                elif status == 'FATAL':
                    fatal_list.append((data, error))
                else:
                    retry_list.append(data)

        if not current_downloaded:
            return [], retry_list, fatal_list

        extractor = get_global_feature_extractor()
        if extractor is None:
            for _, path in current_downloaded:
                try:
                    os.remove(path)
                except Exception:
                    pass
            retry_list.extend([(idx, image_urls[idx]) for idx, _ in current_downloaded])
            return [], retry_list, fatal_list

        processed_indices = []
        vectors_to_add = []

        for index, save_path in current_downloaded:
            if shutdown_event and shutdown_event.is_set():
                retry_list.append((index, image_urls[index]))
                continue

            try:
                features = None
                with GLOBAL_AI_SEMAPHORE:
                    try:
                        features = extractor.extract_feature(save_path)
                    except Exception as e:
                        logger.error(f"特征提取底层错误: {e}")
                        features = None

                if features is None:
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                    fatal_list.append(((index, image_urls[index]), "AI无法提取特征(图片可能损坏)"))
                    continue

                is_dup, score = check_duplicate_image(features, existing_feats, threshold=0.995)
                if is_dup:
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                    stats['duplicates'] += 1
                    processed_indices.append(index)
                    continue

                existing_feats.append(features)
                img_db_id = db.insert_image_record(product_id, save_path, index, features)

                if img_db_id:
                    vectors_to_add.append((img_db_id, features))
                    processed_indices.append(index)
                    stats['stored'] += 1
                else:
                    retry_list.append((index, image_urls[index]))

            except Exception as e:
                logger.error(f"处理图片 {index} 异常: {e}")
                retry_list.append((index, image_urls[index]))

        if vectors_to_add:
            try:
                from vector_engine import get_vector_engine
                engine = get_vector_engine()
                with faiss_lock:
                    for img_id, feats in vectors_to_add:
                        engine.add_vector(img_id, feats)
                    engine.save()
            except Exception as e:
                logger.error(f"FAISS 写入失败: {e}")
                stats['faiss_failed'] = True

        return processed_indices, retry_list, fatal_list

    logger.info(f"🚀 [商品 {product_id}] 开始处理，待处理 {len(pending_items)} 张")

    for attempt in range(1, max_retries + 1):
        if not pending_items:
            break
        if shutdown_event and shutdown_event.is_set():
            break

        success_indices, retry_items, fatal_items = process_batch(pending_items)

        stats['processed'] += len(success_indices)

        for item, reason in fatal_items:
            idx, url = item
            logger.warning(f"❌ [商品 {product_id}] 图片 {idx} 发生致命错误，放弃: {reason}")
            stats['fatal'] += 1
            stats['failed_details'].append({
                'index': idx,
                'url': url,
                'reason': reason
            })

        pending_items = retry_items

        if not pending_items:
            break

        if attempt <= 5:
            sleep_time = random.uniform(1, 2)
        elif attempt <= 15:
            sleep_time = random.uniform(3, 5)
        else:
            sleep_time = random.uniform(5, 10)

        logger.warning(
            f"⚠️ [商品 {product_id}] 第 {attempt} 轮结束，{len(pending_items)} 张需重试，{len(fatal_items)} 张已放弃。等待 {sleep_time:.1f}s..."
        )
        time.sleep(sleep_time)

    for idx, url in pending_items:
        stats['failed_details'].append({
            'index': idx,
            'url': url,
            'reason': '超过最大重试次数 (可能网络超时)'
        })

    stats['download_failed'] = len(stats['failed_details'])
    stats['retry_failed'] = len(pending_items)

    if stats['download_failed'] > 0:
        logger.error(f"❌ [商品 {product_id}] 最终结果: {stats['processed']} 成功, {stats['download_failed']} 失败")
    else:
        logger.info(f"✅ [商品 {product_id}] 全部处理成功")

    logger.info(
        f"🧾 [商品 {product_id}] 图片统计: total={stats['total_urls']}, stored={stats['stored']}, "
        f"existing={stats['existing']}, duplicate={stats['duplicates']}, fatal={stats['fatal']}, "
        f"retry_failed={stats['retry_failed']}"
    )

    return stats['processed'], stats

def run_cleanup_task():
    """后台清理任务，定期清理数据库和内存中的过期记录"""
    while True:
        try:
            # 每小时执行一次
            time.sleep(3600)
            logger.info("⚙️ 开始执行后台清理任务...")

            # 1. 清理已处理的消息ID表
            db.cleanup_processed_messages()
            logger.info("✅ 已清理过期的消息ID记录")

            # 2. 清理内存中的冷却记录
            try:
                from bot import cleanup_expired_cooldowns
                cleanup_expired_cooldowns()
                logger.info("✅ 已清理内存中过期的冷却状态")
            except ImportError:
                logger.warning("无法导入bot模块进行冷却清理，跳过")

        except Exception as e:
            logger.error(f"后台清理任务异常: {e}")

if __name__ == '__main__':
    # 【Windows兼容性修复】必须在最开始调用
    multiprocessing.freeze_support()

    import atexit
    import signal
    import time

    # 【核心修复】只在主进程执行初始化
    initialize_runtime()

    # 全局变量用于控制优雅关闭
    import threading
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

    # 启动 Flask 服务
    print("🚀 服务启动中...")
    try:
        # 关闭 debug 模式，避免 Flask 重载器导致双重初始化
        # 【关键修改】添加 use_reloader=False 禁用Flask重载器，避免双重进程
        app.run(host='0.0.0.0', port=5001, debug=False, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Received KeyboardInterrupt, shutting down...")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        signal_handler(signal.SIGINT, None)
    finally:
        print("👋 Flask API shutdown complete")
