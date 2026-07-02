import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == '':
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == '':
        return default
    try:
        return float(value)
    except ValueError:
        return default

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
    DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN = _env_float('DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN', 0.0)
    DISCORD_MESSAGE_STAGE_SLOW_SECONDS = _env_float('DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0)
    LIVE_IMAGE_SEARCH_STRATEGY = os.getenv('LIVE_IMAGE_SEARCH_STRATEGY', 'siglip2_rerank')
    LIVE_IMAGE_SEARCH_STREAMING_ENABLED = _env_bool('LIVE_IMAGE_SEARCH_STREAMING_ENABLED', False)
    LIVE_IMAGE_SEARCH_STREAMING_FORCE = _env_bool('LIVE_IMAGE_SEARCH_STREAMING_FORCE', False)
    LIVE_IMAGE_SEARCH_MAX_INFLIGHT = _env_int('LIVE_IMAGE_SEARCH_MAX_INFLIGHT', 1)
    LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE = _env_int('LIVE_IMAGE_SEARCH_QUEUE_MAX_SIZE', 64)
    LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS = _env_float('LIVE_IMAGE_SEARCH_QUEUE_TIMEOUT_SECONDS', 2.0)
    LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS = _env_float(
        'LIVE_IMAGE_SEARCH_EXECUTION_TIMEOUT_SECONDS',
        20.0,
    )
    # 对外部 Discord 服务器依赖实时监听时，保留 guild subscriptions，
    # 但不要默认开启 chunk_guilds_at_startup，否则会和无成员缓存配置冲突。
    DISCORD_CHUNK_GUILDS_AT_STARTUP = _env_bool('DISCORD_CHUNK_GUILDS_AT_STARTUP', False)
    DISCORD_GUILD_SUBSCRIPTIONS = _env_bool('DISCORD_GUILD_SUBSCRIPTIONS', True)
    DISCORD_HEARTBEAT_TIMEOUT = _env_float('DISCORD_HEARTBEAT_TIMEOUT', 120.0)
    DISCORD_MAX_MESSAGES = _env_int('DISCORD_MAX_MESSAGES', 200)
    DISCORD_STARTUP_STAGGER_SECONDS = _env_float('DISCORD_STARTUP_STAGGER_SECONDS', 1.5)
    DISCORD_SEND_MAX_INFLIGHT = _env_int('DISCORD_SEND_MAX_INFLIGHT', 1)
    DISCORD_SEND_INTERVAL_SECONDS = _env_float('DISCORD_SEND_INTERVAL_SECONDS', 0.75)
    DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS = _env_float('DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS', 60.0)
    DISCORD_MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS = _env_float('DISCORD_MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS', 45.0)
    DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS = _env_float('DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS', 130.0)
    DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE = _env_int('DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE', 2)
    DISCORD_WATCHDOG_INTERVAL_SECONDS = _env_float('DISCORD_WATCHDOG_INTERVAL_SECONDS', 3.0)
    DISCORD_WATCHDOG_RESTART_INTERVAL_SECONDS = _env_float('DISCORD_WATCHDOG_RESTART_INTERVAL_SECONDS', 8.0)
    DISCORD_WATCHDOG_TASK_DONE_RESTART_INTERVAL_SECONDS = _env_float(
        'DISCORD_WATCHDOG_TASK_DONE_RESTART_INTERVAL_SECONDS',
        300.0,
    )
    DISCORD_WATCHDOG_DISCONNECTED_GRACE_SECONDS = _env_float(
        'DISCORD_WATCHDOG_DISCONNECTED_GRACE_SECONDS',
        8.0,
    )

    # === 延迟配置 ===
    GLOBAL_REPLY_MIN_DELAY = 1.0
    GLOBAL_REPLY_MAX_DELAY = 3.0

    # === 频道配置 ===
    CNFANS_CHANNEL_ID = 0
    ACBUY_CHANNEL_ID = 0
    FORWARD_KEYWORDS = []
    FORWARD_TARGET_CHANNEL_ID = 0

    # === API 地址 ===
    BACKEND_API_URL = os.getenv('BACKEND_API_URL', 'http://127.0.0.1:5001')
    PUBLIC_FRONTEND_BASE_URL = (
        os.getenv('PUBLIC_FRONTEND_BASE_URL')
        or os.getenv('NEXT_PUBLIC_FRONTEND_BASE_URL')
        or os.getenv('FRONTEND_URL')
        or ''
    ).strip().rstrip('/')
    NEXTJS_API_URL = f'{BACKEND_API_URL}/api'
    KEYWORD_IMAGE_SEARCH_PROVIDER = os.getenv('KEYWORD_IMAGE_SEARCH_PROVIDER', 'searchapi_google_images')
    GOOGLE_IMAGE_SEARCH_API_KEY = os.getenv('GOOGLE_IMAGE_SEARCH_API_KEY', '')
    GOOGLE_IMAGE_SEARCH_CX = os.getenv('GOOGLE_IMAGE_SEARCH_CX', '')
    SEARCHAPI_IMAGE_SEARCH_API_KEY = os.getenv('SEARCHAPI_IMAGE_SEARCH_API_KEY', '')
    KEYWORD_IMAGE_SEARCH_REQUEST_TIMEOUT_SECONDS = _env_float(
        'KEYWORD_IMAGE_SEARCH_REQUEST_TIMEOUT_SECONDS',
        20.0,
    )
    KEYWORD_IMAGE_SEARCH_INTERNAL_TIMEOUT_SECONDS = _env_float(
        'KEYWORD_IMAGE_SEARCH_INTERNAL_TIMEOUT_SECONDS',
        45.0,
    )
    KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS = _env_float(
        'KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS',
        8.0,
    )
    KEYWORD_TEXT_SEARCH_MAX_INFLIGHT = _env_int(
        'KEYWORD_TEXT_SEARCH_MAX_INFLIGHT',
        3,
    )
    DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS = _env_float(
        'DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS',
        30.0,
    )
    DISCORD_THREAD_REPLY_WAIT_TIMEOUT_SECONDS = _env_float(
        'DISCORD_THREAD_REPLY_WAIT_TIMEOUT_SECONDS',
        180.0,
    )
    DISCORD_THREAD_REPLY_WAIT_POLL_SECONDS = _env_float(
        'DISCORD_THREAD_REPLY_WAIT_POLL_SECONDS',
        2.0,
    )

    # === 机器人 ===
    COMMAND_PREFIX = '!'

    # === 检索缓存预热 ===
    RETRIEVAL_CACHE_STARTUP_WARMUP = _env_bool('RETRIEVAL_CACHE_STARTUP_WARMUP', False)
    RETRIEVAL_CACHE_STARTUP_COMPACTION = _env_bool('RETRIEVAL_CACHE_STARTUP_COMPACTION', False)
    RETRIEVAL_CACHE_STARTUP_LIMIT = _env_int('RETRIEVAL_CACHE_STARTUP_LIMIT', 200)
    RETRIEVAL_CACHE_REBUILD_LIMIT = _env_int('RETRIEVAL_CACHE_REBUILD_LIMIT', 200)
    RETRIEVAL_CACHE_AUTO_BACKFILL = _env_bool('RETRIEVAL_CACHE_AUTO_BACKFILL', False)
    RETRIEVAL_CACHE_AUTO_BACKFILL_BURST = _env_bool('RETRIEVAL_CACHE_AUTO_BACKFILL_BURST', False)
    RETRIEVAL_CACHE_AUTO_BATCH_LIMIT = _env_int('RETRIEVAL_CACHE_AUTO_BATCH_LIMIT', 24)
    RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL = _env_int('RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL', 180)
    RETRIEVAL_CACHE_AUTO_BATCH_COOLDOWN = _env_int('RETRIEVAL_CACHE_AUTO_BATCH_COOLDOWN', 3)
    RETRIEVAL_CACHE_AUTO_BACKFILL_TIMEOUT = _env_int('RETRIEVAL_CACHE_AUTO_BACKFILL_TIMEOUT', 1200)
    RETRIEVAL_CACHE_AUTO_BACKFILL_MAX_MISSING = _env_int('RETRIEVAL_CACHE_AUTO_BACKFILL_MAX_MISSING', 5000)
    RETRIEVAL_CACHE_AUTO_BACKFILL_EMERGENCY_BATCH_LIMIT = _env_int('RETRIEVAL_CACHE_AUTO_BACKFILL_EMERGENCY_BATCH_LIMIT', 2)
    RETRIEVAL_CACHE_BINARY_STORAGE_ENABLED = _env_bool('RETRIEVAL_CACHE_BINARY_STORAGE_ENABLED', False)
    LIVE_IMAGE_SEARCH_STARTUP_PREPARE_CATALOG = _env_bool('LIVE_IMAGE_SEARCH_STARTUP_PREPARE_CATALOG', False)
    LIVE_IMAGE_SEARCH_STARTUP_LOAD_SCOPED_CATALOGS = _env_bool('LIVE_IMAGE_SEARCH_STARTUP_LOAD_SCOPED_CATALOGS', False)

    # === AI 模型 ===
    DINO_MODEL_NAME = 'facebook/dinov2-small'
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

    # === 路径 ===
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'backend', 'data')
    # 确保这些路径是绝对路径
    IMAGE_SAVE_DIR = os.path.join(DATA_DIR, 'scraped_images')
    MESSAGE_FILTER_IMAGE_DIR = os.path.join(DATA_DIR, 'message_filter_images')
    WEBSITE_FILTER_IMAGE_DIR = os.path.join(DATA_DIR, 'website_filter_images')
    SEARCH_QUERY_IMAGE_DIR = os.path.join(DATA_DIR, 'search_query_images')
    LOG_DIR = os.path.join(DATA_DIR, 'logs')
    DATABASE_PATH = os.path.join(DATA_DIR, 'metadata.db')
    SEARCH_QUERY_IMAGE_RETENTION_DAYS = _env_int('SEARCH_QUERY_IMAGE_RETENTION_DAYS', 1)

    # === 网络 ===
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3

    @classmethod
    def init_dirs(cls):
        for dir_path in [
            cls.DATA_DIR,
            cls.IMAGE_SAVE_DIR,
            cls.MESSAGE_FILTER_IMAGE_DIR,
            cls.WEBSITE_FILTER_IMAGE_DIR,
            cls.SEARCH_QUERY_IMAGE_DIR,
            cls.LOG_DIR
        ]:
            os.makedirs(dir_path, exist_ok=True)

# 初始化
config = Config()
config.init_dirs()
