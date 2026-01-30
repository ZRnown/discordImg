import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    # === 基础配置 ===
    HOST = '0.0.0.0'
    PORT = 5001
    DEBUG = False  # 生产环境建议关闭调试模式以减少日志

    # === 关键修复：SECRET_KEY 必须在类里面 ===
    SECRET_KEY = 'my-fixed-secret-key-888888'

    # === Session配置 ===
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_LIFETIME = 86400 * 30

    # === CORS ===
    CORS_ORIGINS = ["*"]

    # === 设备配置 ===
    DEVICE = os.getenv('DEVICE', 'cpu')

    # === Discord 配置 ===
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0
    DISCORD_SIMILARITY_THRESHOLD = 0.6
    # 相似度过高时不回复（用于屏蔽过于相似的图片）
    DISCORD_SIMILARITY_BLOCK_THRESHOLD = 0.995

    # === 延迟配置 ===
    GLOBAL_REPLY_MIN_DELAY = 3.0
    GLOBAL_REPLY_MAX_DELAY = 8.0

    # === 频道配置 ===
    CNFANS_CHANNEL_ID = 0
    ACBUY_CHANNEL_ID = 0
    FORWARD_KEYWORDS = []
    FORWARD_TARGET_CHANNEL_ID = 0

    # === API 地址 ===
    BACKEND_API_URL = os.getenv('BACKEND_API_URL', 'http://127.0.0.1:5001')
    NEXTJS_API_URL = f'{BACKEND_API_URL}/api'

    # === 机器人 ===
    COMMAND_PREFIX = '!'

    # === AI 模型 ===
    DINO_MODEL_NAME = 'facebook/dinov2-small'
    VECTOR_DIMENSION = 384
    YOLO_MODEL_PATH = 'yolov8s-world.pt'
    USE_YOLO_CROP = True

    # === 多线程配置 (针对 10核 CPU 优化) ===
    # 商品信息抓取是IO密集型，可以开大
    SCRAPE_THREADS = int(os.getenv('SCRAPE_THREADS', '5'))
    
    # 图片下载也是IO密集型，可以开更大
    DOWNLOAD_THREADS = int(os.getenv('DOWNLOAD_THREADS', '8'))

    # AI 推理的并发控制 (CPU密集型)：
    # - AI_INTRA_THREADS：单个推理任务内部使用的 CPU 核心数
    # - AI_MAX_WORKERS：同时跑多少个"图片特征提取任务"
    # 【优化建议】如果是 10核 CPU，单次搜索设为 4-6 可以显著加快单张图的搜索速度
    # 【修复】从6改为4，为Flask Web服务留出CPU核心，避免Bot和Web服务争抢资源导致UI卡死
    # 优化后策略：单张图搜索使用4核，批量抓取时2个Worker * 4核 = 8核，留2核给Flask
    AI_INTRA_THREADS = int(os.getenv('AI_INTRA_THREADS', '4'))
    AI_MAX_WORKERS = int(os.getenv('AI_MAX_WORKERS', '2'))

    # 新的 save_product_images_unified 已不依赖该参数做图片特征线程池，保留字段主要用于兼容旧逻辑。
    FEATURE_EXTRACT_THREADS = int(os.getenv('FEATURE_EXTRACT_THREADS', '4'))

    # === FAISS ===
    FAISS_HNSW_M = 64
    FAISS_EF_CONSTRUCTION = 128
    FAISS_EF_SEARCH = 128

    # === 路径 ===
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'backend', 'data')
    # 确保这些路径是绝对路径
    IMAGE_SAVE_DIR = os.path.join(DATA_DIR, 'scraped_images')
    MESSAGE_FILTER_IMAGE_DIR = os.path.join(DATA_DIR, 'message_filter_images')
    LOG_DIR = os.path.join(DATA_DIR, 'logs')
    DATABASE_PATH = os.path.join(DATA_DIR, 'metadata.db')

    FAISS_INDEX_FILE = os.path.join(DATA_DIR, 'faiss_index.bin')
    FAISS_ID_MAP_FILE = os.path.join(DATA_DIR, 'faiss_id_map.pkl')

    # === 网络 ===
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3

    @classmethod
    def init_dirs(cls):
        for dir_path in [cls.DATA_DIR, cls.IMAGE_SAVE_DIR, cls.MESSAGE_FILTER_IMAGE_DIR, cls.LOG_DIR]:
            os.makedirs(dir_path, exist_ok=True)

# 初始化
config = Config()
config.init_dirs()
