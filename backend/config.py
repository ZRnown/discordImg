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

    # === 延迟配置 ===
    GLOBAL_REPLY_MIN_DELAY = 3.0
    GLOBAL_REPLY_MAX_DELAY = 8.0

    # === 频道配置 ===
    CNFANS_CHANNEL_ID = 0
    ACBUY_CHANNEL_ID = 0
    FORWARD_KEYWORDS = []
    FORWARD_TARGET_CHANNEL_ID = 0

    # === API 地址 ===
    BACKEND_API_URL = 'http://127.0.0.1:5001'
    NEXTJS_API_URL = f'{BACKEND_API_URL}/api'

    # === 机器人 ===
    COMMAND_PREFIX = '!'

    # === AI 模型 ===
    DINO_MODEL_NAME = 'facebook/dinov2-small'
    VECTOR_DIMENSION = 384
    YOLO_MODEL_PATH = 'yolov8s-world.pt'
    USE_YOLO_CROP = True

    # === 多线程 ===
    SCRAPE_THREADS = 10  # 提高并发数
    DOWNLOAD_THREADS = 8  # 图片下载线程
    FEATURE_EXTRACT_THREADS = 4  # AI 线程 (不要太大，否则 CPU 爆满)

    # === FAISS ===
    FAISS_HNSW_M = 64
    FAISS_EF_CONSTRUCTION = 80
    FAISS_EF_SEARCH = 64

    # === 路径 ===
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'backend', 'data')
    # 确保这些路径是绝对路径
    IMAGE_SAVE_DIR = os.path.join(DATA_DIR, 'scraped_images')
    LOG_DIR = os.path.join(DATA_DIR, 'logs')
    DATABASE_PATH = os.path.join(DATA_DIR, 'metadata.db')

    FAISS_INDEX_FILE = os.path.join(DATA_DIR, 'faiss_index.bin')
    FAISS_ID_MAP_FILE = os.path.join(DATA_DIR, 'faiss_id_map.pkl')

    # === 网络 ===
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3

    @classmethod
    def init_dirs(cls):
        for dir_path in [cls.DATA_DIR, cls.IMAGE_SAVE_DIR, cls.LOG_DIR]:
            os.makedirs(dir_path, exist_ok=True)

# 初始化
config = Config()
config.init_dirs()