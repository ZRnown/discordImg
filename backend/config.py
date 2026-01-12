import os
from dotenv import load_dotenv

# 加载 .env 文件 - 支持从项目根目录或backend目录加载
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.dirname(os.path.abspath(__file__))

# 优先从项目根目录加载，其次从backend目录加载
env_paths = [
    os.path.join(project_root, '.env'),
    os.path.join(backend_dir, '.env')
]

for env_path in env_paths:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ 已加载环境变量文件: {env_path}")
        break
else:
    print("ℹ️  未找到.env文件，使用系统环境变量")

class Config:
    # === 基础服务配置 ===
    HOST = os.getenv('HOST', '0.0.0.0')  # 默认监听所有接口
    PORT = int(os.getenv('PORT', 5001))  # 默认端口
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'  # 调试模式

    # === 设备配置 ===
    DEVICE = os.getenv('DEVICE', 'cpu')  # CPU/GPU设备

    # === Discord 配置 ===
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0
    DISCORD_SIMILARITY_THRESHOLD = float(os.getenv('DISCORD_SIMILARITY_THRESHOLD', '0.6'))

    # === 全局回复延迟配置 ===
    GLOBAL_REPLY_MIN_DELAY = float(os.getenv('GLOBAL_REPLY_MIN_DELAY', '3.0'))
    GLOBAL_REPLY_MAX_DELAY = float(os.getenv('GLOBAL_REPLY_MAX_DELAY', '8.0'))

    # === 频道配置 ===
    CNFANS_CHANNEL_ID = int(os.getenv('CNFANS_CHANNEL_ID', 0)) if os.getenv('CNFANS_CHANNEL_ID') else 0
    ACBUY_CHANNEL_ID = int(os.getenv('ACBUY_CHANNEL_ID', 0)) if os.getenv('ACBUY_CHANNEL_ID') else 0

    # === 关键词转发配置 ===
    FORWARD_KEYWORDS = os.getenv('FORWARD_KEYWORDS', '商品,货源,进货,批发,代理').split(',')  # 触发转发的关键词
    FORWARD_TARGET_CHANNEL_ID = int(os.getenv('FORWARD_TARGET_CHANNEL_ID', 0)) if os.getenv('FORWARD_TARGET_CHANNEL_ID') else 0  # 转发目标频道ID

    # === 安全配置 (简化版 - 解决HTTP IP访问问题) ===
    # 固定密钥，防止重启服务后用户掉线
    SECRET_KEY = os.getenv('SECRET_KEY', 'my-fixed-secret-key-888888')

    # 允许HTTP访问（关键修改）
    SESSION_COOKIE_SECURE = False  # 允许在非HTTPS下传输Cookie
    SESSION_COOKIE_SAMESITE = 'Lax'  # 防止浏览器拦截跨站请求
    SESSION_LIFETIME = int(os.getenv('SESSION_LIFETIME', 86400 * 30))  # 30天不过期

    # === CORS配置（简化版 - 允许所有来源） ===
    # 简单粗暴，允许所有来源，避免浏览器报错
    CORS_ORIGINS = ["*"]

    # === API服务地址配置 ===
    # 后端API地址（本地服务）
    BACKEND_API_URL = os.getenv('BACKEND_API_URL', 'http://127.0.0.1:5001')
    # 前端Next.js API地址（用于机器人回调）
    NEXTJS_API_URL = os.getenv('NEXTJS_API_URL', f'{BACKEND_API_URL}/api')

    # === 机器人配置 ===
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX', '!')

    # === AI模型配置 ===
    # DINOv2配置
    DINO_MODEL_NAME = os.getenv('DINO_MODEL_NAME', 'facebook/dinov2-small')
    VECTOR_DIMENSION = 384 if 'small' in DINO_MODEL_NAME else 768
    SIMILARITY_THRESHOLD = 0.99  # 图片查重阈值，99%相似度

    # YOLO-World配置
    YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'yolov8s-world.pt')
    USE_YOLO_CROP = os.getenv('USE_YOLO_CROP', 'True').lower() == 'true'

    # === 多线程配置 ===
    SCRAPE_THREADS = int(os.getenv('SCRAPE_THREADS', '5'))  # 商品抓取线程数（调低避免服务器过载）
    DOWNLOAD_THREADS = int(os.getenv('DOWNLOAD_THREADS', '8'))  # 图片下载线程数
    FEATURE_EXTRACT_THREADS = int(os.getenv('FEATURE_EXTRACT_THREADS', '4'))  # 特征提取线程数

    # === FAISS向量搜索配置 ===
    FAISS_INDEX_FILE = os.path.join(os.path.dirname(__file__), 'data', 'faiss_index.bin')
    FAISS_ID_MAP_FILE = os.path.join(os.path.dirname(__file__), 'data', 'faiss_id_map.pkl')
    FAISS_HNSW_M = int(os.getenv('FAISS_HNSW_M', '64'))
    FAISS_EF_CONSTRUCTION = int(os.getenv('FAISS_EF_CONSTRUCTION', '80'))
    FAISS_EF_SEARCH = int(os.getenv('FAISS_EF_SEARCH', '64'))

    # === 文件路径配置 ===
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # 项目根目录
    DATA_DIR = os.path.join(BASE_DIR, 'backend', 'data')
    IMAGE_SAVE_DIR = os.path.join(DATA_DIR, 'scraped_images')  # 图片保存目录
    LOG_DIR = os.path.join(DATA_DIR, 'logs')  # 日志目录

    # === 数据库配置 ===
    DATABASE_PATH = os.path.join(DATA_DIR, 'metadata.db')

    # === 网络和超时配置 ===
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))  # HTTP请求超时时间(秒)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))  # 最大重试次数

    # === 前端配置 ===
    # HTTP IP访问时必须设置为development，否则Cookie无法正常工作
    NODE_ENV = os.getenv('NODE_ENV', 'development')
    NEXT_PUBLIC_BACKEND_URL = os.getenv('NEXT_PUBLIC_BACKEND_URL', 'http://127.0.0.1:5001')

    # === 超时和重试配置 ===
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))  # HTTP请求超时时间(秒)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))  # 最大重试次数

    # === 会话配置 ===
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SESSION_LIFETIME = int(os.getenv('SESSION_LIFETIME', '86400'))  # 会话生命周期(秒)

    @classmethod
    def init_dirs(cls):
        """初始化必要的目录"""
        dirs_to_create = [
            cls.DATA_DIR,
            cls.IMAGE_SAVE_DIR,
            cls.LOG_DIR
        ]
        for dir_path in dirs_to_create:
            os.makedirs(dir_path, exist_ok=True)

# 初始化配置
config = Config()
config.init_dirs()
