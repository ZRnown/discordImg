import discord
import aiohttp
import logging
import time
import asyncio
import random
import os
import json
import io
import sqlite3
from datetime import datetime
try:
    from config import config
except ImportError:
    from .config import config

# 全局变量用于多账号机器人管理
bot_clients = []
bot_tasks = []

# 全局冷却管理器：(account_id, channel_id) -> timestamp (上次发送时间)
account_last_sent = {}

def is_account_on_cooldown(account_id, channel_id, interval):
    """检查账号在指定频道是否在冷却中"""
    key = (account_id, str(channel_id))  # 确保channel_id是字符串
    last = account_last_sent.get(key, 0)
    logger.debug(f"检查冷却 - 账号:{account_id}, 频道:{channel_id} -> 键:{key}, 上次发送:{last}, 冷却字典大小:{len(account_last_sent)}")
    is_cooldown = (time.time() - last) < interval
    if is_cooldown:
        logger.debug(f"账号 {account_id} 在频道 {channel_id} 冷却中，还需等待 {interval - (time.time() - last):.1f} 秒")
    return is_cooldown

def set_account_cooldown(account_id, channel_id):
    """设置账号在指定频道的冷却时间"""
    key = (account_id, str(channel_id))  # 确保channel_id是字符串
    account_last_sent[key] = time.time()
    logger.debug(f"设置冷却 - 账号:{account_id}, 频道:{channel_id} -> {key}")

def cleanup_expired_cooldowns():
    """清理过期的冷却状态"""
    current_time = time.time()
    expired_keys = []
    for key, last_sent in account_last_sent.items():
        # 如果冷却时间超过24小时，清理掉（防止内存泄漏）
        if current_time - last_sent > 86400:  # 24小时
            expired_keys.append(key)

    for key in expired_keys:
        del account_last_sent[key]
        logger.debug(f"清理过期冷却: {key}")

    if expired_keys:
        logger.info(f"清理了 {len(expired_keys)} 个过期的冷却状态")

