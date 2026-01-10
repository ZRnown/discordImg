import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0
    DISCORD_SIMILARITY_THRESHOLD = float(os.getenv('DISCORD_SIMILARITY_THRESHOLD', '0.6'))  # Discord机器人相似度阈值

    # 全局回复延迟配置
    GLOBAL_REPLY_MIN_DELAY = int(os.getenv('GLOBAL_REPLY_MIN_DELAY', '3'))  # 全局最小延迟秒数
    GLOBAL_REPLY_MAX_DELAY = int(os.getenv('GLOBAL_REPLY_MAX_DELAY', '8'))  # 全局最大延迟秒数

    # 关键词转发配置
    FORWARD_KEYWORDS = os.getenv('FORWARD_KEYWORDS', '商品,货源,进货,批发,代理').split(',')  # 触发转发的关键词
    FORWARD_TARGET_CHANNEL_ID = int(os.getenv('FORWARD_TARGET_CHANNEL_ID', 0)) if os.getenv('FORWARD_TARGET_CHANNEL_ID') else 0  # 转发目标频道ID

    # API服务地址（本地服务）
    NEXTJS_API_URL = 'http://localhost:5001/api'
    PADDLE_SERVICE_URL = 'http://localhost:5001'

    # 机器人配置
    COMMAND_PREFIX = '!'

config = Config()
