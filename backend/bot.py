import discord
import aiohttp
import logging
import time
import asyncio
import os
from bot_config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DiscordBotClient(discord.Client):
    def __init__(self):
        # discord.py-self 可能不需要 intents，或者使用不同的语法
        try:
            # 尝试使用标准的 intents
            intents = discord.Intents.default()
            intents.message_content = True
            intents.messages = True
            intents.guilds = True
            super().__init__(intents=intents)
        except AttributeError:
            # 如果 Intents 不存在，直接初始化（discord.py-self 可能不需要）
            super().__init__()
        self.current_token = None
        self.running = False

    async def on_ready(self):
        logger.info(f'Logged on as {self.user}')
        logger.info(f'Bot is ready!')
        self.running = True

    async def on_message(self, message):
        if not self.running:
            return

        # 忽略自己的消息
        if message.author == self.user:
            return

        # 只处理特定频道的消息（如果配置了频道ID）
        if config.DISCORD_CHANNEL_ID and message.channel.id != config.DISCORD_CHANNEL_ID:
            return

        # 检查消息是否包含图片
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    await self.handle_image(message, attachment)

    async def handle_image(self, message, attachment):
        try:
            # 下载图片
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()

                        # 发送处理中的消息
                        processing_msg = await message.channel.send('🔍 正在分析图片...')

                        # 调用 Paddle 服务识别图片
                        result = await self.recognize_image(image_data)

                        if result and result.get('success'):
                            product = result.get('product', {})
                            sku_id = result.get('skuId', '')
                            similarity = result.get('similarity', 0)

                            # 构建回复消息
                            response = f"""
🎯 **识别结果** (相似度: {similarity:.2%})

📦 **商品信息**
ID: {sku_id}
标题: {product.get('title', 'N/A')}
英文标题: {product.get('englishTitle', 'N/A')}

🔗 **链接**
微店: {product.get('weidianUrl', 'N/A')}
CNFans: {product.get('cnfansUrl', 'N/A')}
"""

                            # 使用全局延迟配置
                            if config.GLOBAL_REPLY_MIN_DELAY > 0 or config.GLOBAL_REPLY_MAX_DELAY > 0:
                                delay = random.uniform(config.GLOBAL_REPLY_MIN_DELAY, config.GLOBAL_REPLY_MAX_DELAY)
                                logger.info(f"延迟回复 {delay:.2f} 秒...")
                                await asyncio.sleep(delay)

                            await message.channel.send(response)
                        else:
                            await message.channel.send('❌ 未能识别出相似商品')

                        # 删除处理中的消息
                        await processing_msg.delete()

        except Exception as e:
            logger.error(f'Error handling image: {e}')
            await message.channel.send(f'❌ 处理图片时出错: {str(e)}')

    async def recognize_image(self, image_data):
        try:
            async with aiohttp.ClientSession() as session:
                # 准备图片数据
                form_data = aiohttp.FormData()
                form_data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
                form_data.add_field('threshold', str(config.DISCORD_SIMILARITY_THRESHOLD))

                # 调用 PP-ShiTuV2 + Milvus 服务（本地）
                async with session.post('http://localhost:5001/search_similar', data=form_data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result
                    else:
                        logger.error(f'PP-ShiTuV2 service error: {resp.status}')
                        return None

        except Exception as e:
            logger.error(f'Error recognizing image: {e}')
            return None

async def get_token_from_backend():
    """从后端 API 获取当前可用的 Discord token"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:5001/api/accounts/current') as resp:
                if resp.status == 200:
                    result = await resp.json()
                    token = result.get('token')
                    if token:
                        logger.info(f'Got token from backend for account: {result.get("username")}')
                        return token
    except Exception as e:
        logger.error(f'Failed to get token from backend: {e}')
    return None

async def bot_loop(client):
    """主循环，定期检查并重连"""
    while True:
        try:
            token = await get_token_from_backend()
            if token:
                if not client.is_ready():
                    logger.info('Starting Discord bot with token from database...')
                    await client.start(token, reconnect=True)
                elif client.current_token != token:
                    logger.info('Token changed, reconnecting...')
                    await client.close()
                    await asyncio.sleep(2)
                    client.current_token = token
                    await client.start(token, reconnect=True)
            else:
                logger.warning('No active token found in database, waiting...')
                if client.is_ready():
                    await client.close()
                client.current_token = None

        except Exception as e:
            logger.error(f'Bot loop error: {e}')
            if client.is_ready():
                await client.close()

        # 等待 30 秒后再次检查
        await asyncio.sleep(30)

async def main():
    client = DiscordBotClient()

    # 启动主循环
    await bot_loop(client)

if __name__ == '__main__':
    asyncio.run(main())
