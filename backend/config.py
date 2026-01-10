import os

class Config:
    # Discord 配置
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0
    DISCORD_SIMILARITY_THRESHOLD = float(os.getenv('DISCORD_SIMILARITY_THRESHOLD', '0.6'))

    # 全局回复延迟配置
    GLOBAL_REPLY_MIN_DELAY = float(os.getenv('GLOBAL_REPLY_MIN_DELAY', '3.0'))
    GLOBAL_REPLY_MAX_DELAY = float(os.getenv('GLOBAL_REPLY_MAX_DELAY', '8.0'))

    # 频道配置
    CNFANS_CHANNEL_ID = int(os.getenv('CNFANS_CHANNEL_ID', 0)) if os.getenv('CNFANS_CHANNEL_ID') else 0
    ACBUY_CHANNEL_ID = int(os.getenv('ACBUY_CHANNEL_ID', 0)) if os.getenv('ACBUY_CHANNEL_ID') else 0

    # 关键词转发配置
    FORWARD_KEYWORDS = os.getenv('FORWARD_KEYWORDS', '商品,货源,进货,批发,代理').split(',')  # 触发转发的关键词
    FORWARD_TARGET_CHANNEL_ID = int(os.getenv('FORWARD_TARGET_CHANNEL_ID', 0)) if os.getenv('FORWARD_TARGET_CHANNEL_ID') else 0  # 转发目标频道ID

    # API服务地址（本地服务）
    NEXTJS_API_URL = 'http://localhost:5001/api'
    PADDLE_SERVICE_URL = 'http://localhost:5001'

    # 机器人配置
    COMMAND_PREFIX = '!'

    # DINOv2 & FAISS 配置
    DINO_MODEL_NAME = os.getenv('DINO_MODEL_NAME', 'facebook/dinov2-small')
    VECTOR_DIMENSION = 384 if 'small' in DINO_MODEL_NAME else 768
    SIMILARITY_THRESHOLD = 0.6

    # 图像处理配置
    YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'yolov8n.pt')
    USE_YOLO_CROP = os.getenv('USE_YOLO_CROP', 'False').lower() == 'true'  # 暂时禁用YOLO裁剪

    # 多线程配置
    DOWNLOAD_THREADS = int(os.getenv('DOWNLOAD_THREADS', '4'))  # 图片下载线程数
    FEATURE_EXTRACT_THREADS = int(os.getenv('FEATURE_EXTRACT_THREADS', '4'))  # 特征提取线程数


    # FAISS 配置
    FAISS_INDEX_FILE = os.path.join(os.path.dirname(__file__), 'data', 'faiss_index.bin')
    FAISS_ID_MAP_FILE = os.path.join(os.path.dirname(__file__), 'data', 'faiss_id_map.pkl')
    FAISS_HNSW_M = int(os.getenv('FAISS_HNSW_M', '64'))
    FAISS_EF_CONSTRUCTION = int(os.getenv('FAISS_EF_CONSTRUCTION', '80'))
    FAISS_EF_SEARCH = int(os.getenv('FAISS_EF_SEARCH', '64'))

    # 图片保存目录
    IMAGE_SAVE_DIR = os.path.join(os.path.dirname(__file__), 'data')

    # 服务配置
    HOST = '0.0.0.0'
    PORT = int(os.getenv('PORT', 5001))
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    # 设备配置
    DEVICE = os.getenv('DEVICE', 'cpu')

config = Config()
