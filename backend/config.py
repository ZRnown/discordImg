import os

class Config:
    # Discord 配置
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0
    DISCORD_SIMILARITY_THRESHOLD = float(os.getenv('DISCORD_SIMILARITY_THRESHOLD', '0.4'))  # Discord机器人相似度阈值

    # PP-ShiTuV2 & Milvus 配置
    VECTOR_DIMENSION = 512  # PP-ShiTuV2 输出512维特征向量
    SIMILARITY_THRESHOLD = 0.3  # Milvus 相似度阈值 (0.3 = 30%相似度，更宽容)

    # 图像处理配置 (PP-ShiTuV2 自动处理)
    IMAGE_SIZE = (224, 224)  # 预处理后的大小
    MEAN = [0.485, 0.456, 0.406]  # ImageNet 均值
    STD = [0.229, 0.224, 0.225]   # ImageNet 标准差

    # 服务配置
    HOST = '0.0.0.0'
    PORT = int(os.getenv('PORT', 5001))
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    # Milvus Lite 配置
    MILVUS_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'milvus.db')
    MILVUS_COLLECTION_NAME = "image_embeddings"
    MILVUS_METRIC_TYPE = "COSINE"  # 余弦相似度
    # 可选主体检测配置（默认关闭）
    USE_DETECT = os.getenv('USE_DETECT', 'False').lower() == 'true'
    DETECTION_MODEL_DIR = os.getenv('DETECTION_MODEL_DIR', os.path.join(os.path.dirname(__file__), 'models', 'detection'))

config = Config()
