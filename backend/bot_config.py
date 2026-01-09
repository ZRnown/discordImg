import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else 0

    # API服务地址（本地服务）
    NEXTJS_API_URL = 'http://localhost:5001/api'
    PADDLE_SERVICE_URL = 'http://localhost:5001'

    # 机器人配置
    COMMAND_PREFIX = '!'

config = Config()