def mark_message_as_processed(message_id):
    """检查消息是否已处理（原子操作）"""
    try:
        from database import db
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO processed_messages (message_id) VALUES (?)", (str(message_id),))
            conn.commit()
        return True  # 抢锁成功
    except sqlite3.IntegrityError:
        return False  # 已经被其他Bot抢锁

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
    def __init__(self, account_id=None, user_id=None, user_shops=None, role='both'):
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
        self.user_id = user_id  # 用户ID，用于获取个性化设置
        self.user_shops = user_shops  # 用户管理的店铺列表
        self.role = role  # 'listener', 'sender', 'both' - 账号角色

    async def schedule_reply(self, message, product, custom_reply=None):
        """调度回复到合适的发送账号 (增强版：带在线检查和兜底机制)"""
        try:
            # 清理过期的冷却状态
            cleanup_expired_cooldowns()
            try:
                from database import db
            except ImportError:
                from .database import db

            # 获取用户设置以确定延迟时间
            user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
            min_delay = user_settings.get('global_reply_min_delay', 3.0)
            max_delay = user_settings.get('global_reply_max_delay', 8.0)

            # 生成回复内容
            response_content = self._generate_reply_content(product, message.channel.id, custom_reply)

            # 1. 尝试获取网站配置
            website_config = await self.get_website_config_by_channel_async(message.channel.id)

            target_client = None

            if website_config:
                # 2. 获取数据库配置的发送者 ID
                db_sender_ids = await asyncio.get_event_loop().run_in_executor(None, db.get_website_senders, website_config['id'])

                # === 关键修复：获取当前真正"活着"的机器人 ID ===
                # bot_clients 是全局变量，存着当前内存里的机器人实例
                online_client_ids = [c.account_id for c in bot_clients if c.is_ready() and not c.is_closed()]

                # 取交集：既在数据库配置了，又是当前在线的
                valid_senders = [uid for uid in db_sender_ids if uid in online_client_ids]

                # 3. 轮换/冷却逻辑
                rotation_enabled = website_config.get('rotation_enabled', 1)
                rotation_interval = website_config.get('rotation_interval', 180)

                # 调试信息：检查轮换配置
                logger.info(f"账号轮换配置 - 启用:{rotation_enabled}, 间隔:{rotation_interval}秒, 频道:{message.channel.id}")
                logger.info(f"可用发送账号: {len(available_senders) if 'available_senders' in locals() else 0} 个")

                available_senders = []
                if rotation_enabled:
                    # 筛选非冷却的（按频道区分冷却）
                    available_senders = [uid for uid in valid_senders if not is_account_on_cooldown(uid, message.channel.id, rotation_interval)]
                    # 如果都在冷却，不发送消息（根据用户要求）
                    if not available_senders:
                        logger.info(f"所有账号在频道{message.channel.id}的{rotation_interval}秒冷却期内，跳过发送")
                        return  # 不发送消息，直接返回
                else:
                    available_senders = valid_senders

                # 4. 选中一个 ID
                if available_senders:
                    selected_id = random.choice(available_senders)
                    # 从全局列表中找到这个实例
                    target_client = next((c for c in bot_clients if c.account_id == selected_id), None)

            # === 兜底逻辑 (最重要的一步) ===
            # 如果上面一顿操作猛如虎，最后没找到人（比如配置错误、没在线、列表为空）
            # 或者当前账号本身就是"Both"角色，且上面随机没随到自己，但为了稳妥
            if not target_client:
                logger.warning(f"调度失败或未配置，启用兜底机制：使用当前接收账号回复")
                target_client = self  # <--- 强制使用自己，保证消息一定能发出去

            # 5. 执行发送
            if target_client:
                # 记录冷却（按频道区分）
                if hasattr(target_client, 'account_id') and target_client.account_id:
                    set_account_cooldown(target_client.account_id, message.channel.id)

                try:
                    # 只有当 target_client 和 message 在同一个服务器时，get_channel 才有效
                    # 如果是用别的号回复，那个号也必须在这个服务器里
                    target_channel = target_client.get_channel(message.channel.id)

                    if target_channel:
                        async with target_channel.typing():
                            await asyncio.sleep(random.uniform(min_delay, max_delay))

                        # 总是尝试回复原消息，而不是直接发送
                        try:
                            await message.reply(response_content)
                            logger.info(f"✅ [回复成功] 账号: {target_client.user.name} | 商品ID: {product.get('id')}")
                        except Exception as reply_error:
                            logger.warning(f"回复消息失败，改用直接发送: {reply_error}")
                            await target_channel.send(response_content)
                            logger.info(f"✅ [发送成功] 账号: {target_client.user.name} | 商品ID: {product.get('id')}")
                    else:
                        # 这种情况是：选中的机器人不在这个频道/服务器里
                        logger.warning(f"❌ 选中的账号 {target_client.user.name} 无法访问频道，回退到直接回复")
                        await message.reply(response_content)

                except Exception as e:
                    logger.error(f"❌ 发送异常，尝试最后一次回退: {e}")
                    # 最后的最后，直接用 message 对象回复
                    await message.reply(response_content)
            else:
                # 理论上不会走到这里，因为有 target_client = self
                await message.reply(response_content)

        except Exception as e:
            logger.error(f"❌ 严重错误: {e}")
            # 无论发生什么错误，保证回复
            try:
                response_content = self._generate_reply_content(product, message.channel.id, custom_reply)
                await message.reply(response_content)
            except:
                pass

    def _generate_reply_content(self, product, channel_id, custom_reply=None):
        """生成回复内容"""
        if custom_reply:
            reply_type = custom_reply.get('reply_type')

            if reply_type == 'custom_only':
                # 只发送自定义内容，不发送链接
                return custom_reply.get('content', '')

            elif reply_type == 'text_and_link':
                # 发送文字 + 链接
                response = get_response_url_for_channel(product, channel_id)
                return f"{custom_reply.get('content', '')}\n{response}".strip()

            elif reply_type == 'text':
                # 只发送文字
                return custom_reply.get('content', '')

        # 默认行为：发送链接
        return get_response_url_for_channel(product, channel_id)

    def get_website_config_by_channel(self, channel_id):
        """根据频道ID获取对应的网站配置"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            # 查询频道绑定的网站配置
            configs = db.get_website_configs()
            for config in configs:
                channels = config.get('channels', [])
                if str(channel_id) in channels:
                    return config
            return None
        except Exception as e:
            logger.error(f"获取频道网站配置失败: {e}")
            return None

    async def get_website_config_by_channel_async(self, channel_id):
        """异步版本：根据频道ID获取对应的网站配置"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            # 异步查询频道绑定的网站配置
            configs = await asyncio.get_event_loop().run_in_executor(None, db.get_website_configs)
            for config in configs:
                channels = config.get('channels', [])
                if str(channel_id) in channels:
                    return config
            return None
        except Exception as e:
            logger.error(f"异步获取频道网站配置失败: {e}")
            return None

    def _should_filter_message(self, message):
        """检查消息是否应该被过滤"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            # 1. 检查全局消息过滤规则
            filters = db.get_message_filters()
            message_content = message.content.lower()

            for filter_rule in filters:
                filter_value = filter_rule['filter_value'].lower()
                filter_type = filter_rule['filter_type']

                if filter_type == 'contains':
                    if filter_value in message_content:
                        logger.info(f'消息被过滤: 包含 "{filter_value}"')
                        return True
                elif filter_type == 'starts_with':
                    if message_content.startswith(filter_value):
                        logger.info(f'消息被过滤: 以 "{filter_value}" 开头')
                        return True
                elif filter_type == 'ends_with':
                    if message_content.endswith(filter_value):
                        logger.info(f'消息被过滤: 以 "{filter_value}" 结尾')
                        return True
                elif filter_type == 'regex':
                    import re
                    try:
                        if re.search(filter_value, message_content, re.IGNORECASE):
                            logger.info(f'消息被过滤: 匹配正则 "{filter_value}"')
                            return True
                    except re.error:
                        logger.warning(f'无效的正则表达式: {filter_value}')
                elif filter_type == 'user_id':
                    # 检查用户ID过滤
                    filter_user_ids = [uid.strip() for uid in filter_value.split(',') if uid.strip()]
                    sender_id = str(message.author.id)
                    sender_name = str(message.author.name).lower()

                    for blocked_id in filter_user_ids:
                        blocked_id = blocked_id.strip()
                        if blocked_id == sender_id or blocked_id.lower() in sender_name:
                            logger.info(f'消息被过滤: 用户 {message.author.name} (ID: {sender_id}) 在过滤列表中')
                            return True

            # 2. 检查用户个性化设置的过滤规则
            if self.user_id:
                user_settings = db.get_user_settings(self.user_id)
                if user_settings:
                    # 检查用户黑名单
                    user_blacklist = user_settings.get('user_blacklist', '')
                    if user_blacklist:
                        blacklist_users = [u.strip().lower() for u in user_blacklist.split(',') if u.strip()]
                        sender_name = str(message.author.name).lower()
                        sender_id = str(message.author.id).lower()

                        for blocked_user in blacklist_users:
                            blocked_user = blocked_user.lower()
                            if blocked_user in sender_name or blocked_user == sender_id:
                                logger.info(f'消息被过滤: 用户 {message.author.name} 在黑名单中')
                                return True

                    # 检查关键词过滤
                    keyword_filters = user_settings.get('keyword_filters', '')
                    if keyword_filters:
                        filter_keywords = [k.strip().lower() for k in keyword_filters.split(',') if k.strip()]

                        for keyword in filter_keywords:
                            if keyword in message_content:
                                logger.info(f'消息被过滤: 包含关键词 "{keyword}"')
                                return True

        except Exception as e:
            logger.error(f'检查消息过滤失败: {e}')

        return False

    def _get_custom_reply(self):
        """获取自定义回复内容"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            replies = db.get_custom_replies()

            if replies:
                # 返回优先级最高的活跃回复
                return replies[0]
        except Exception as e:
            logger.error(f'获取自定义回复失败: {e}')

        return None

    async def on_ready(self):
        logger.info(f'Discord机器人已登录: {self.user} (ID: {self.user.id})')
        logger.info(f'机器人已就绪，开始监听消息')
        logger.info(f'监听频道: {config.DISCORD_CHANNEL_ID or "所有频道"}')
        self.running = True

        # 更新数据库中的账号状态为在线
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            if hasattr(self, 'account_id'):
                db.update_account_status(self.account_id, 'online')
                logger.info(f'账号 {self.account_id} 状态已更新为在线')
        except Exception as e:
            logger.error(f'更新账号状态失败: {e}')

    async def on_message(self, message):
        if not self.running:
            return

        # 忽略自己的消息
        if message.author == self.user:
            return

        # 忽略机器人和webhook的消息
        if message.author.bot or message.webhook_id:
            return

        # --- 新增过滤需求 ---

        # 1. 忽略 @别人的信息 (Message Mentions)
        # 如果消息中包含 mention，且 mention 的不是自己，则忽略
        if message.mentions:
            # 如果仅仅是不想回复 @别人的消息（不管是不是@自己），直接 return
            return

        # 2. 忽略回复别人的信息 (Message Reference)
        if message.reference is not None:
            return

        # 3. 触发消息过滤规则
        if self._should_filter_message(message):
            return

        # 4. 角色过滤：纯 sender 账号不处理消息
        if self.role == 'sender':
            return  # 纯发送账号不监听消息

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

            # 调用 DINOv2 服务识别图片，根据用户权限过滤结果
            result = await self.recognize_image(image_data, self.user_shops)

            logger.info(f'图片识别结果: success={result.get("success") if result else False}, results_count={len(result.get("results", [])) if result else 0}')

            if result and result.get('success') and result.get('results'):
                # 获取最佳匹配结果
                best_match = result['results'][0]
                similarity = best_match.get('similarity', 0)

                # 获取用户个性化相似度阈值，如果没有则使用全局默认值
                user_threshold = config.DISCORD_SIMILARITY_THRESHOLD  # 默认值
                if self.user_id:
                    try:
                        try:
                            from database import db
                        except ImportError:
                            from .database import db
                        # 异步获取用户设置
                        user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
                        if user_settings and 'discord_similarity_threshold' in user_settings:
                            user_threshold = user_settings['discord_similarity_threshold']
                    except Exception as e:
                        logger.error(f'获取用户相似度设置失败: {e}')

                logger.info(f'最佳匹配相似度: {similarity:.4f}, 用户阈值: {user_threshold:.4f}')

                # 检查相似度是否超过用户设置的阈值，或者是否为高质量匹配（相似度>0.8）
                if similarity >= user_threshold or similarity > 0.8:
                    product = best_match.get('product', {})
                    logger.info(f'✅ 匹配成功! 相似度: {similarity:.2f} | 商品: {product.get("id")} | 频道: {message.channel.name}')

                    # 检查商品是否启用了自动回复规则
                    product_rule_enabled = product.get('ruleEnabled', True)

                    if product_rule_enabled:
                        # 使用全局自定义回复
                        custom_reply = self._get_custom_reply()

                        # 使用调度机制回复，而不是直接回复
                        await self.schedule_reply(message, product, custom_reply)
                    else:
                        # 商品级自定义回复
                        custom_text = product.get('custom_reply_text', '').strip()
                        custom_image_indexes = product.get('selectedImageIndexes', [])
                        custom_image_urls = product.get('customImageUrls', [])

                        # 发送自定义文本消息
                        if custom_text:
                            await message.reply(custom_text)

                        # 发送图片（按优先级：本地上传 > 自定义链接 > 商品图片）
                        images_sent = False

                        # 优先检查图片来源类型
                        image_source = product.get('image_source', 'product')

                        if image_source == 'upload':
                            # 发送本地上传的图片
                            try:
                                from database import db
                                # 获取该商品的所有图片（包括上传的）
                                product_images = db.get_product_images(product['id'])
                                if product_images:
                                    for img_data in product_images[:10]:  # 最多发送10张图片
                                        try:
                                            image_path = img_data.get('image_path')
                                            # 如果是相对路径，构建完整路径
                                            if image_path and not os.path.isabs(image_path):
                                                image_path = os.path.join(os.path.dirname(__file__), image_path)
                                            if image_path and os.path.exists(image_path):
                                                await message.reply(file=discord.File(image_path, os.path.basename(image_path)))
                                                images_sent = True
                                        except Exception as e:
                                            logger.error(f'发送本地上传图片失败: {e}')
                            except Exception as e:
                                logger.error(f'处理本地上传图片回复失败: {e}')

                        elif image_source == 'custom' and custom_image_urls and len(custom_image_urls) > 0:
                            # 发送自定义图片链接
                            try:
                                # aiohttp already imported at module level
                                for url in custom_image_urls[:10]:  # 最多发送10张图片
                                    try:
                                        async with aiohttp.ClientSession() as session:
                                            async with session.get(url.strip()) as resp:
                                                if resp.status == 200:
                                                    image_data = await resp.read()
                                                    # 从URL提取文件名
                                                    filename = url.split('/')[-1].split('?')[0] or f"image_{custom_image_urls.index(url)}.jpg"
                                                    if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                                                        filename += '.jpg'
                                                    await message.reply(file=discord.File(io.BytesIO(image_data), filename))
                                                    images_sent = True
                                    except Exception as e:
                                        logger.error(f'发送自定义图片失败 {url}: {e}')
                            except Exception as e:
                                logger.error(f'处理自定义图片回复失败: {e}')

                        elif custom_image_indexes and len(custom_image_indexes) > 0:
                            # 发送选中的商品图片
                            try:
                                import aiofiles
                                import os
                                from database import db

                                for image_index in custom_image_indexes:
                                    try:
                                        # 获取图片路径
                                        image_path = db.get_product_image_path(product['id'], image_index)
                                        if image_path and os.path.exists(image_path):
                                            # 发送图片文件
                                            await message.reply(file=discord.File(image_path, f"image_{image_index}.jpg"))
                                            images_sent = True
                                    except Exception as e:
                                        logger.error(f'发送商品图片失败: {e}')
                            except Exception as e:
                                logger.error(f'处理商品图片回复失败: {e}')

                        # 如果既没有文本也没有图片，则发送默认链接
                        if not custom_text and not images_sent:
                            response = get_response_url_for_channel(product, message.channel.id)
                            await message.reply(response)

                    logger.info(f'图片识别成功，相似度: {similarity:.4f}')
                else:
                    # 相似度低于阈值，不回复任何消息
                    logger.info(f'图片识别相似度 {similarity:.4f} 低于用户阈值 {user_threshold:.4f}，不回复')

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

    async def recognize_image(self, image_data, user_shops=None):
        try:
            # 设置较短的超时时间，避免阻塞Discord网关
            timeout = aiohttp.ClientTimeout(total=15)  # 15秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 准备图片数据
                form_data = aiohttp.FormData()
                form_data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
                # 使用配置的阈值
                # 使用用户个性化阈值，如果没有则使用全局默认值
                api_threshold = config.DISCORD_SIMILARITY_THRESHOLD
                if self.user_id:
                    try:
                        try:
                            from database import db
                        except ImportError:
                            from .database import db
                        # 异步获取用户设置
                        user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
                        if user_settings and 'discord_similarity_threshold' in user_settings:
                            api_threshold = user_settings['discord_similarity_threshold']
                    except Exception as e:
                        logger.error(f'获取用户相似度设置失败: {e}')

                form_data.add_field('threshold', str(api_threshold))
                form_data.add_field('limit', '1')  # Discord只返回最相似的一个结果

                # 如果指定了用户店铺权限，添加到请求中
                if user_shops:
                    form_data.add_field('user_shops', json.dumps(user_shops))

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
            async with session.get('http://127.0.0.1:5001/api/accounts') as resp:
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
