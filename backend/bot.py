import discord
import aiohttp
import logging
import time
import asyncio
import random
import os
import json
from datetime import datetime
from config import config

# 全局变量用于多账号机器人管理
bot_clients = []
bot_tasks = []

def get_response_url_for_channel(product, channel_id):
    """根据频道ID决定发送哪个链接"""
    channel_id_str = str(channel_id)

    # 如果是CNFans频道，优先发送CNFans链接
    if config.CNFANS_CHANNEL_ID and channel_id_str == config.CNFANS_CHANNEL_ID:
        if product.get('cnfansUrl'):
            return product['cnfansUrl']
        elif product.get('acbuyUrl'):
            return product['acbuyUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

    # 如果是AcBuy频道，优先发送AcBuy链接
    elif config.ACBUY_CHANNEL_ID and channel_id_str == config.ACBUY_CHANNEL_ID:
        if product.get('acbuyUrl'):
            return product['acbuyUrl']
        elif product.get('cnfansUrl'):
            return product['cnfansUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

    # 其他频道默认发送CNFans链接，如果没有则发送微店链接
    else:
        if product.get('cnfansUrl'):
            return product['cnfansUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

class HTTPLogHandler(logging.Handler):
    """通过HTTP发送日志到Flask应用"""
    def __init__(self):
        super().__init__()
        self.pending_logs = []
        self.is_sending = False

    def emit(self, record):
        try:
            # 只发送我们关心的日志级别
            if record.levelno >= logging.INFO:
                log_data = {
                    'timestamp': datetime.now().isoformat(),
                    'level': record.levelname,
                    'message': self.format(record),
                    'module': record.module,
                    'func': record.funcName
                }

                # 添加到待发送队列
                self.pending_logs.append(log_data)

                # 如果没有正在发送，启动发送任务
                if not self.is_sending:
                    # 在机器人的事件循环中创建任务
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(self.send_pending_logs())
                        else:
                            # 如果循环没有运行，直接发送（同步方式）
                            self.send_sync(log_data)
                    except RuntimeError:
                        # 没有事件循环，直接同步发送
                        self.send_sync(log_data)

        except Exception as e:
            print(f"HTTP日志处理器错误: {e}")

    def send_sync(self, log_data):
        """同步发送日志（作为fallback）"""
        try:
            import requests
            response = requests.post('http://localhost:5001/api/logs/add',
                                   json=log_data, timeout=2)
            if response.status_code != 200:
                print(f"同步发送日志失败: {response.status_code}")
        except Exception as e:
            print(f"同步发送日志异常: {e}")

    async def send_pending_logs(self):
        """异步发送待处理的日志"""
        if self.is_sending:
            return

        self.is_sending = True

        try:
            while self.pending_logs:
                log_data = self.pending_logs.pop(0)

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post('http://localhost:5001/api/logs/add',
                                              json=log_data, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                            if resp.status != 200:
                                print(f"发送日志失败: {resp.status}")
                except Exception as e:
                    print(f"发送日志异常: {e}")
                    # 重新放回队列
                    self.pending_logs.insert(0, log_data)
                    break

                # 小延迟避免发送太快
                await asyncio.sleep(0.1)

        finally:
            self.is_sending = False

# 配置日志
logging.basicConfig(level=logging.INFO)

# 添加HTTP日志处理器
http_handler = HTTPLogHandler()
http_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(http_handler)

logger = logging.getLogger(__name__)

# 确保discord库也使用我们的日志配置
logging.getLogger('discord').setLevel(logging.INFO)

class DiscordBotClient(discord.Client):
    def __init__(self, account_id=None):
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
        self.account_id = account_id

    async def on_ready(self):
        logger.info(f'Discord机器人已登录: {self.user} (ID: {self.user.id})')
        logger.info(f'机器人已就绪，开始监听消息')
        logger.info(f'监听频道: {config.DISCORD_CHANNEL_ID or "所有频道"}')
        self.running = True

    async def on_message(self, message):
        if not self.running:
            return

        # 忽略自己的消息
        if message.author == self.user:
            return

        # 忽略机器人和webhook的消息
        if message.author.bot or message.webhook_id:
            return

        # 如果配置了频道ID，只处理特定频道的消息；否则处理所有频道
        if config.DISCORD_CHANNEL_ID and str(message.channel.id) != str(config.DISCORD_CHANNEL_ID):
            return

        logger.info(f'收到消息: {message.author.name} 在 #{message.channel.name}: "{message.content[:100]}{"..." if len(message.content) > 100 else ""}"')

        # 处理关键词消息转发
        await self.handle_keyword_forward(message)

        # 处理关键词搜索（文字消息）
        await self.handle_keyword_search(message)

        # 检查消息是否包含图片（只处理图片，不处理文字）
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    await self.handle_image(message, attachment)
                    # 如果消息包含图片，不再处理文字内容，避免重复回复

    async def handle_image(self, message, attachment):
        try:
            # 下载图片，设置较短的超时时间和重试机制
            timeout = aiohttp.ClientTimeout(total=10, connect=5)  # 10秒总超时，5秒连接超时
            image_data = None

            # 重试最多3次
            for attempt in range(3):
                try:
                    logger.info(f"下载Discord图片 (尝试 {attempt + 1}/3): {attachment.filename}")
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(attachment.url) as resp:
                            if resp.status == 200:
                                image_data = await resp.read()
                                logger.info(f"图片下载成功，大小: {len(image_data)} bytes")
                                break
                            else:
                                logger.warning(f"图片下载失败，状态码: {resp.status}")
                except aiohttp.ClientError as e:
                    logger.warning(f"图片下载失败 (尝试 {attempt + 1}/3): {e}")
                    if attempt < 2:  # 不是最后一次尝试
                        await asyncio.sleep(1)  # 等待1秒后重试
                except Exception as e:
                    logger.error(f"图片下载未知错误 (尝试 {attempt + 1}/3): {e}")
                    break

            if image_data is None:
                logger.error("图片下载失败，已达到最大重试次数")
                return  # 静默失败，不发送错误消息

            # 调用 DINOv2 服务识别图片
            result = await self.recognize_image(image_data)

            if result and result.get('success') and result.get('results'):
                # 获取最佳匹配结果
                best_match = result['results'][0]
                similarity = best_match.get('similarity', 0)

                # 检查相似度是否超过阈值
                if similarity >= config.DISCORD_SIMILARITY_THRESHOLD:
                    product = best_match.get('product', {})
                    # 根据频道决定发送哪个链接
                    response = get_response_url_for_channel(product, message.channel.id)

                    # 模拟打字状态并延迟回复
                    async with message.channel.typing():
                        # 检查是否设置了全局延迟（只要有一个值不为默认值3.0，就认为已设置）
                        if abs(config.GLOBAL_REPLY_MIN_DELAY - 3.0) > 0.01 or abs(config.GLOBAL_REPLY_MAX_DELAY - 8.0) > 0.01:
                            delay = random.uniform(config.GLOBAL_REPLY_MIN_DELAY, config.GLOBAL_REPLY_MAX_DELAY)
                            logger.info(f"模拟打字并延迟回复 {delay:.2f} 秒...")
                            await asyncio.sleep(delay)
                        else:
                            # 如果没有设置延迟，至少模拟1-3秒的打字时间
                            delay = random.uniform(1.0, 3.0)
                            logger.info(f"模拟打字 {delay:.2f} 秒...")
                            await asyncio.sleep(delay)

                    await message.reply(response)
                    logger.info(f'图片识别成功，相似度: {similarity:.4f}')
                else:
                    # 相似度低于阈值，不回复任何消息
                    logger.info(f'图片识别相似度 {similarity:.4f} 低于阈值 {config.DISCORD_SIMILARITY_THRESHOLD}，不回复')

        except Exception as e:
            logger.error(f'Error handling image: {e}')
            # 不发送错误消息到Discord，只记录日志

    async def handle_keyword_forward(self, message):
        """处理关键词消息转发"""
        try:
            # 检查消息内容是否包含关键词
            message_content = message.content.lower() if message.content else ""
            has_keyword = any(keyword.strip().lower() in message_content for keyword in config.FORWARD_KEYWORDS)

            if has_keyword and config.FORWARD_TARGET_CHANNEL_ID:
                # 获取目标频道
                target_channel = self.get_channel(config.FORWARD_TARGET_CHANNEL_ID)
                if target_channel:
                    # 构建转发消息
                    forward_embed = discord.Embed(
                        title="📢 商品相关消息转发",
                        description=f"**原始消息:** {message.content[:500]}{'...' if len(message.content) > 500 else ''}",
                        color=0x00ff00,
                        timestamp=message.created_at
                    )

                    forward_embed.add_field(
                        name="发送者",
                        value=f"{message.author.name}#{message.author.discriminator}",
                        inline=True
                    )

                    forward_embed.add_field(
                        name="来源频道",
                        value=f"#{message.channel.name}",
                        inline=True
                    )

                    forward_embed.add_field(
                        name="服务器",
                        value=message.guild.name if message.guild else "DM",
                        inline=True
                    )

                    # 如果有附件，添加到embed中
                    if message.attachments:
                        attachment_urls = [att.url for att in message.attachments]
                        forward_embed.add_field(
                            name="附件",
                            value="\n".join(attachment_urls),
                            inline=False
                        )

                    forward_embed.set_footer(text=f"消息ID: {message.id}")

                    await target_channel.send(embed=forward_embed)
                    logger.info(f"转发了包含关键词的消息: {message.content[:100]}...")
                else:
                    logger.warning(f"找不到目标频道: {config.FORWARD_TARGET_CHANNEL_ID}")

        except Exception as e:
            logger.error(f'Error handling keyword forward: {e}')

    async def handle_keyword_search(self, message):
        """处理关键词商品搜索"""
        try:
            # 只处理纯文字消息（不包含图片的）
            if not message.content or message.attachments:
                return

            search_query = message.content.strip()
            if not search_query:
                return

            # 调用搜索API
            result = await self.search_products_by_keyword(search_query)

            products = []
            if result and result.get('success') and result.get('products'):
                products = result['products'][:5]  # 最多显示5个结果

            # 只在找到商品时回复和记录日志
            if products:
                logger.info(f'关键词搜索成功: "{search_query}" -> 找到 {len(products)} 个商品')
                # 根据频道决定发送哪个链接
                product = products[0]
                response = get_response_url_for_channel(product, message.channel.id)

                logger.info(f'关键词搜索完成，找到 {len(products)} 个商品')

                # 模拟打字状态并延迟回复
                async with message.channel.typing():
                    # 检查是否设置了全局延迟（只要有一个值不为默认值3.0，就认为已设置）
                    if abs(config.GLOBAL_REPLY_MIN_DELAY - 3.0) > 0.01 or abs(config.GLOBAL_REPLY_MAX_DELAY - 8.0) > 0.01:
                        delay = random.uniform(config.GLOBAL_REPLY_MIN_DELAY, config.GLOBAL_REPLY_MAX_DELAY)
                        logger.info(f"模拟打字并延迟回复 {delay:.2f} 秒...")
                        await asyncio.sleep(delay)
                    else:
                        # 如果没有设置延迟，至少模拟1-3秒的打字时间
                        delay = random.uniform(1.0, 3.0)
                        logger.info(f"模拟打字 {delay:.2f} 秒...")
                        await asyncio.sleep(delay)

                await message.reply(response)
            else:
                # 没有找到商品，不回复任何消息
                logger.info(f'关键词搜索无结果: {search_query}')

        except Exception as e:
            logger.error(f'Error handling keyword search: {e}')
            # 不发送错误消息到Discord，只记录日志

    async def search_products_by_keyword(self, keyword):
        """根据关键词搜索商品"""
        try:
            # 设置超时时间
            timeout = aiohttp.ClientTimeout(total=10)  # 10秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 构建搜索请求
                search_data = {
                    'query': keyword,
                    'limit': 10  # 搜索更多结果，但只显示前5个
                }

                # 调用后端搜索API
                async with session.post('http://localhost:5001/api/search_similar_text',
                                      json=search_data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result
                    else:
                        logger.error(f'Keyword search API error: {resp.status}')
                        return None

        except Exception as e:
            logger.error(f'Error searching products by keyword: {e}')
            return None

    async def recognize_image(self, image_data):
        try:
            # 设置较短的超时时间，避免阻塞Discord网关
            timeout = aiohttp.ClientTimeout(total=15)  # 15秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 准备图片数据
                form_data = aiohttp.FormData()
                form_data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
                form_data.add_field('threshold', str(config.DISCORD_SIMILARITY_THRESHOLD))
                form_data.add_field('limit', '1')  # Discord只返回最相似的一个结果

                # 调用 DINOv2 + FAISS 服务（本地）
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

async def get_all_accounts_from_backend():
    """从后端 API 获取所有可用的 Discord 账号"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:5001/api/accounts') as resp:
                if resp.status == 200:
                    result = await resp.json()
                    accounts = result.get('accounts', [])
                    if accounts:
                        logger.info(f'Got {len(accounts)} accounts from backend')
                        return accounts
    except Exception as e:
        logger.error(f'Failed to get accounts from backend: {e}')
    return []

async def get_all_accounts_from_backend():
    """从后端 API 获取所有可用的 Discord 账号"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:5001/api/accounts') as resp:
                if resp.status == 200:
                    result = await resp.json()
                    accounts = result.get('accounts', [])
                    # 只返回状态为online的账号
                    return [account for account in accounts if account.get('status') == 'online']
    except Exception as e:
        logger.error(f'Failed to get accounts from backend: {e}')
    return []

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

async def start_multi_bot_loop():
    """启动多账号机器人循环，定期检查账号状态"""
    global bot_clients, bot_tasks

    while True:
        try:
            # 获取当前所有账号
            accounts = await get_all_accounts_from_backend()
            current_account_ids = {account['id'] for account in accounts}

            # 停止已删除账号的机器人
            to_remove = []
            for i, client in enumerate(bot_clients):
                if client.account_id not in current_account_ids:
                    logger.info(f'停止已删除账号的机器人: {client.account_id}')
                    try:
                        if not client.is_closed():
                            await client.close()
                    except Exception as e:
                        logger.error(f'停止机器人时出错: {e}')

                    # 取消对应的任务
                    if i < len(bot_tasks) and bot_tasks[i] and not bot_tasks[i].done():
                        bot_tasks[i].cancel()

                    to_remove.append(i)

            # 从列表中移除已停止的机器人
            for i in reversed(to_remove):
                bot_clients.pop(i)
                if i < len(bot_tasks):
                    bot_tasks.pop(i)

            # 为新账号启动机器人
            existing_account_ids = {client.account_id for client in bot_clients}
            for account in accounts:
                account_id = account['id']
                if account_id not in existing_account_ids:
                    token = account['token']
                    username = account.get('username', f'account_{account_id}')

                    logger.info(f'启动新账号机器人: {username}')

                    # 创建机器人实例
                    client = DiscordBotClient(account_id=account_id)

                    # 启动机器人
                    try:
                        task = asyncio.create_task(client.start(token, reconnect=True))
                        bot_clients.append(client)
                        bot_tasks.append(task)
                        logger.info(f'机器人启动成功: {username}')
                    except Exception as e:
                        logger.error(f'启动机器人失败 {username}: {e}')

            # 等待一段时间后再次检查
            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f'多账号机器人循环错误: {e}')
            await asyncio.sleep(30)

async def main():
    client = DiscordBotClient()

    # 启动主循环
    await bot_loop(client)

if __name__ == '__main__':
    asyncio.run(main())
