import sqlite3
import numpy as np
import os
import logging
import json
from time import perf_counter
from typing import List, Dict, Any, Optional, Sequence, Tuple
from contextlib import contextmanager
try:
    from config import config
except ImportError:
    from .config import config
try:
    from settings_validation import normalize_reply_delay_range
except ImportError:
    from .settings_validation import normalize_reply_delay_range
try:
    from product_reply_settings import build_frontend_per_website_reply_settings
except ImportError:
    from .product_reply_settings import build_frontend_per_website_reply_settings
try:
    from product_title_translations import (
        get_effective_reply_languages,
        normalize_title_translations,
    )
except ImportError:
    from .product_title_translations import (
        get_effective_reply_languages,
        normalize_title_translations,
    )

logger = logging.getLogger(__name__)

MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH = 200000
MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH = 20000
MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH = 20000
USABLE_RETRIEVAL_CACHE_INDEX_NAME = 'idx_retrieval_cache_usable_image_strategy'

class Database:
    def __init__(self, db_path: Optional[str] = None):
        # SQLite 数据库路径 (用于存储商品元数据和Discord账号信息)
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), 'data', 'metadata.db')

        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化 SQLite 数据库
        self.init_sqlite_database()

    @staticmethod
    def _get_table_columns(cursor, table_name: str) -> List[str]:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [str(row[1]) for row in cursor.fetchall()]

    @staticmethod
    def _configure_connection(conn, *, enable_wal: bool = False) -> None:
        conn.execute('PRAGMA foreign_keys=ON;')
        if enable_wal:
            conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA busy_timeout=60000;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.execute('PRAGMA cache_size=-64000;')

    def _migrate_legacy_product_images_schema(self, conn, cursor):
        columns = self._get_table_columns(cursor, 'product_images')
        legacy_columns = {'features', 'milvus_id'}
        if not columns or not legacy_columns.intersection(columns):
            return

        logger.info("迁移 product_images 旧检索字段到纯图片元数据结构")
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute('''
            CREATE TABLE product_images_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                image_index INTEGER NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
                UNIQUE(product_id, image_index)
            )
        ''')
        cursor.execute('''
            INSERT INTO product_images_new (id, product_id, image_path, image_index)
            SELECT id, product_id, image_path, image_index
            FROM product_images
        ''')
        cursor.execute('DROP TABLE product_images')
        cursor.execute('ALTER TABLE product_images_new RENAME TO product_images')
        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    def init_sqlite_database(self):
        """初始化 SQLite 数据库 (用于元数据存储)"""
        with sqlite3.connect(self.db_path) as conn:
            self._configure_connection(conn, enable_wal=True)
            cursor = conn.cursor()

            # 创建商品表（移除商品级别延迟，使用全局延迟）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    description TEXT,
                    english_title TEXT,
                    title_translations TEXT,
                    partition_match_enabled BOOLEAN DEFAULT 0,
                    partition_match_rules TEXT,
                    cnfans_url TEXT,
                    acbuy_url TEXT,
                    shop_name TEXT,
                    ruleEnabled BOOLEAN DEFAULT 1,
                    reply_scope TEXT DEFAULT 'all',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建索引以优化查询性能
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_shop_name ON products(shop_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_rule_enabled ON products(ruleEnabled)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_partition_match_enabled ON products(partition_match_enabled)')
            except sqlite3.OperationalError:
                pass

            # 创建店铺表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    product_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 为现有表添加新字段（如果不存在）
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN ruleEnabled BOOLEAN DEFAULT 1')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN min_delay INTEGER DEFAULT 3')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN max_delay INTEGER DEFAULT 8')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            # 新增英文标题与 cnfans 链接字段（兼容已有数据库）
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN english_title TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN title_translations TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN partition_match_enabled BOOLEAN DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN partition_match_rules TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN cnfans_url TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN acbuy_url TEXT')
            except sqlite3.OperationalError:
                pass

            # 添加自定义回复字段
            try:
                cursor.execute('ALTER TABLE products ADD COLUMN custom_reply_text TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN custom_reply_images TEXT')  # JSON格式存储图片索引数组
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN custom_image_urls TEXT')  # JSON格式存储自定义图片URL数组
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN image_source TEXT DEFAULT \'product\'')  # 图片来源：'product'(商品图片), 'upload'(本地上传), 'custom'(URL)
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN reply_scope TEXT DEFAULT \'all\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN shop_name TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN item_id TEXT')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN updated_at TIMESTAMP')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN uploaded_reply_images TEXT')  # JSON格式存储上传的自定义回复图片文件名数组
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE products ADD COLUMN per_website_reply_settings TEXT')  # JSON格式存储各网站独立回复设置
            except sqlite3.OperationalError:
                pass  # 字段已存在

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN cnfans_channel_id TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN acbuy_channel_id TEXT')
            except sqlite3.OperationalError:
                pass

            # 创建商品图片表，仅保存图片元数据；检索特征统一落到 product_image_retrieval_cache
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    image_index INTEGER NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
                    UNIQUE(product_id, image_index)
                )
            ''')
            self._migrate_legacy_product_images_schema(conn, cursor)
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_images_product_id ON product_images(product_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_images_image_index ON product_images(image_index)')
            except sqlite3.OperationalError:
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_image_retrieval_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_db_id INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    cache_version TEXT,
                    embedding_json TEXT,
                    color_hist_json TEXT,
                    tokens_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (image_db_id) REFERENCES product_images (id) ON DELETE CASCADE,
                    UNIQUE(image_db_id, strategy_name)
                )
            ''')
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_retrieval_cache_strategy ON product_image_retrieval_cache(strategy_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_retrieval_cache_image_db_id ON product_image_retrieval_cache(image_db_id)')
                cursor.execute(
                    f'''
                    CREATE INDEX IF NOT EXISTS {USABLE_RETRIEVAL_CACHE_INDEX_NAME}
                    ON product_image_retrieval_cache(image_db_id, strategy_name)
                    WHERE embedding_json IS NOT NULL
                      AND LENGTH(embedding_json) <= {MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH}
                    '''
                )
            except sqlite3.OperationalError:
                pass

            # 创建用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',  -- admin, user
                    is_active BOOLEAN DEFAULT 1,
                    image_search_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            try:
                cursor.execute('ALTER TABLE users ADD COLUMN image_search_count INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            # 创建用户-店铺权限表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_shop_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    shop_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    UNIQUE(user_id, shop_id)
                )
            ''')

            # 创建 Discord 账号表（关联到用户）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS discord_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    token TEXT UNIQUE NOT NULL,
                    user_id INTEGER,
                    auto_start_enabled BOOLEAN DEFAULT 0,
                    status TEXT DEFAULT 'offline',
                    last_active TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
                )
            ''')

            try:
                cursor.execute('ALTER TABLE discord_accounts ADD COLUMN auto_start_enabled BOOLEAN DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            # 插入默认管理员用户
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (id, username, password_hash, role, is_active)
                    VALUES (1, 'admin', 'hashed_admin123', 'admin', 1)
                ''')  # 密码: admin123
            except sqlite3.Error as e:
                logger.warning(f"创建默认管理员失败: {e}")

            # 创建账号轮换配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_rotation_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled BOOLEAN DEFAULT 0,
                    rotation_interval INTEGER DEFAULT 10,
                    current_account_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认轮换配置
            cursor.execute('''
                INSERT OR IGNORE INTO account_rotation_config (id, enabled, rotation_interval)
                VALUES (1, 0, 10)
            ''')

            # 创建搜索历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_image_path TEXT NOT NULL,
                    matched_product_id INTEGER,
                    matched_image_index INTEGER,
                    similarity REAL NOT NULL,
                    threshold REAL NOT NULL,
                    is_skipped INTEGER DEFAULT 0,
                    discord_message_id TEXT,
                    discord_channel_id TEXT,
                    discord_channel_name TEXT DEFAULT '',
                    discord_author_id TEXT,
                    discord_author_name TEXT DEFAULT '',
                    message_content TEXT DEFAULT '',
                    search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matched_product_id) REFERENCES products (id) ON DELETE SET NULL
                )
            ''')

            for column_name, column_definition in (
                ('is_skipped', 'INTEGER DEFAULT 0'),
                ('discord_message_id', 'TEXT'),
                ('discord_channel_id', 'TEXT'),
                ('discord_channel_name', "TEXT DEFAULT ''"),
                ('discord_author_id', 'TEXT'),
                ('discord_author_name', "TEXT DEFAULT ''"),
                ('message_content', "TEXT DEFAULT ''"),
            ):
                try:
                    cursor.execute(f'ALTER TABLE search_history ADD COLUMN {column_name} {column_definition}')
                except Exception:
                    pass

            # 【新增优化】为搜索历史创建时间索引，极大提升翻页速度
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_history_time ON search_history(search_time DESC)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_history_skipped_time ON search_history(is_skipped, search_time DESC, id DESC)')
            except Exception:
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS skipped_image_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_image_path TEXT NOT NULL,
                    matched_product_id INTEGER,
                    matched_image_index INTEGER,
                    similarity REAL NOT NULL,
                    threshold REAL NOT NULL,
                    discord_message_id TEXT,
                    discord_channel_id TEXT,
                    discord_channel_name TEXT DEFAULT '',
                    discord_author_id TEXT,
                    discord_author_name TEXT DEFAULT '',
                    message_content TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matched_product_id) REFERENCES products (id) ON DELETE SET NULL
                )
            ''')

            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_skipped_image_history_time ON skipped_image_history(created_at DESC)')
            except Exception:
                pass

            # 创建全局延迟配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_reply_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    min_delay REAL DEFAULT 1.0,
                    max_delay REAL DEFAULT 3.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建系统配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    discord_channel_id TEXT DEFAULT '',
                    download_threads INTEGER DEFAULT 4,
                    feature_extract_threads INTEGER DEFAULT 4,
                    discord_similarity_threshold REAL DEFAULT 0.6,
                    cnfans_channel_id TEXT DEFAULT '',
                    acbuy_channel_id TEXT DEFAULT '',
                    scrape_threads INTEGER DEFAULT 2,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认系统配置
            cursor.execute('''
                INSERT OR IGNORE INTO system_config (id, discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id)
                VALUES (1, '', 4, 4, 0.6, '', '')
            ''')

            # 为现有记录添加scrape_threads字段
            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN scrape_threads INTEGER DEFAULT 2')
            except sqlite3.OperationalError:
                pass  # 字段已存在

            # 创建网站配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    url_template TEXT NOT NULL,
                    id_pattern TEXT NOT NULL,
                    badge_color TEXT DEFAULT 'blue',
                    reply_template TEXT DEFAULT '{url}',
                    reply_language TEXT DEFAULT 'link_only',
                    image_similarity_threshold REAL DEFAULT NULL,
                    blocked_role_ids TEXT DEFAULT '[]',
                    rotation_interval INTEGER DEFAULT 180,
                    rotation_enabled INTEGER DEFAULT 1,  -- 是否启用轮换功能 (1=启用, 0=禁用)
                    message_filters TEXT DEFAULT '[]',  -- JSON格式存储过滤条件数组
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 网站每日回复统计表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_reply_stats_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    stat_date TEXT NOT NULL,
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(website_id, stat_date),
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE
                )
            ''')

            # 为website_configs表添加rotation_interval字段
            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN rotation_interval INTEGER DEFAULT 180')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN reply_template TEXT DEFAULT \'{url}\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN reply_language TEXT DEFAULT \'link_only\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN image_similarity_threshold REAL DEFAULT NULL')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN blocked_role_ids TEXT DEFAULT \'[]\'')
            except sqlite3.OperationalError:
                pass

            # 为website_configs表添加message_filters字段
            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN message_filters TEXT DEFAULT \'[]\'')
            except sqlite3.OperationalError:
                pass

            # 为website_configs表添加rotation_enabled字段
            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN rotation_enabled INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN stat_replies_text INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN stat_replies_image INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE website_configs ADD COLUMN stat_replies_total INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            # 1. 消息处理去重表（防止多个Bot回复同一条消息）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建自定义回复内容表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS custom_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reply_type TEXT NOT NULL, -- 'text', 'image', 'text_and_link', 'custom_only'
                    content TEXT, -- 文字内容或图片URL
                    image_url TEXT, -- 如果是图片回复
                    is_active BOOLEAN DEFAULT 1,
                    priority INTEGER DEFAULT 0, -- 优先级，数字越大优先级越高
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 2. 修改频道绑定表，增加 user_id 实现用户隔离
            try:
                cursor.execute('ALTER TABLE website_channel_bindings ADD COLUMN user_id INTEGER')
            except sqlite3.OperationalError:
                pass

            # 检测并迁移旧的唯一约束 (UNIQUE(website_id, channel_id) -> UNIQUE(website_id, channel_id, user_id))
            needs_migration = False
            table_exists = False
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='website_channel_bindings'")
                table_exists = cursor.fetchone() is not None
            except sqlite3.OperationalError:
                table_exists = False

            if table_exists:
                try:
                    cursor.execute("PRAGMA index_list(website_channel_bindings)")
                    for idx in cursor.fetchall():
                        if len(idx) > 2 and idx[2]:
                            index_name = idx[1]
                            cursor.execute(f'PRAGMA index_info("{index_name}")')
                            col_names = [row[2] for row in cursor.fetchall()]
                            if 'website_id' in col_names and 'channel_id' in col_names and 'user_id' not in col_names:
                                needs_migration = True
                                break
                except sqlite3.OperationalError:
                    pass

            if needs_migration:
                logger.info("🔄 检测到旧的频道绑定表结构，正在迁移以支持多用户绑定...")
                try:
                    cursor.execute("ALTER TABLE website_channel_bindings RENAME TO website_channel_bindings_old")
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS website_channel_bindings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            website_id INTEGER NOT NULL,
                            channel_id TEXT NOT NULL,
                            user_id INTEGER,
                            keyword_review_enabled INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                            UNIQUE(website_id, channel_id, user_id)
                        )
                    ''')
                    cursor.execute('''
                        INSERT OR IGNORE INTO website_channel_bindings (
                            id,
                            website_id,
                            channel_id,
                            user_id,
                            keyword_review_enabled,
                            created_at
                        )
                        SELECT id, website_id, channel_id, user_id, 0, created_at
                        FROM website_channel_bindings_old
                    ''')
                    cursor.execute("DROP TABLE website_channel_bindings_old")
                    logger.info("✅ 频道绑定表结构迁移完成")
                except Exception as e:
                    logger.error(f"❌ 表结构迁移失败: {e}")

            # 创建网站频道绑定表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_channel_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    channel_id TEXT NOT NULL,
                    user_id INTEGER,
                    keyword_review_enabled INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    UNIQUE(website_id, channel_id, user_id)
                )
            ''')
            try:
                cursor.execute('ALTER TABLE website_channel_bindings ADD COLUMN keyword_review_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keyword_reply_review_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    channel_id TEXT NOT NULL,
                    guild_id TEXT DEFAULT '',
                    guild_name TEXT DEFAULT '',
                    channel_name TEXT DEFAULT '',
                    account_ids_json TEXT DEFAULT '[]',
                    account_names TEXT DEFAULT '',
                    sender_id TEXT DEFAULT '',
                    sender_name TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    source_content TEXT DEFAULT '',
                    message_id TEXT DEFAULT '',
                    reply_mode TEXT DEFAULT 'keyword',
                    status TEXT DEFAULT 'pending',
                    payload_json TEXT NOT NULL,
                    reviewed_by_user_id INTEGER DEFAULT NULL,
                    error_message TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP DEFAULT NULL,
                    sent_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE
                )
            ''')
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_keyword_reply_review_items_user_status ON keyword_reply_review_items(user_id, status, created_at DESC)')
            except sqlite3.OperationalError:
                pass

            # 创建网站账号绑定表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_account_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('listener', 'sender', 'both')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES discord_accounts (id) ON DELETE CASCADE,
                    UNIQUE(website_id, account_id)
                )
            ''')

            # 创建系统公告表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_announcements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建消息过滤规则表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_type TEXT NOT NULL, -- 'contains', 'starts_with', 'ends_with', 'regex'
                    filter_value TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建消息过滤图片表（全局）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_filter_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    features TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (filter_id) REFERENCES message_filters (id) ON DELETE CASCADE
                )
            ''')

            # 创建网站过滤图片表（用户级别）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_filter_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    filter_id TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    features TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_blocked_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    discord_user_id TEXT NOT NULL,
                    discord_username TEXT DEFAULT '',
                    trigger_keyword TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    UNIQUE(user_id, website_id, discord_user_id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_filter_blocked_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_id INTEGER NOT NULL,
                    discord_user_id TEXT NOT NULL,
                    discord_username TEXT DEFAULT '',
                    trigger_keyword TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (filter_id) REFERENCES message_filters (id) ON DELETE CASCADE,
                    UNIQUE(filter_id, discord_user_id)
                )
            ''')

            # 创建用户回复统计表（累计）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_reply_stats (
                    user_id INTEGER PRIMARY KEY,
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')

            # 创建用户回复统计表（每日）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_reply_stats_daily (
                    user_id INTEGER NOT NULL,
                    stat_date DATE NOT NULL,
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, stat_date),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')

            # 创建用户-网站回复统计表（累计）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_website_reply_stats (
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, website_id),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE
                )
            ''')

            # 创建用户-网站回复统计表（每日）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_website_reply_stats_daily (
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    stat_date DATE NOT NULL,
                    stat_replies_text INTEGER DEFAULT 0,
                    stat_replies_image INTEGER DEFAULT 0,
                    stat_replies_total INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, website_id, stat_date),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE
                )
            ''')

            # 创建用户设置表（每个用户的个性化设置）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    download_threads INTEGER DEFAULT 4,
                    feature_extract_threads INTEGER DEFAULT 4,
                    discord_similarity_threshold REAL DEFAULT 0.6,
                    global_reply_min_delay REAL DEFAULT 1.0,
                    global_reply_max_delay REAL DEFAULT 3.0,
                    user_blacklist TEXT DEFAULT '',  -- 用户黑名单，逗号分隔
                    keyword_filters TEXT DEFAULT '',  -- 关键词过滤，逗号分隔
                    keyword_reply_enabled INTEGER DEFAULT 1,  -- 是否启用关键词回复
                    image_reply_enabled INTEGER DEFAULT 1,  -- 是否启用图片回复
                    keyword_match_limit INTEGER DEFAULT 0,  -- 单条消息最多允许命中的关键词数，0 表示不限制
                    global_reply_template TEXT DEFAULT '',
                    numeric_filter_keyword TEXT DEFAULT '',
                    filter_size_min INTEGER DEFAULT 35,
                    filter_size_max INTEGER DEFAULT 46,
                    bark_enabled INTEGER DEFAULT 0,  -- 是否启用 Bark 通知
                    bark_server_url TEXT DEFAULT 'https://api.day.app',  -- Bark 服务地址
                    bark_device_key TEXT DEFAULT '',  -- Bark 设备密钥
                    keyword_reply_send_best_match_image INTEGER DEFAULT 0,
                    keyword_image_search_api_key TEXT DEFAULT '',
                    keyword_image_search_cx TEXT DEFAULT '',
                    review_bark_enabled INTEGER DEFAULT 0,
                    review_bark_mode TEXT DEFAULT 'count',
                    review_bark_count_threshold INTEGER DEFAULT 5,
                    review_bark_interval_minutes INTEGER DEFAULT 60,
                    review_bark_last_notified_at TEXT DEFAULT '',
                    review_bark_last_pending_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    UNIQUE(user_id)
                )
            ''')

            # 为 user_settings 表添加新字段（如果不存在）
            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN keyword_reply_enabled INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN image_reply_enabled INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN keyword_match_limit INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN global_reply_template TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN numeric_filter_keyword TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN filter_size_min INTEGER DEFAULT 35')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN filter_size_max INTEGER DEFAULT 46')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN bark_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN bark_server_url TEXT DEFAULT \'https://api.day.app\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN bark_device_key TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN keyword_reply_send_best_match_image INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN keyword_image_search_api_key TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN keyword_image_search_cx TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_mode TEXT DEFAULT \'count\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_count_threshold INTEGER DEFAULT 5')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_interval_minutes INTEGER DEFAULT 60')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_last_notified_at TEXT DEFAULT \'\'')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE user_settings ADD COLUMN review_bark_last_pending_count INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            # 创建用户级别的网站设置表（轮换设置和消息过滤）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_website_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    rotation_interval INTEGER DEFAULT 180,
                    rotation_enabled INTEGER DEFAULT 1,
                    reply_mode TEXT DEFAULT 'rotation',
                    keyword_reply_interval INTEGER DEFAULT NULL,
                    keyword_reply_batch_size INTEGER DEFAULT 0,
                    keyword_batch_dispatch_mode TEXT DEFAULT 'immediate',
                    thread_reply_enabled INTEGER DEFAULT 0,
                    forum_post_reply_enabled INTEGER DEFAULT 0,
                    keyword_match_limit INTEGER DEFAULT NULL,
                    keyword_image_search_enabled INTEGER DEFAULT 0,
                    keyword_image_search_mode TEXT DEFAULT 'manual',
                    keyword_image_search_max_images INTEGER DEFAULT 3,
                    message_filters TEXT DEFAULT '[]',
                    image_similarity_threshold REAL DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    UNIQUE(user_id, website_id)
                )
            ''')
            reply_mode_added = False
            try:
                cursor.execute("ALTER TABLE user_website_settings ADD COLUMN reply_mode TEXT DEFAULT 'rotation'")
                reply_mode_added = True
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN keyword_reply_interval INTEGER DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN image_similarity_threshold REAL DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN reply_min_delay REAL DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN reply_max_delay REAL DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN keyword_reply_batch_size INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE user_website_settings ADD COLUMN keyword_batch_dispatch_mode TEXT DEFAULT 'immediate'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN thread_reply_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN forum_post_reply_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN keyword_match_limit INTEGER DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN keyword_image_search_enabled INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE user_website_settings ADD COLUMN keyword_image_search_mode TEXT DEFAULT 'manual'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE user_website_settings ADD COLUMN keyword_image_search_max_images INTEGER DEFAULT 3')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('''
                    UPDATE user_website_settings
                    SET keyword_reply_interval = rotation_interval
                    WHERE keyword_reply_interval IS NULL OR keyword_reply_interval <= 0
                ''')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('''
                    UPDATE user_website_settings
                    SET keyword_batch_dispatch_mode = 'immediate'
                    WHERE keyword_batch_dispatch_mode IS NULL
                       OR TRIM(keyword_batch_dispatch_mode) = ''
                       OR LOWER(keyword_batch_dispatch_mode) NOT IN ('immediate', 'window_end')
                ''')
            except sqlite3.OperationalError:
                pass
            if reply_mode_added:
                try:
                    cursor.execute('''
                        UPDATE user_website_settings
                        SET reply_mode = CASE
                            WHEN COALESCE(keyword_reply_batch_size, 0) > 0
                                 AND COALESCE(rotation_enabled, 1) = 0 THEN 'keyword'
                            ELSE 'rotation'
                        END
                    ''')
                except sqlite3.OperationalError:
                    pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keyword_image_search_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    website_id INTEGER NOT NULL,
                    query_text TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    guild_id TEXT,
                    author_id TEXT,
                    mode TEXT DEFAULT 'manual',
                    provider TEXT DEFAULT 'searchapi_google_images',
                    status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    external_result_count INTEGER DEFAULT 0,
                    matched_result_count INTEGER DEFAULT 0,
                    selected_candidate_index INTEGER,
                    sent_product_id INTEGER,
                    candidates_json TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    FOREIGN KEY (sent_product_id) REFERENCES products (id) ON DELETE SET NULL
                )
            ''')

            try:
                cursor.execute(
                    'CREATE INDEX IF NOT EXISTS idx_keyword_image_jobs_user_created '
                    'ON keyword_image_search_jobs(user_id, created_at)'
                )
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute(
                    'CREATE INDEX IF NOT EXISTS idx_keyword_image_jobs_website_created '
                    'ON keyword_image_search_jobs(website_id, created_at)'
                )
            except sqlite3.OperationalError:
                pass

            # 创建抓取状态表（持久化存储抓取状态）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scrape_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),  -- 只允许一条记录
                    is_scraping BOOLEAN DEFAULT 0,
                    stop_signal BOOLEAN DEFAULT 0,
                    current_shop_id TEXT,
                    total INTEGER DEFAULT 0,
                    processed INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    image_failed INTEGER DEFAULT 0,
                    index_failed INTEGER DEFAULT 0,
                    failed_items TEXT DEFAULT '[]',
                    progress REAL DEFAULT 0,
                    message TEXT DEFAULT '等待开始...',
                    completed BOOLEAN DEFAULT 0,
                    thread_id TEXT,  -- 记录当前线程ID
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            try:
                cursor.execute('ALTER TABLE scrape_status ADD COLUMN failed INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE scrape_status ADD COLUMN image_failed INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE scrape_status ADD COLUMN index_failed INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE scrape_status ADD COLUMN failed_items TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass

            # 插入默认网站配置
            cursor.execute('''
                INSERT OR IGNORE INTO website_configs (name, display_name, url_template, id_pattern, badge_color, reply_template)
                VALUES
                    ('cnfans', 'CNFans', 'https://cnfans.com/product?id={id}&platform=WEIDIAN', '{id}', 'blue', '{url}'),
                    ('acbuy', 'AcBuy', 'https://www.acbuy.com/product?url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}&id={id}&source=WD', '{id}', 'orange', '{url}'),
                    ('weidian', '微店', 'https://weidian.com/item.html?itemID={id}', '{id}', 'gray', '{url}')
            ''')

            # 插入默认状态记录
            cursor.execute('''
                INSERT OR IGNORE INTO scrape_status (id, is_scraping, stop_signal, message)
                VALUES (1, 0, 0, '等待开始...')
            ''')

            # 插入默认全局延迟配置
            cursor.execute('''
                INSERT OR IGNORE INTO global_reply_config (id, min_delay, max_delay)
                VALUES (1, 1.0, 3.0)
            ''')
            cursor.execute('''
                UPDATE global_reply_config
                SET min_delay = 1.0, max_delay = 3.0
                WHERE id = 1 AND min_delay = 3.0 AND max_delay = 8.0
            ''')
            cursor.execute('''
                UPDATE user_settings
                SET global_reply_min_delay = 1.0, global_reply_max_delay = 3.0
                WHERE global_reply_min_delay = 3.0 AND global_reply_max_delay = 8.0
            ''')

            conn.commit()

    def cleanup_processed_messages(self):
        """清理旧的消息处理记录，只保留最近1小时的记录"""
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM processed_messages WHERE processed_at < datetime('now', '-1 hour')")
                conn.commit()
        except Exception as e:
            logger.error(f"清理消息记录失败: {e}")


    @contextmanager
    def get_connection(self):
        """获取 SQLite 数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=60.0)
            conn.row_factory = sqlite3.Row
            self._configure_connection(conn, enable_wal=False)

            yield conn
        except sqlite3.IntegrityError:
            # 这是一个逻辑控制信号（如唯一性约束），直接抛出给上层处理，不记录为连接错误
            raise
        except Exception as e:
            logger.error("数据库连接失败: %s", str(e))
            raise
        finally:
            if conn:
                conn.close()

    def execute_query(self, query: str, params: tuple = None, fetch: bool = True) -> List[Dict]:
        """执行查询并返回结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            if fetch:
                results = [dict(row) for row in cursor.fetchall()]
                conn.commit()
                return results
            conn.commit()
            return []

    def insert_product(self, product_data: Dict) -> int:
        """插入商品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            product_url = product_data['product_url']
            cursor.execute("SELECT id FROM products WHERE product_url = ?", (product_url,))
            existing = cursor.fetchone()

            if existing:
                product_id = int(existing['id'])
                cursor.execute('''
                    UPDATE products
                    SET title = ?,
                        description = ?,
                        english_title = ?,
                        title_translations = ?,
                        cnfans_url = ?,
                        acbuy_url = ?,
                        shop_name = ?,
                        ruleEnabled = ?,
                        item_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    product_data.get('title', ''),
                    product_data.get('description', ''),
                    product_data.get('english_title', ''),
                    product_data.get('title_translations'),
                    product_data.get('cnfans_url', ''),
                    product_data.get('acbuy_url', ''),
                    product_data.get('shop_name', ''),
                    product_data.get('ruleEnabled', True),
                    product_data.get('item_id'),
                    product_id,
                ))
            else:
                cursor.execute('''
                    INSERT INTO products
                    (product_url, title, description, english_title, title_translations, cnfans_url, acbuy_url, shop_name, ruleEnabled, item_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    product_url,
                    product_data.get('title', ''),
                    product_data.get('description', ''),
                    product_data.get('english_title', ''),
                    product_data.get('title_translations'),
                    product_data.get('cnfans_url', ''),
                    product_data.get('acbuy_url', ''),
                    product_data.get('shop_name', ''),
                    product_data.get('ruleEnabled', True),
                    product_data.get('item_id'),
                ))
                product_id = cursor.lastrowid
            conn.commit()
            return product_id

    def insert_image_record(self, product_id: int, image_path: str, image_index: int) -> int:
        """插入图像记录到数据库，返回记录ID供检索缓存关联使用"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO product_images
                    (product_id, image_path, image_index)
                    VALUES (?, ?, ?)
                ''', (product_id, image_path, image_index))
                conn.commit()
                record_id = cursor.lastrowid
                logger.debug(f"图像记录插入成功: product_id={product_id}, image_index={image_index}, record_id={record_id}")
                return record_id

        except Exception as e:
            logger.error(f"插入图像记录失败: {e}")
            raise e

    def _get_product_url_by_id(self, product_id: int) -> Optional[str]:
        """根据产品ID获取产品URL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT product_url FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return row['product_url'] if row else None

    def get_image_info_by_id(self, image_id: int) -> Optional[Dict]:
        """根据图像记录ID获取图像信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM product_images WHERE id = ?", (image_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def _get_product_info_by_id(self, product_id: int) -> Optional[Dict]:
        """根据产品ID获取完整的产品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_indexed_product_ids(self) -> List[str]:
        """获取已有图片记录的商品URL列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT p.product_url
                FROM products p
                JOIN product_images pi ON p.id = pi.product_id
            ''')
            return [row['product_url'] for row in cursor.fetchall()]

    def get_product_images(self, product_id: int) -> List[Dict]:
        """获取商品的所有图片元数据"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, image_path, image_index
                    FROM product_images
                    WHERE product_id = ?
                    ORDER BY image_index
                ''', (product_id,))
                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"获取商品图片失败: {e}")
            return []

    def upsert_product_image_retrieval_cache(
        self,
        image_db_id: int,
        strategy_name: str,
        cache_version: str,
        embedding: Optional[List[float]] = None,
        color_hist: Optional[List[float]] = None,
        tokens: Optional[List[str]] = None,
    ) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO product_image_retrieval_cache
                    (image_db_id, strategy_name, cache_version, embedding_json, color_hist_json, tokens_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(image_db_id, strategy_name)
                    DO UPDATE SET
                        cache_version = excluded.cache_version,
                        embedding_json = excluded.embedding_json,
                        color_hist_json = excluded.color_hist_json,
                        tokens_json = excluded.tokens_json,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        image_db_id,
                        strategy_name,
                        cache_version,
                        json.dumps(embedding) if embedding is not None else None,
                        json.dumps(color_hist) if color_hist is not None else None,
                        json.dumps(tokens or []),
                    ),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError as e:
            if 'FOREIGN KEY constraint failed' in str(e):
                logger.warning(
                    "跳过商品检索缓存写入，图片记录不存在: image_db_id=%s strategy=%s",
                    image_db_id,
                    strategy_name,
                )
                return False
            logger.error(f"写入商品检索缓存失败: {e}")
            return False
        except Exception as e:
            logger.error(f"写入商品检索缓存失败: {e}")
            return False

    @staticmethod
    def _usable_retrieval_cache_sql(alias: str = 'rc') -> str:
        return (
            f"{alias}.image_db_id IS NOT NULL "
            f"AND {alias}.embedding_json IS NOT NULL "
            f"AND LENGTH({alias}.embedding_json) <= {MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH}"
        )

    @classmethod
    def _retrieval_cache_join_sql(
        cls,
        image_alias: str = 'pi',
        cache_alias: str = 'rc',
        *,
        include_usable_embedding: bool = False,
    ) -> str:
        clauses = [
            f"{cache_alias}.image_db_id = {image_alias}.id",
            f"{cache_alias}.strategy_name = ?",
        ]
        if include_usable_embedding:
            clauses.append(cls._usable_retrieval_cache_sql(cache_alias))
        return ' AND '.join(clauses)

    @staticmethod
    def _safe_retrieval_cache_field_sql(
        alias: str,
        field_name: str,
        max_length: int,
    ) -> str:
        return (
            f"CASE "
            f"WHEN {alias}.{field_name} IS NULL THEN NULL "
            f"WHEN LENGTH({alias}.{field_name}) <= {int(max_length)} THEN {alias}.{field_name} "
            f"ELSE NULL END"
        )

    def get_searchable_product_image_records(
        self,
        strategy_name: Optional[str] = None,
        require_cache: bool = False,
        only_missing_cache: bool = False,
        limit: Optional[int] = None,
        shop_names: Optional[Sequence[str]] = None,
        ordered: bool = True,
    ) -> List[Dict]:
        """获取实时图片检索需要的商品图片与商品元数据"""
        try:
            return list(
                self.iter_searchable_product_image_records(
                    strategy_name=strategy_name,
                    require_cache=require_cache,
                    only_missing_cache=only_missing_cache,
                    limit=limit,
                    shop_names=shop_names,
                    ordered=ordered,
                )
            )
        except Exception as e:
            logger.error(f"获取实时检索商品目录失败: {e}")
            return []

    @staticmethod
    def _normalize_searchable_product_shop_names(
        shop_names: Optional[Sequence[str]],
    ) -> Optional[List[str]]:
        if shop_names is None:
            return None
        normalized = []
        for shop_name in shop_names:
            text = str(shop_name or '').strip()
            if text:
                normalized.append(text)
        return normalized

    def _build_searchable_product_image_records_query(
        self,
        strategy_name: Optional[str] = None,
        require_cache: bool = False,
        only_missing_cache: bool = False,
        limit: Optional[int] = None,
        shop_names: Optional[Sequence[str]] = None,
        ordered: bool = True,
    ) -> tuple[Optional[str], List[Any]]:
        effective_limit = int(limit) if limit is not None else None
        normalized_shop_names = self._normalize_searchable_product_shop_names(shop_names)
        if shop_names is not None and not normalized_shop_names:
            return None, []

        params: List[Any] = []
        if strategy_name:
            if require_cache and not only_missing_cache:
                order_sql = "ORDER BY p.id ASC, pi.image_index ASC" if ordered else ""
                if normalized_shop_names:
                    placeholders = ','.join('?' for _ in normalized_shop_names)
                    params.extend(normalized_shop_names)
                    params.append(strategy_name)
                    query = f'''
                        SELECT
                            p.id AS product_id,
                            p.item_id,
                            p.title,
                            p.english_title,
                            p.description,
                            p.product_url,
                            p.cnfans_url,
                            p.acbuy_url,
                            p.shop_name,
                            p.ruleEnabled,
                            p.reply_scope,
                            p.image_source,
                            p.custom_reply_text,
                            p.custom_reply_images,
                            p.custom_image_urls,
                            p.uploaded_reply_images,
                            p.per_website_reply_settings,
                            pi.id AS image_db_id,
                            pi.image_path,
                            pi.image_index,
                            rc.strategy_name AS retrieval_cache_strategy,
                            rc.cache_version AS retrieval_cache_version,
                            rc.embedding_json AS retrieval_embedding,
                            {self._safe_retrieval_cache_field_sql('rc', 'color_hist_json', MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH)} AS retrieval_color_hist,
                            {self._safe_retrieval_cache_field_sql('rc', 'tokens_json', MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH)} AS retrieval_tokens
                        FROM products p
                        JOIN product_images pi ON pi.product_id = p.id
                        CROSS JOIN product_image_retrieval_cache rc INDEXED BY {USABLE_RETRIEVAL_CACHE_INDEX_NAME}
                        WHERE p.shop_name IN ({placeholders})
                          AND {self._retrieval_cache_join_sql('pi', 'rc', include_usable_embedding=True)}
                        {order_sql}
                    '''
                else:
                    params.append(strategy_name)
                    query = f'''
                        SELECT
                            p.id AS product_id,
                            p.item_id,
                            p.title,
                            p.english_title,
                            p.description,
                            p.product_url,
                            p.cnfans_url,
                            p.acbuy_url,
                            p.shop_name,
                            p.ruleEnabled,
                            p.reply_scope,
                            p.image_source,
                            p.custom_reply_text,
                            p.custom_reply_images,
                            p.custom_image_urls,
                            p.uploaded_reply_images,
                            p.per_website_reply_settings,
                            pi.id AS image_db_id,
                            pi.image_path,
                            pi.image_index,
                            rc.strategy_name AS retrieval_cache_strategy,
                            rc.cache_version AS retrieval_cache_version,
                            rc.embedding_json AS retrieval_embedding,
                            {self._safe_retrieval_cache_field_sql('rc', 'color_hist_json', MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH)} AS retrieval_color_hist,
                            {self._safe_retrieval_cache_field_sql('rc', 'tokens_json', MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH)} AS retrieval_tokens
                        FROM product_image_retrieval_cache rc
                        JOIN product_images pi ON pi.id = rc.image_db_id
                        JOIN products p ON p.id = pi.product_id
                        WHERE rc.strategy_name = ? AND {self._usable_retrieval_cache_sql('rc')}
                        {order_sql}
                    '''
            else:
                params.append(strategy_name)
                where_clauses = []
                if only_missing_cache:
                    where_clauses.append('rc.image_db_id IS NULL')
                if normalized_shop_names:
                    placeholders = ','.join('?' for _ in normalized_shop_names)
                    where_clauses.append(f'p.shop_name IN ({placeholders})')
                    params.extend(normalized_shop_names)

                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
                order_sql = "ORDER BY p.id ASC, pi.image_index ASC" if ordered else ""
                query = f'''
                    SELECT
                        p.id AS product_id,
                        p.item_id,
                        p.title,
                        p.english_title,
                        p.description,
                        p.product_url,
                        p.cnfans_url,
                        p.acbuy_url,
                        p.shop_name,
                        p.ruleEnabled,
                        p.reply_scope,
                        p.image_source,
                        p.custom_reply_text,
                        p.custom_reply_images,
                        p.custom_image_urls,
                        p.uploaded_reply_images,
                        p.per_website_reply_settings,
                        pi.id AS image_db_id,
                        pi.image_path,
                        pi.image_index,
                        rc.strategy_name AS retrieval_cache_strategy,
                        rc.cache_version AS retrieval_cache_version,
                        {self._safe_retrieval_cache_field_sql('rc', 'embedding_json', MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH)} AS retrieval_embedding,
                        {self._safe_retrieval_cache_field_sql('rc', 'color_hist_json', MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH)} AS retrieval_color_hist,
                        {self._safe_retrieval_cache_field_sql('rc', 'tokens_json', MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH)} AS retrieval_tokens
                    FROM products p
                    JOIN product_images pi ON pi.product_id = p.id
                    LEFT JOIN product_image_retrieval_cache rc
                        ON {self._retrieval_cache_join_sql('pi', 'rc', include_usable_embedding=only_missing_cache)}
                    {where_sql}
                    {order_sql}
                '''
        else:
            where_clauses = []
            if normalized_shop_names:
                placeholders = ','.join('?' for _ in normalized_shop_names)
                where_clauses.append(f'p.shop_name IN ({placeholders})')
                params.extend(normalized_shop_names)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
            order_sql = "ORDER BY p.id ASC, pi.image_index ASC" if ordered else ""
            query = f'''
                SELECT
                    p.id AS product_id,
                    p.item_id,
                    p.title,
                    p.english_title,
                    p.description,
                    p.product_url,
                    p.cnfans_url,
                    p.acbuy_url,
                    p.shop_name,
                    p.ruleEnabled,
                    p.reply_scope,
                    p.image_source,
                    p.custom_reply_text,
                    p.custom_reply_images,
                    p.custom_image_urls,
                    p.uploaded_reply_images,
                    p.per_website_reply_settings,
                    pi.id AS image_db_id,
                    pi.image_path,
                    pi.image_index
                FROM products p
                JOIN product_images pi ON pi.product_id = p.id
                {where_sql}
                {order_sql}
            '''

        if effective_limit and effective_limit > 0:
            query += ' LIMIT ?'
            params.append(effective_limit)

        return query, params

    def iter_searchable_product_image_records(
        self,
        strategy_name: Optional[str] = None,
        require_cache: bool = False,
        only_missing_cache: bool = False,
        limit: Optional[int] = None,
        shop_names: Optional[Sequence[str]] = None,
        batch_size: int = 256,
        ordered: bool = True,
    ):
        query, params = self._build_searchable_product_image_records_query(
            strategy_name=strategy_name,
            require_cache=require_cache,
            only_missing_cache=only_missing_cache,
            limit=limit,
            shop_names=shop_names,
            ordered=ordered,
        )
        if not query:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            fetch_batch_size = max(int(batch_size or 0), 1)
            yielded_rows = 0
            while True:
                fetch_started_at = perf_counter()
                rows = cursor.fetchmany(fetch_batch_size)
                fetch_elapsed = perf_counter() - fetch_started_at
                if fetch_elapsed >= 1.0:
                    logger.warning(
                        "Slow searchable record batch fetch: strategy=%s require_cache=%s only_missing_cache=%s ordered=%s batch_size=%s rows=%s yielded=%s shops=%s elapsed=%.2fs",
                        strategy_name,
                        require_cache,
                        only_missing_cache,
                        ordered,
                        fetch_batch_size,
                        len(rows),
                        yielded_rows,
                        list(shop_names or []),
                        fetch_elapsed,
                    )
                if not rows:
                    break
                for row in rows:
                    yielded_rows += 1
                    yield dict(row)

    def count_searchable_product_image_records(
        self,
        strategy_name: Optional[str] = None,
        require_cache: bool = False,
        only_missing_cache: bool = False,
        shop_names: Optional[Sequence[str]] = None,
    ) -> int:
        normalized_shop_names = self._normalize_searchable_product_shop_names(shop_names)
        if shop_names is not None and not normalized_shop_names:
            return 0

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                params: List[Any] = []

                if strategy_name:
                    params.append(strategy_name)
                    if require_cache and not only_missing_cache:
                        where_clauses = [
                            'rc.strategy_name = ?',
                            self._usable_retrieval_cache_sql('rc'),
                        ]
                        if normalized_shop_names:
                            placeholders = ','.join('?' for _ in normalized_shop_names)
                            where_clauses.append(f'p.shop_name IN ({placeholders})')
                            params.extend(normalized_shop_names)
                        query = f'''
                            SELECT COUNT(*)
                            FROM product_image_retrieval_cache rc
                            JOIN product_images pi ON pi.id = rc.image_db_id
                            JOIN products p ON p.id = pi.product_id
                            WHERE {' AND '.join(where_clauses)}
                        '''
                    else:
                        where_clauses = []
                        if only_missing_cache:
                            where_clauses.append('rc.image_db_id IS NULL')
                        if normalized_shop_names:
                            placeholders = ','.join('?' for _ in normalized_shop_names)
                            where_clauses.append(f'p.shop_name IN ({placeholders})')
                            params.extend(normalized_shop_names)
                        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
                        query = f'''
                            SELECT COUNT(*)
                            FROM products p
                            JOIN product_images pi ON pi.product_id = p.id
                            LEFT JOIN product_image_retrieval_cache rc
                                ON {self._retrieval_cache_join_sql('pi', 'rc', include_usable_embedding=only_missing_cache)}
                            {where_sql}
                        '''
                else:
                    where_clauses = []
                    if normalized_shop_names:
                        placeholders = ','.join('?' for _ in normalized_shop_names)
                        where_clauses.append(f'p.shop_name IN ({placeholders})')
                        params.extend(normalized_shop_names)
                    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
                    query = f'''
                        SELECT COUNT(*)
                        FROM products p
                        JOIN product_images pi ON pi.product_id = p.id
                        {where_sql}
                    '''

                cursor.execute(query, params)
                row = cursor.fetchone()
                return int(row[0] or 0) if row else 0
        except Exception as e:
            logger.error(f"统计实时检索商品目录失败: {e}")
            return 0

    def get_product_image_search_record(
        self,
        image_db_id: int,
        strategy_name: Optional[str] = None,
    ) -> Optional[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if strategy_name:
                    cursor.execute(
                        '''
                        SELECT
                            p.id AS product_id,
                            p.item_id,
                            p.title,
                            p.english_title,
                            p.description,
                            p.product_url,
                            p.cnfans_url,
                            p.acbuy_url,
                            p.shop_name,
                            p.ruleEnabled,
                            p.reply_scope,
                            p.image_source,
                            p.custom_reply_text,
                            p.custom_reply_images,
                            p.custom_image_urls,
                            p.uploaded_reply_images,
                            p.per_website_reply_settings,
                            pi.id AS image_db_id,
                            pi.image_path,
                            pi.image_index,
                            rc.strategy_name AS retrieval_cache_strategy,
                            rc.cache_version AS retrieval_cache_version,
                            {self._safe_retrieval_cache_field_sql('rc', 'embedding_json', MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH)} AS retrieval_embedding,
                            {self._safe_retrieval_cache_field_sql('rc', 'color_hist_json', MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH)} AS retrieval_color_hist,
                            {self._safe_retrieval_cache_field_sql('rc', 'tokens_json', MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH)} AS retrieval_tokens
                        FROM product_images pi
                        JOIN products p ON p.id = pi.product_id
                        LEFT JOIN product_image_retrieval_cache rc
                            ON rc.image_db_id = pi.id
                           AND rc.strategy_name = ?
                        WHERE pi.id = ?
                        ''',
                        (strategy_name, image_db_id),
                    )
                else:
                    cursor.execute(
                        '''
                        SELECT
                            p.id AS product_id,
                            p.item_id,
                            p.title,
                            p.english_title,
                            p.description,
                            p.product_url,
                            p.cnfans_url,
                            p.acbuy_url,
                            p.shop_name,
                            p.ruleEnabled,
                            p.reply_scope,
                            p.image_source,
                            p.custom_reply_text,
                            p.custom_reply_images,
                            p.custom_image_urls,
                            p.uploaded_reply_images,
                            p.per_website_reply_settings,
                            pi.id AS image_db_id,
                            pi.image_path,
                            pi.image_index
                        FROM product_images pi
                        JOIN products p ON p.id = pi.product_id
                        WHERE pi.id = ?
                        ''',
                        (image_db_id,),
                    )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"获取单张商品图片检索记录失败: {e}")
            return None

    def get_product_image_retrieval_embeddings(self, product_id: int, strategy_name: str) -> List[np.ndarray]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT rc.embedding_json
                    FROM product_image_retrieval_cache rc
                    JOIN product_images pi ON pi.id = rc.image_db_id
                    WHERE pi.product_id = ? AND rc.strategy_name = ? AND ''' + self._usable_retrieval_cache_sql('rc') + '''
                    ORDER BY pi.image_index ASC
                    ''',
                    (product_id, strategy_name),
                )
                embeddings = []
                for row in cursor.fetchall():
                    try:
                        embeddings.append(np.array(json.loads(row['embedding_json']), dtype='float32'))
                    except Exception:
                        continue
                return embeddings
        except Exception as e:
            logger.error(f"获取商品检索缓存向量失败: {e}")
            return []

    def count_product_image_retrieval_cache(self, strategy_name: str) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT COUNT(*)
                    FROM product_image_retrieval_cache rc
                    WHERE rc.strategy_name = ? AND ''' + self._usable_retrieval_cache_sql('rc') + '''
                    ''',
                    (strategy_name,),
                )
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"统计商品检索缓存数量失败: {e}")
            return 0

    def count_missing_product_image_retrieval_cache(
        self,
        strategy_name: str,
        max_count: Optional[int] = None,
    ) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                effective_limit = max(int(max_count or 0), 0)
                if effective_limit > 0:
                    cursor.execute(
                        '''
                        SELECT COUNT(*)
                        FROM (
                            SELECT 1
                            FROM products p
                            JOIN product_images pi ON pi.product_id = p.id
                            LEFT JOIN product_image_retrieval_cache rc
                                ON ''' + self._retrieval_cache_join_sql('pi', 'rc', include_usable_embedding=True) + '''
                            WHERE rc.image_db_id IS NULL
                            LIMIT ?
                        ) missing_rows
                        ''',
                        (strategy_name, effective_limit),
                    )
                else:
                    cursor.execute(
                        '''
                        SELECT COUNT(*)
                        FROM products p
                        JOIN product_images pi ON pi.product_id = p.id
                        LEFT JOIN product_image_retrieval_cache rc
                            ON ''' + self._retrieval_cache_join_sql('pi', 'rc', include_usable_embedding=True) + '''
                        WHERE rc.image_db_id IS NULL
                        ''',
                        (strategy_name,),
                    )
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"统计缺失商品检索缓存数量失败: {e}")
            return 0

    def compact_product_image_retrieval_cache(self, strategy_name: str) -> Dict[str, int]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    '''
                    UPDATE product_image_retrieval_cache
                    SET color_hist_json = NULL
                    WHERE strategy_name = ?
                      AND color_hist_json IS NOT NULL
                      AND LENGTH(color_hist_json) > ?
                    ''',
                    (strategy_name, MAX_USABLE_RETRIEVAL_COLOR_HIST_JSON_LENGTH),
                )
                trimmed_hist = max(int(cursor.rowcount or 0), 0)

                cursor.execute(
                    '''
                    UPDATE product_image_retrieval_cache
                    SET tokens_json = NULL
                    WHERE strategy_name = ?
                      AND tokens_json IS NOT NULL
                      AND LENGTH(tokens_json) > ?
                    ''',
                    (strategy_name, MAX_USABLE_RETRIEVAL_TOKENS_JSON_LENGTH),
                )
                trimmed_tokens = max(int(cursor.rowcount or 0), 0)

                cursor.execute(
                    '''
                    DELETE FROM product_image_retrieval_cache
                    WHERE strategy_name = ?
                      AND (
                        embedding_json IS NULL
                        OR LENGTH(embedding_json) > ?
                      )
                    ''',
                    (strategy_name, MAX_USABLE_RETRIEVAL_EMBEDDING_JSON_LENGTH),
                )
                deleted_rows = max(int(cursor.rowcount or 0), 0)
                conn.commit()

                return {
                    'trimmed_hist': trimmed_hist,
                    'trimmed_tokens': trimmed_tokens,
                    'deleted_rows': deleted_rows,
                }
        except Exception as e:
            logger.error(f"压缩商品检索缓存失败: {e}")
            return {
                'trimmed_hist': 0,
                'trimmed_tokens': 0,
                'deleted_rows': 0,
            }

    def delete_product_images(self, product_id: int) -> bool:
        """删除商品的所有图像和物理文件"""
        try:
            # 获取该商品的所有图像记录ID和文件路径
            image_records = []
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, image_path FROM product_images WHERE product_id = ?", (product_id,))
                image_records = [{'id': row['id'], 'path': row['image_path']} for row in cursor.fetchall()]

            # 删除物理文件
            for record in image_records:
                if record['path'] and os.path.exists(record['path']):
                    try:
                        os.remove(record['path'])
                        logger.info(f"已删除商品图片文件: {record['path']}")
                    except Exception as e:
                        logger.warning(f"删除商品图片文件失败: {e}")

            # 从 SQLite 删除
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                conn.commit()

            return True
        except Exception as e:
            logger.error(f"删除商品图像失败: {e}")
            return False

    def delete_products_bulk(self, product_ids: List[int], max_workers: int = 8) -> Dict[str, Any]:
        """批量删除商品及其图片与检索缓存关联数据"""
        try:
            normalized_ids = []
            for pid in product_ids or []:
                try:
                    normalized_ids.append(int(pid))
                except (TypeError, ValueError):
                    continue

            if not normalized_ids:
                return {'deleted_count': 0, 'missing_ids': [], 'file_failed_count': 0}

            unique_ids = sorted(set(normalized_ids))
            existing_ids = set()
            image_records = []

            def chunked(values, size):
                for idx in range(0, len(values), size):
                    yield values[idx:idx + size]

            with self.get_connection() as conn:
                cursor = conn.cursor()
                for chunk in chunked(unique_ids, 500):
                    placeholders = ','.join(['?'] * len(chunk))
                    cursor.execute(f"SELECT id FROM products WHERE id IN ({placeholders})", chunk)
                    existing_ids.update([row['id'] for row in cursor.fetchall()])

                if not existing_ids:
                    return {'deleted_count': 0, 'missing_ids': unique_ids, 'file_failed_count': 0}

                existing_list = list(existing_ids)
                for chunk in chunked(existing_list, 500):
                    placeholders = ','.join(['?'] * len(chunk))
                    cursor.execute(
                        f"SELECT id, image_path FROM product_images WHERE product_id IN ({placeholders})",
                        chunk
                    )
                    image_records.extend([{'id': row['id'], 'path': row['image_path']} for row in cursor.fetchall()])

            file_failed = {'count': 0}
            if image_records:
                import concurrent.futures
                import threading

                lock = threading.Lock()

                def remove_file(path: str):
                    if not path:
                        return
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            with lock:
                                file_failed['count'] += 1

                workers = min(max_workers, len(image_records))
                if workers > 1:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                        executor.map(lambda rec: remove_file(rec['path']), image_records)
                else:
                    for record in image_records:
                        remove_file(record['path'])

            with self.get_connection() as conn:
                cursor = conn.cursor()
                existing_list = list(existing_ids)
                for chunk in chunked(existing_list, 500):
                    placeholders = ','.join(['?'] * len(chunk))
                    cursor.execute(f"DELETE FROM product_images WHERE product_id IN ({placeholders})", chunk)
                    cursor.execute(f"DELETE FROM products WHERE id IN ({placeholders})", chunk)
                conn.commit()

            missing_ids = [pid for pid in unique_ids if pid not in existing_ids]

            return {
                'deleted_count': len(existing_ids),
                'missing_ids': missing_ids,
                'file_failed_count': file_failed['count']
            }
        except Exception as e:
            logger.error(f"批量删除商品失败: {e}")
            return {'deleted_count': 0, 'missing_ids': [], 'file_failed_count': 0, 'error': str(e)}

    def delete_image_record(self, image_id: int) -> bool:
        """根据图片ID删除图片记录（用于回滚操作）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE id = ?", (image_id,))
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"已删除图片记录: id={image_id}")
                return deleted
        except Exception as e:
            logger.error(f"删除图片记录失败: {e}")
            return False

    def delete_product_image_record(self, product_id: int, image_index: int) -> bool:
        """删除特定商品图片记录及其物理文件"""
        try:
            # 获取该图像的记录ID和文件路径
            image_path = None
            image_id = None
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, image_path FROM product_images WHERE product_id = ? AND image_index = ?",
                             (product_id, image_index))
                row = cursor.fetchone()
                if row:
                    image_id = row['id']
                    image_path = row['image_path']

            if not image_id:
                logger.warning(f"图片不存在: product_id={product_id}, image_index={image_index}")
                return False

            # 删除物理文件
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                    logger.info(f"已删除图片文件: {image_path}")
                except Exception as e:
                    logger.warning(f"删除图片文件失败: {e}")

            # 从 SQLite 删除记录
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM product_images WHERE product_id = ? AND image_index = ?",
                             (product_id, image_index))
                conn.commit()

            logger.info(f"图片删除成功: product_id={product_id}, image_index={image_index}")
            return True
        except Exception as e:
            logger.error(f"删除商品图片记录失败: {e}")
            return False

    def get_product_by_url(self, product_url: str) -> Optional[Dict]:
        """根据商品URL获取商品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE product_url = ?", (product_url,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_product_by_item_id(self, item_id: str) -> Optional[Dict]:
        """根据微店商品ID获取商品信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE item_id = ?", (item_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_existing_item_ids(self) -> set:
        """获取数据库中所有已存在的商品item_id，用于快速查重"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item_id FROM products WHERE item_id IS NOT NULL")
            return {row[0] for row in cursor.fetchall()}

    def cleanup_unused_images(self, days_old: int = 30) -> int:
        """
        清理未使用的图片文件
        删除那些在数据库中不存在记录的图片文件，或者删除超过指定天数的旧图片

        Args:
            days_old: 删除多少天前的图片（默认30天）

        Returns:
            删除的文件数量
        """
        try:
            import os
            import time

            # 获取所有数据库中存在的图片路径
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT image_path FROM product_images")
                db_image_paths = set(row['image_path'] for row in cursor.fetchall())

            # 获取data/images目录下的所有文件
            images_dir = os.path.join('data', 'images')
            if not os.path.exists(images_dir):
                return 0

            deleted_count = 0
            cutoff_time = time.time() - (days_old * 24 * 60 * 60)

            for filename in os.listdir(images_dir):
                filepath = os.path.join(images_dir, filename)

                # 只处理jpg文件
                if not filename.endswith('.jpg'):
                    continue

                # 检查是否在数据库中存在
                if filepath not in db_image_paths:
                    try:
                        os.remove(filepath)
                        logger.info(f"清理未使用的图片文件: {filepath}")
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"删除文件失败 {filepath}: {e}")
                # 或者检查是否太旧（即使在数据库中）
                elif os.path.getmtime(filepath) < cutoff_time:
                    # 这里可以选择是否删除旧文件
                    # 暂时保留，避免误删
                    pass

            if deleted_count > 0:
                logger.info(f"图片清理完成，共删除 {deleted_count} 个未使用的文件")

            return deleted_count

        except Exception as e:
            logger.error(f"图片清理失败: {e}")
            return 0

    def get_product_id_by_url(self, product_url: str) -> Optional[int]:
        """根据商品URL获取商品内部ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM products WHERE product_url = ?", (product_url,))
            row = cursor.fetchone()
            return row['id'] if row else None

    def get_total_indexed_images(self) -> int:
        """获取已建立当前检索缓存的总图片数量"""
        try:
            strategy_name = getattr(config, 'LIVE_IMAGE_SEARCH_STRATEGY', 'siglip2_rerank')
            return self.count_product_image_retrieval_cache(strategy_name)
        except Exception as e:
            logger.error(f"获取检索缓存图片数量失败: {e}")
            return 0

    def get_indexed_product_urls(self) -> List[str]:
        """获取已建立当前检索缓存的商品URL列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                strategy_name = getattr(config, 'LIVE_IMAGE_SEARCH_STRATEGY', 'siglip2_rerank')
                cursor.execute('''
                    SELECT DISTINCT p.product_url
                    FROM products p
                    JOIN product_images pi ON p.id = pi.product_id
                    JOIN product_image_retrieval_cache rc ON rc.image_db_id = pi.id
                    WHERE rc.strategy_name = ?
                ''', (strategy_name,))
                return [row['product_url'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取已建立检索缓存的商品URL失败: {e}")
            return []

    def add_search_history(
        self,
        query_image_path: str,
        matched_product_id: int,
        matched_image_index: int,
        similarity: float,
        threshold: float,
        is_skipped: bool = False,
        discord_message_id: Optional[str] = None,
        discord_channel_id: Optional[str] = None,
        discord_channel_name: str = '',
        discord_author_id: Optional[str] = None,
        discord_author_name: str = '',
        message_content: str = '',
    ) -> bool:
        """添加搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO search_history
                    (
                        query_image_path, matched_product_id, matched_image_index,
                        similarity, threshold, is_skipped, discord_message_id,
                        discord_channel_id, discord_channel_name, discord_author_id,
                        discord_author_name, message_content
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    query_image_path,
                    matched_product_id,
                    matched_image_index,
                    similarity,
                    threshold,
                    1 if is_skipped else 0,
                    discord_message_id,
                    discord_channel_id,
                    discord_channel_name or '',
                    discord_author_id,
                    discord_author_name or '',
                    message_content or '',
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加搜索历史失败: {e}")
            return False

    def get_search_history(self, limit: int = 50, offset: int = 0, skipped: Optional[bool] = None) -> Dict:
        """获取搜索历史记录（支持分页）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                where_clause = ''
                params: List[Any] = []
                if skipped is not None:
                    where_clause = 'WHERE sh.is_skipped = ?'
                    params.append(1 if skipped else 0)

                # 获取总数
                count_query = 'SELECT COUNT(*) FROM search_history sh'
                if where_clause:
                    count_query += f' {where_clause}'
                cursor.execute(count_query, params)
                total = cursor.fetchone()[0]

                # 获取分页数据
                query = f'''
                    SELECT
                        sh.id,
                        sh.query_image_path,
                        sh.matched_product_id,
                        sh.matched_image_index,
                        sh.similarity,
                        sh.threshold,
                        COALESCE(sh.is_skipped, 0) as is_skipped,
                        sh.discord_message_id,
                        sh.discord_channel_id,
                        sh.discord_channel_name,
                        sh.discord_author_id,
                        sh.discord_author_name,
                        sh.message_content,
                        sh.search_time,
                        p.title,
                        p.english_title,
                        p.product_url as weidian_url,
                        p.cnfans_url,
                        p.acbuy_url,
                        p.ruleEnabled,
                        pi.image_path as matched_image_path
                    FROM search_history sh
                    LEFT JOIN products p ON sh.matched_product_id = p.id
                    LEFT JOIN product_images pi ON sh.matched_product_id = pi.product_id AND sh.matched_image_index = pi.image_index
                    {where_clause}
                    ORDER BY sh.search_time DESC, sh.id DESC
                    LIMIT ? OFFSET ?
                '''
                cursor.execute(query, (*params, limit, offset))
                rows = cursor.fetchall()
                history = []
                for row in rows:
                    weidian_url = row['weidian_url']
                    weidian_id = ''
                    if weidian_url:
                        try:
                            import re
                            match = re.search(r'itemID=(\d+)', weidian_url)
                            if match:
                                weidian_id = match.group(1)
                        except Exception:
                            weidian_id = ''

                    website_urls = []
                    if weidian_id:
                        try:
                            website_urls = self.generate_website_urls(weidian_id)
                        except Exception:
                            website_urls = []

                    history.append({
                        'id': row['id'],
                        'query_image_path': row['query_image_path'],
                        'matched_product_id': row['matched_product_id'],
                        'matched_image_index': row['matched_image_index'],
                        'similarity': row['similarity'],
                        'threshold': row['threshold'],
                        'is_skipped': 1 if int(row['is_skipped'] or 0) else 0,
                        'discord_message_id': row['discord_message_id'] or '',
                        'discord_channel_id': row['discord_channel_id'] or '',
                        'discord_channel_name': row['discord_channel_name'] or '',
                        'discord_author_id': row['discord_author_id'] or '',
                        'discord_author_name': row['discord_author_name'] or '',
                        'message_content': row['message_content'] or '',
                        'search_time': row['search_time'],
                        'title': row['title'],
                        'english_title': row['english_title'],
                        'weidian_url': weidian_url,
                        'cnfans_url': row['cnfans_url'],
                        'acbuy_url': row['acbuy_url'],
                        'ruleEnabled': row['ruleEnabled'],
                        'matched_image_path': row['matched_image_path'],
                        'websiteUrls': website_urls
                    })

                return {
                    'history': history,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                    'has_more': offset + limit < total
                }
        except Exception as e:
            logger.error(f"获取搜索历史失败: {e}")
            return []

    def delete_search_history(self, history_id: int) -> bool:
        """删除搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM search_history WHERE id = ?', (history_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除搜索历史失败: {e}")
            return False

    def clear_search_history(self) -> bool:
        """清空所有搜索历史"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM search_history')
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"清空搜索历史失败: {e}")
            return False

    def add_skipped_image_history(
        self,
        query_image_path: str,
        similarity: float,
        threshold: float,
        discord_message_id: Optional[str] = None,
        discord_channel_id: Optional[str] = None,
        discord_channel_name: str = '',
        discord_author_id: Optional[str] = None,
        discord_author_name: str = '',
        message_content: str = '',
        matched_product_id: Optional[int] = None,
        matched_image_index: Optional[int] = None,
    ) -> Optional[int]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO skipped_image_history (
                        query_image_path, matched_product_id, matched_image_index,
                        similarity, threshold, discord_message_id, discord_channel_id,
                        discord_channel_name, discord_author_id, discord_author_name,
                        message_content
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        query_image_path,
                        matched_product_id,
                        matched_image_index,
                        similarity,
                        threshold,
                        discord_message_id,
                        discord_channel_id,
                        discord_channel_name or '',
                        discord_author_id,
                        discord_author_name or '',
                        message_content or '',
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"保存略过图片历史失败: {e}")
            return None

    def get_skipped_image_history(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM skipped_image_history')
                total = cursor.fetchone()[0]

                cursor.execute(
                    '''
                    SELECT
                        sih.id,
                        sih.query_image_path,
                        sih.matched_product_id,
                        sih.matched_image_index,
                        sih.similarity,
                        sih.threshold,
                        sih.discord_message_id,
                        sih.discord_channel_id,
                        sih.discord_channel_name,
                        sih.discord_author_id,
                        sih.discord_author_name,
                        sih.message_content,
                        sih.created_at,
                        p.title,
                        p.english_title,
                        p.product_url AS weidian_url
                    FROM skipped_image_history sih
                    LEFT JOIN products p ON sih.matched_product_id = p.id
                    ORDER BY sih.created_at DESC, sih.id DESC
                    LIMIT ? OFFSET ?
                    ''',
                    (limit, offset),
                )
                rows = cursor.fetchall()
                history = []
                for row in rows:
                    history.append({
                        'id': row[0],
                        'query_image_path': row[1],
                        'matched_product_id': row[2],
                        'matched_image_index': row[3],
                        'similarity': float(row[4]),
                        'threshold': float(row[5]),
                        'discord_message_id': row[6] or '',
                        'discord_channel_id': row[7] or '',
                        'discord_channel_name': row[8] or '',
                        'discord_author_id': row[9] or '',
                        'discord_author_name': row[10] or '',
                        'message_content': row[11] or '',
                        'created_at': row[12],
                        'title': row[13] or '',
                        'english_title': row[14] or '',
                        'weidian_url': row[15] or '',
                    })

                return {
                    'history': history,
                    'total': total,
                    'has_more': offset + limit < total,
                }
        except Exception as e:
            logger.error(f"获取略过图片历史失败: {e}")
            return {
                'history': [],
                'total': 0,
                'has_more': False,
            }

    def delete_skipped_image_history(self, history_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM skipped_image_history WHERE id = ?', (history_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除略过图片历史失败: {e}")
            return False

    def clear_skipped_image_history(self) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM skipped_image_history')
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"清空略过图片历史失败: {e}")
            return False

    # ===== 用户权限管理方法 =====

    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """用户认证"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, username, password_hash, role, is_active, created_at
                    FROM users
                    WHERE username = ?
                ''', (username,))
                user = cursor.fetchone()
                if user:
                    user_dict = dict(user)
                    is_active = user_dict.get('is_active')
                    if is_active is not None and int(is_active) == 0:
                        return None
                    stored_hash = user_dict.get('password_hash')

                    # 验证密码
                    authenticated = False

                    if stored_hash:
                        # 首先尝试Werkzeug哈希验证（新用户）
                        from werkzeug.security import check_password_hash
                        if check_password_hash(stored_hash, password):
                            authenticated = True
                        # 如果失败，尝试旧的哈希方式（兼容旧用户）
                        elif stored_hash == f"hashed_{password}":
                            authenticated = True

                    if not authenticated and stored_hash == password:
                        authenticated = True
                        try:
                            from werkzeug.security import generate_password_hash
                            new_hash = generate_password_hash(password)
                            cursor.execute('''
                                UPDATE users SET password_hash = ?, updated_at = datetime('now')
                                WHERE id = ?
                            ''', (new_hash, user_dict['id']))
                            conn.commit()
                        except Exception as update_error:
                            logger.warning(f"升级用户密码哈希失败: {update_error}")

                    if authenticated:
                        # 获取用户管理的店铺
                        user_dict['shops'] = self.get_user_shops(user_dict['id'])
                        return user_dict
                return None
        except Exception as e:
            logger.error(f"用户认证失败: {e}")
            return None

    def create_user(self, username: str, password_hash: str, role: str = 'user') -> bool:
        """创建新用户（password_hash 由上层生成）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO users (username, password_hash, role, is_active)
                    VALUES (?, ?, ?, 1)
                ''', (username, password_hash, role))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"用户名已存在: {username}")
            return False
        except Exception as e:
            logger.error(f"创建用户失败: {e}")
            return False

    def get_all_users(self) -> List[Dict]:
        """获取所有用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, username, role, is_active, image_search_count, created_at
                    FROM users
                    ORDER BY created_at DESC
                ''')
                users = []
                for row in cursor.fetchall():
                    user = dict(row)
                    user['image_search_count'] = user.get('image_search_count', 0) or 0
                    user['shops'] = self.get_user_shops(user['id'])
                    users.append(user)
                return users
        except Exception as e:
            logger.error(f"获取用户列表失败: {e}")
            return []

    def get_user_shops(self, user_id: int) -> List[str]:
        """获取用户管理的店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT shop_id FROM user_shop_permissions
                    WHERE user_id = ?
                ''', (user_id,))
                return [row['shop_id'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取用户店铺权限失败: {e}")
            return []

    def update_user_shops(self, user_id: int, shop_ids: List[str]) -> bool:
        """更新用户的店铺权限"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 先删除旧的权限
                cursor.execute('DELETE FROM user_shop_permissions WHERE user_id = ?', (user_id,))

                # 添加新的权限
                for shop_id in shop_ids:
                    cursor.execute('''
                        INSERT INTO user_shop_permissions (user_id, shop_id)
                        VALUES (?, ?)
                    ''', (user_id, shop_id))

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户店铺权限失败: {e}")
            return False

    def add_user_shop_permission(self, user_id: int, shop_id: str) -> bool:
        """为用户追加单个店铺权限"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO user_shop_permissions (user_id, shop_id)
                    VALUES (?, ?)
                ''', (user_id, shop_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"追加用户店铺权限失败: {e}")
            return False

    def get_user_ids_by_shop(self, shop_id: str) -> List[int]:
        """获取拥有某个店铺权限的用户ID列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT user_id
                    FROM user_shop_permissions
                    WHERE shop_id = ?
                ''', (shop_id,))
                return [int(row['user_id']) for row in cursor.fetchall() if row['user_id'] is not None]
        except Exception as e:
            logger.error(f"获取店铺权限用户失败: {e}")
            return []

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据ID获取用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, username, role, is_active, image_search_count, created_at
                    FROM users
                    WHERE id = ?
                ''', (user_id,))
                user = cursor.fetchone()
                if user:
                    user_dict = dict(user)
                    user_dict['image_search_count'] = user_dict.get('image_search_count', 0) or 0
                    user_dict['shops'] = self.get_user_shops(user_id)
                    return user_dict
                return None
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return None

    def increment_user_image_search_count(self, user_id: int) -> bool:
        """增加用户以图搜图次数"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users
                    SET image_search_count = COALESCE(image_search_count, 0) + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (user_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新用户搜索次数失败: {e}")
            return False

    def update_discord_account_user(self, account_id: int, user_id: Optional[int]) -> bool:
        """更新Discord账号关联的用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE discord_accounts
                    SET user_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (user_id, account_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新Discord账号用户关联失败: {e}")
            return False

    def get_discord_accounts_by_user(self, user_id: Optional[int]) -> List[Dict]:
        """获取用户关联的Discord账号"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id is None:
                    # 管理员查询所有账号
                    cursor.execute('''
                        SELECT id, username, token, status, last_active, created_at, user_id, auto_start_enabled
                    FROM discord_accounts
                    ORDER BY created_at DESC
                    ''')
                else:
                    # 普通用户查询自己的账号
                    cursor.execute('''
                        SELECT id, username, token, status, last_active, created_at, user_id, auto_start_enabled
                        FROM discord_accounts
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                    ''', (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取用户Discord账号失败: {e}")
            return []

    def get_discord_accounts_marked_for_autostart(self) -> List[Dict]:
        """获取服务重启后需要自动恢复的 Discord 账号"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT id, username, token, status, last_active, created_at, user_id, auto_start_enabled
                    FROM discord_accounts
                    WHERE auto_start_enabled = 1
                    ORDER BY created_at DESC
                    '''
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取自动恢复Discord账号失败: {e}")
            return []

    def set_discord_accounts_autostart_by_user(self, user_id: int, enabled: bool) -> int:
        """按用户更新 Discord 账号的自动恢复开关"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    UPDATE discord_accounts
                    SET auto_start_enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    ''',
                    (1 if enabled else 0, user_id),
                )
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"更新Discord账号自动恢复开关失败: {e}")
            return 0

    def update_product_title(self, product_id: int, title: str) -> bool:
        """更新商品标题"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE products
                    SET title = ?, updated_at = datetime('now')
                    WHERE id = ?
                ''', (title, product_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新商品标题失败: {e}")
            return False

    def update_product(self, product_id: int, updates: Dict) -> bool:
        """更新商品信息（通用方法）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 构建动态更新语句
                set_parts = []
                params = []
                allowed_fields = [
                    'title', 'english_title', 'title_translations',
                    'partition_match_enabled', 'partition_match_rules',
                    'ruleEnabled',
                    'custom_reply_text', 'custom_reply_images', 'custom_image_urls',
                    'image_source', 'uploaded_reply_images', 'reply_scope',
                    'per_website_reply_settings'
                ]

                for field in allowed_fields:
                    if field in updates:
                        set_parts.append(f'{field} = ?')
                        if (field == 'custom_reply_images' or field == 'custom_image_urls') and isinstance(updates[field], list):
                            # 将图片索引或URL数组转换为JSON字符串
                            params.append(json.dumps(updates[field]))
                        else:
                            params.append(updates[field])

                if not set_parts:
                    return False

                set_parts.append('updated_at = datetime(\'now\')')

                query = f'''
                    UPDATE products
                    SET {', '.join(set_parts)}
                    WHERE id = ?
                '''
                params.append(product_id)

                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新商品失败: {e}")
            return False

    def get_product_by_id(self, product_id: int) -> Optional[Dict]:
        """根据ID获取商品"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"获取商品失败: {e}")
            return None

    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 首先删除用户的所有相关数据
                # 删除用户的网站账号绑定
                cursor.execute('DELETE FROM website_account_bindings WHERE user_id = ?', (user_id,))
                # 删除用户的Discord账号
                cursor.execute('DELETE FROM discord_accounts WHERE user_id = ?', (user_id,))
                # 删除用户的设置
                cursor.execute('DELETE FROM user_settings WHERE user_id = ?', (user_id,))
                # 删除用户
                cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除用户失败: {e}")
            return False

    def update_account_status(
        self,
        account_id: int,
        status: str,
        min_update_interval_seconds: Optional[int] = None,
    ) -> bool:
        """更新Discord账号状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                min_interval = max(int(min_update_interval_seconds or 0), 0)
                if min_interval > 0:
                    cursor.execute(
                        '''
                        UPDATE discord_accounts
                        SET status = ?, last_active = datetime('now')
                        WHERE id = ?
                          AND (
                              status IS NULL
                              OR status <> ?
                              OR last_active IS NULL
                              OR last_active <= datetime('now', ?)
                          )
                        ''',
                        (status, account_id, status, f'-{min_interval} seconds'),
                    )
                else:
                    cursor.execute(
                        '''
                        UPDATE discord_accounts
                        SET status = ?, last_active = datetime('now')
                        WHERE id = ?
                        ''',
                        (status, account_id),
                    )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新账号状态失败: {e}")
            return False

    def get_website_configs(self) -> List[Dict]:
        """获取所有网站配置及其频道绑定（优化版本，避免N+1查询）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 使用LEFT JOIN一次性获取所有网站和其频道绑定
                cursor.execute('''
                    SELECT
                        wc.id, wc.name, wc.display_name, wc.url_template,
                        wc.id_pattern, wc.badge_color, wc.reply_template, wc.reply_language,
                        wc.image_similarity_threshold, wc.blocked_role_ids,
                        wc.rotation_interval, wc.rotation_enabled, wc.message_filters,
                        wc.stat_replies_text, wc.stat_replies_image, wc.stat_replies_total,
                        COALESCE(wrd.stat_replies_text, 0) as stat_replies_daily_text,
                        COALESCE(wrd.stat_replies_image, 0) as stat_replies_daily_image,
                        COALESCE(wrd.stat_replies_total, 0) as stat_replies_daily_total,
                        wc.created_at,
                        GROUP_CONCAT(wcb.channel_id) as channels
                    FROM website_configs wc
                    LEFT JOIN website_channel_bindings wcb ON wc.id = wcb.website_id
                    LEFT JOIN website_reply_stats_daily wrd
                        ON wc.id = wrd.website_id
                        AND wrd.stat_date = date('now','localtime')
                    GROUP BY wc.id, wc.name, wc.display_name, wc.url_template, wc.id_pattern, wc.badge_color, wc.reply_template, wc.reply_language, wc.image_similarity_threshold, wc.blocked_role_ids, wc.rotation_interval, wc.rotation_enabled, wc.message_filters, wc.stat_replies_text, wc.stat_replies_image, wc.stat_replies_total, wrd.stat_replies_text, wrd.stat_replies_image, wrd.stat_replies_total, wc.created_at
                    ORDER BY wc.created_at
                ''')

                configs = []
                for row in cursor.fetchall():
                    config = dict(row)
                    config['reply_language'] = get_effective_reply_languages(
                        config.get('reply_language')
                    )
                    config['stat_replies_text'] = config.get('stat_replies_text', 0) or 0
                    config['stat_replies_image'] = config.get('stat_replies_image', 0) or 0
                    config['stat_replies_total'] = config.get('stat_replies_total', 0) or 0
                    config['stat_replies_daily_text'] = config.get('stat_replies_daily_text', 0) or 0
                    config['stat_replies_daily_image'] = config.get('stat_replies_daily_image', 0) or 0
                    config['stat_replies_daily_total'] = config.get('stat_replies_daily_total', 0) or 0
                    # 将channels字符串解析为数组
                    if config.get('channels'):
                        config['channels'] = config['channels'].split(',') if config['channels'] else []
                    else:
                        config['channels'] = []
                    configs.append(config)

                return configs
        except Exception as e:
            logger.error(f"获取网站配置失败: {e}")
            return []

    def increment_website_stats(self, website_id: int, has_text: bool, has_image: bool, user_id: int = None) -> bool:
        """增加网站回复统计（普通用户不计入全局统计）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                daily_text = 1 if has_text else 0
                daily_image = 1 if has_image else 0
                should_update_global = True

                if user_id:
                    cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
                    row = cursor.fetchone()
                    role = row['role'] if row else None
                    if role and role != 'admin':
                        should_update_global = False

                    cursor.execute('''
                        INSERT INTO user_reply_stats (
                            user_id,
                            stat_replies_total,
                            stat_replies_text,
                            stat_replies_image
                        )
                        VALUES (?, 1, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            stat_replies_total = stat_replies_total + 1,
                            stat_replies_text = stat_replies_text + excluded.stat_replies_text,
                            stat_replies_image = stat_replies_image + excluded.stat_replies_image,
                            updated_at = CURRENT_TIMESTAMP
                    ''', (user_id, daily_text, daily_image))

                    cursor.execute('''
                        INSERT INTO user_reply_stats_daily (
                            user_id,
                            stat_date,
                            stat_replies_total,
                            stat_replies_text,
                            stat_replies_image
                        )
                        VALUES (?, date('now','localtime'), 1, ?, ?)
                        ON CONFLICT(user_id, stat_date) DO UPDATE SET
                            stat_replies_total = stat_replies_total + 1,
                            stat_replies_text = stat_replies_text + excluded.stat_replies_text,
                            stat_replies_image = stat_replies_image + excluded.stat_replies_image
                    ''', (user_id, daily_text, daily_image))

                    cursor.execute('''
                        INSERT INTO user_website_reply_stats (
                            user_id,
                            website_id,
                            stat_replies_total,
                            stat_replies_text,
                            stat_replies_image
                        )
                        VALUES (?, ?, 1, ?, ?)
                        ON CONFLICT(user_id, website_id) DO UPDATE SET
                            stat_replies_total = stat_replies_total + 1,
                            stat_replies_text = stat_replies_text + excluded.stat_replies_text,
                            stat_replies_image = stat_replies_image + excluded.stat_replies_image,
                            updated_at = CURRENT_TIMESTAMP
                    ''', (user_id, website_id, daily_text, daily_image))

                    cursor.execute('''
                        INSERT INTO user_website_reply_stats_daily (
                            user_id,
                            website_id,
                            stat_date,
                            stat_replies_total,
                            stat_replies_text,
                            stat_replies_image
                        )
                        VALUES (?, ?, date('now','localtime'), 1, ?, ?)
                        ON CONFLICT(user_id, website_id, stat_date) DO UPDATE SET
                            stat_replies_total = stat_replies_total + 1,
                            stat_replies_text = stat_replies_text + excluded.stat_replies_text,
                            stat_replies_image = stat_replies_image + excluded.stat_replies_image
                    ''', (user_id, website_id, daily_text, daily_image))

                if should_update_global:
                    updates = ['stat_replies_total = stat_replies_total + 1']
                    if has_text:
                        updates.append('stat_replies_text = stat_replies_text + 1')
                    if has_image:
                        updates.append('stat_replies_image = stat_replies_image + 1')

                    cursor.execute(f'''
                        UPDATE website_configs
                        SET {', '.join(updates)}
                        WHERE id = ?
                    ''', (website_id,))

                    cursor.execute('''
                        INSERT INTO website_reply_stats_daily (
                            website_id,
                            stat_date,
                            stat_replies_total,
                            stat_replies_text,
                            stat_replies_image
                        )
                        VALUES (?, date('now','localtime'), 1, ?, ?)
                        ON CONFLICT(website_id, stat_date) DO UPDATE SET
                            stat_replies_total = stat_replies_total + 1,
                            stat_replies_text = stat_replies_text + excluded.stat_replies_text,
                            stat_replies_image = stat_replies_image + excluded.stat_replies_image
                    ''', (website_id, daily_text, daily_image))

                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站回复统计失败: {e}")
            return False

    def get_user_website_reply_stats_map(self, user_id: int, website_ids: List[int] = None) -> Dict[int, Dict[str, int]]:
        """获取用户维度的网站回复统计映射。"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                params = [user_id]
                website_filter_clause = ''
                if website_ids:
                    placeholders = ','.join('?' for _ in website_ids)
                    website_filter_clause = f' AND uwrs.website_id IN ({placeholders})'
                    params.extend(website_ids)

                cursor.execute(f'''
                    SELECT
                        uwrs.website_id,
                        uwrs.stat_replies_total,
                        uwrs.stat_replies_text,
                        uwrs.stat_replies_image,
                        COALESCE(uwrsd.stat_replies_total, 0) AS stat_replies_daily_total,
                        COALESCE(uwrsd.stat_replies_text, 0) AS stat_replies_daily_text,
                        COALESCE(uwrsd.stat_replies_image, 0) AS stat_replies_daily_image
                    FROM user_website_reply_stats uwrs
                    LEFT JOIN user_website_reply_stats_daily uwrsd
                        ON uwrs.user_id = uwrsd.user_id
                        AND uwrs.website_id = uwrsd.website_id
                        AND uwrsd.stat_date = date('now','localtime')
                    WHERE uwrs.user_id = ?{website_filter_clause}
                ''', tuple(params))

                stats_map: Dict[int, Dict[str, int]] = {}
                for row in cursor.fetchall():
                    stats_map[row['website_id']] = {
                        'stat_replies_total': row['stat_replies_total'] or 0,
                        'stat_replies_text': row['stat_replies_text'] or 0,
                        'stat_replies_image': row['stat_replies_image'] or 0,
                        'stat_replies_daily_total': row['stat_replies_daily_total'] or 0,
                        'stat_replies_daily_text': row['stat_replies_daily_text'] or 0,
                        'stat_replies_daily_image': row['stat_replies_daily_image'] or 0,
                    }
                return stats_map
        except Exception as e:
            logger.error(f"获取用户网站回复统计失败: {e}")
            return {}

    def get_user_reply_stats(self, user_id: int) -> Dict[str, int]:
        """获取用户回复统计（累计 + 今日）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT stat_replies_total, stat_replies_text, stat_replies_image
                    FROM user_reply_stats
                    WHERE user_id = ?
                ''', (user_id,))
                total_row = cursor.fetchone()
                total_replies = total_row['stat_replies_total'] if total_row else 0

                cursor.execute('''
                    SELECT stat_replies_total, stat_replies_text, stat_replies_image
                    FROM user_reply_stats_daily
                    WHERE user_id = ? AND stat_date = date('now','localtime')
                ''', (user_id,))
                daily_row = cursor.fetchone()
                daily_replies = daily_row['stat_replies_total'] if daily_row else 0

                return {
                    'total_replies': total_replies or 0,
                    'daily_replies_total': daily_replies or 0
                }
        except Exception as e:
            logger.error(f"获取用户回复统计失败: {e}")
            return {
                'total_replies': 0,
                'daily_replies_total': 0
            }

    def add_website_config(self, name: str, display_name: str, url_template: str, id_pattern: str, badge_color: str = 'blue', reply_template: str = '{url}', reply_language: Any = None, image_similarity_threshold: float = None, blocked_role_ids: str = '[]', rotation_interval: int = 180, rotation_enabled: int = 1, message_filters: str = '[]') -> Tuple[bool, Optional[str]]:
        """添加网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                base_name = str(name or '').strip() or str(display_name or '').strip() or 'website'
                candidate_name = base_name
                suffix = 2
                serialized_reply_languages = json.dumps(
                    get_effective_reply_languages(reply_language),
                    ensure_ascii=False,
                )

                while True:
                    try:
                        cursor.execute('''
                            INSERT INTO website_configs (name, display_name, url_template, id_pattern, badge_color, reply_template, reply_language, image_similarity_threshold, blocked_role_ids, rotation_interval, rotation_enabled, message_filters)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (candidate_name, display_name, url_template, id_pattern, badge_color, reply_template, serialized_reply_languages, image_similarity_threshold, blocked_role_ids, rotation_interval, rotation_enabled, message_filters))
                        conn.commit()
                        return True, None
                    except sqlite3.IntegrityError as e:
                        error_text = str(e)
                        if 'website_configs.name' not in error_text and 'UNIQUE constraint failed' not in error_text:
                            raise
                        candidate_name = f"{base_name}-{suffix}"
                        suffix += 1
                        continue
        except Exception as e:
            logger.error(f"添加网站配置失败: {e}")
            return False, f"添加网站配置失败: {e}"

    def update_website_config(self, config_id: int, name: str, display_name: str, url_template: str, id_pattern: str, badge_color: str, reply_template: str, reply_language: Any = None, image_similarity_threshold: float = None, blocked_role_ids: str = '[]', rotation_interval: int = 180, rotation_enabled: int = 1, message_filters: str = '[]') -> Tuple[bool, Optional[str]]:
        """更新网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                serialized_reply_languages = json.dumps(
                    get_effective_reply_languages(reply_language),
                    ensure_ascii=False,
                )
                cursor.execute('''
                    UPDATE website_configs
                    SET name = ?, display_name = ?, url_template = ?, id_pattern = ?, badge_color = ?, reply_template = ?, reply_language = ?, image_similarity_threshold = ?, blocked_role_ids = ?, rotation_interval = ?, rotation_enabled = ?, message_filters = ?
                    WHERE id = ?
                ''', (name, display_name, url_template, id_pattern, badge_color, reply_template, serialized_reply_languages, image_similarity_threshold, blocked_role_ids, rotation_interval, rotation_enabled, message_filters, config_id))
                conn.commit()
                if cursor.rowcount > 0:
                    return True, None
                return False, f'网站配置 {config_id} 不存在'
        except sqlite3.IntegrityError as e:
            error_text = str(e)
            if 'website_configs.name' in error_text or 'UNIQUE constraint failed' in error_text:
                return False, '网站内部标识已存在，请修改显示名称后重试'
            logger.error(f"更新网站配置失败: {e}")
            return False, f"更新网站配置失败: {e}"
        except Exception as e:
            logger.error(f"更新网站配置失败: {e}")
            return False, f"更新网站配置失败: {e}"

    def delete_website_config(self, config_id: int) -> Tuple[bool, Optional[str]]:
        """删除网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM website_configs WHERE id = ?', (config_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    return True, None
                return False, f'网站配置 {config_id} 不存在'
        except Exception as e:
            logger.error(f"删除网站配置失败: {e}")
            return False, f"删除网站配置失败: {e}"

    def get_website_channel_bindings(self, website_id: int, user_id: int = None) -> List[str]:
        """获取网站绑定的频道列表（可选按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute('''
                        SELECT channel_id FROM website_channel_bindings
                        WHERE website_id = ? AND user_id = ?
                        ORDER BY created_at
                    ''', (website_id, user_id))
                else:
                    cursor.execute('''
                        SELECT channel_id FROM website_channel_bindings
                        WHERE website_id = ?
                        ORDER BY created_at
                    ''', (website_id,))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站频道绑定失败: {e}")
            return []

    def get_website_channel_bindings_details(self, website_id: int, user_id: int = None) -> List[Dict[str, Any]]:
        """获取网站绑定的频道详情（包含审核开关）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id is not None:
                    cursor.execute(
                        '''
                        SELECT id, website_id, channel_id, user_id, keyword_review_enabled, created_at
                        FROM website_channel_bindings
                        WHERE website_id = ? AND user_id = ?
                        ORDER BY created_at
                        ''',
                        (website_id, user_id),
                    )
                else:
                    cursor.execute(
                        '''
                        SELECT id, website_id, channel_id, user_id, keyword_review_enabled, created_at
                        FROM website_channel_bindings
                        WHERE website_id = ?
                        ORDER BY created_at
                        ''',
                        (website_id,),
                    )
                rows = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item['keyword_review_enabled'] = 1 if int(item.get('keyword_review_enabled') or 0) else 0
                    rows.append(item)
                return rows
        except Exception as e:
            logger.error(f"获取网站频道绑定详情失败: {e}")
            return []

    def get_website_channel_bindings_details_map(self, user_id: int) -> Dict[int, List[Dict[str, Any]]]:
        """批量获取用户的网站频道绑定详情"""
        bindings: Dict[int, List[Dict[str, Any]]] = {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT id, website_id, channel_id, user_id, keyword_review_enabled, created_at
                    FROM website_channel_bindings
                    WHERE user_id = ?
                    ORDER BY website_id, created_at
                    ''',
                    (user_id,),
                )
                for row in cursor.fetchall():
                    item = dict(row)
                    item['keyword_review_enabled'] = 1 if int(item.get('keyword_review_enabled') or 0) else 0
                    bindings.setdefault(item['website_id'], []).append(item)
        except Exception as e:
            logger.error(f"批量获取网站频道绑定详情失败: {e}")
        return bindings

    def get_website_channel_bindings_map(self, user_id: int) -> Dict[int, List[str]]:
        """批量获取用户的网站频道绑定，避免逐站点查询"""
        bindings: Dict[int, List[str]] = {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT website_id, channel_id
                    FROM website_channel_bindings
                    WHERE user_id = ?
                    ORDER BY website_id, created_at
                ''', (user_id,))
                for row in cursor.fetchall():
                    website_id = row['website_id']
                    bindings.setdefault(website_id, []).append(row['channel_id'])
        except Exception as e:
            logger.error(f"批量获取网站频道绑定失败: {e}")
        return bindings

    def add_website_channel_binding(self, website_id: int, channel_id: str, user_id: int) -> bool:
        """添加网站频道绑定"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO website_channel_bindings (website_id, channel_id, user_id)
                    VALUES (?, ?, ?)
                ''', (website_id, channel_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"添加网站频道绑定失败: {e}")
            return False

    def update_website_channel_binding_review_enabled(
        self,
        website_id: int,
        channel_id: str,
        user_id: int = None,
        enabled: bool = True,
    ) -> bool:
        """更新网站频道的关键词人工审核开关"""
        try:
            normalized_channel_id = str(channel_id or '').strip()
            if not normalized_channel_id:
                return False

            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id is None:
                    cursor.execute(
                        '''
                        UPDATE website_channel_bindings
                        SET keyword_review_enabled = ?
                        WHERE website_id = ?
                          AND channel_id = ?
                        ''',
                        (1 if enabled else 0, website_id, normalized_channel_id),
                    )
                else:
                    cursor.execute(
                        '''
                        UPDATE website_channel_bindings
                        SET keyword_review_enabled = ?
                        WHERE website_id = ?
                          AND channel_id = ?
                          AND user_id = ?
                        ''',
                        (1 if enabled else 0, website_id, normalized_channel_id, user_id),
                    )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站频道审核开关失败: {e}")
            return False

    def remove_website_channel_binding(self, website_id: int, channel_id: str, user_id: int) -> bool:
        """移除网站频道绑定（按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 【修复】兼容完整URL和频道ID两种格式
                # 如果传入的是频道ID，也要匹配数据库中可能存储的完整URL
                # 构造两种可能的匹配模式
                cursor.execute('''
                    DELETE FROM website_channel_bindings
                    WHERE website_id = ?
                    AND (
                        channel_id = ?
                        OR channel_id LIKE '%/' || ?
                        OR channel_id LIKE '%/' || ? || '/%'
                    )
                    AND (user_id = ? OR user_id IS NULL)
                ''', (website_id, channel_id, channel_id, channel_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"移除网站频道绑定失败: {e}")
            return False

    def remove_website_channel_binding_admin(self, website_id: int, channel_id: str) -> bool:
        """移除网站频道绑定（管理员权限，删除所有用户的绑定）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 【修复】兼容完整URL和频道ID两种格式
                cursor.execute('''
                    DELETE FROM website_channel_bindings
                    WHERE website_id = ?
                    AND (
                        channel_id = ?
                        OR channel_id LIKE '%/' || ?
                        OR channel_id LIKE '%/' || ? || '/%'
                    )
                ''', (website_id, channel_id, channel_id, channel_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"管理员移除网站频道绑定失败: {e}")
            return False

    def get_website_configs_by_channel(self, channel_id: Any, user_id: int = None) -> List[Dict]:
        """根据频道ID获取所有绑定的网站配置，支持线程回退到父频道"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if isinstance(channel_id, (list, tuple, set)):
                    lookup_ids = []
                    for item in channel_id:
                        normalized = str(item or '').strip()
                        if normalized and normalized not in lookup_ids:
                            lookup_ids.append(normalized)
                else:
                    normalized = str(channel_id or '').strip()
                    lookup_ids = [normalized] if normalized else []

                if not lookup_ids:
                    return []

                for lookup_id in lookup_ids:
                    if user_id:
                        cursor.execute('''
                        SELECT wc.id, wc.name, wc.display_name, wc.url_template, wc.id_pattern,
                                   wc.badge_color, wc.reply_template, wc.reply_language,
                                   COALESCE(uws.image_similarity_threshold, wc.image_similarity_threshold) as image_similarity_threshold,
                                   COALESCE(uws.keyword_match_limit, NULL) as keyword_match_limit,
                                   COALESCE(wcb.keyword_review_enabled, 0) as keyword_review_enabled,
                                   wc.blocked_role_ids, wc.rotation_interval, wc.rotation_enabled, wc.message_filters
                            FROM website_configs wc
                            JOIN website_channel_bindings wcb ON wc.id = wcb.website_id
                            LEFT JOIN user_website_settings uws
                                ON uws.website_id = wc.id AND uws.user_id = wcb.user_id
                            WHERE wcb.channel_id = ? AND wcb.user_id = ?
                            ORDER BY wcb.created_at, wc.created_at
                        ''', (lookup_id, user_id))
                    else:
                        cursor.execute('''
                        SELECT wc.id, wc.name, wc.display_name, wc.url_template, wc.id_pattern,
                                   wc.badge_color, wc.reply_template, wc.reply_language, wc.image_similarity_threshold, wc.blocked_role_ids,
                                   COALESCE(wcb.keyword_review_enabled, 0) as keyword_review_enabled,
                                   wc.rotation_interval, wc.rotation_enabled, wc.message_filters
                            FROM website_configs wc
                            JOIN website_channel_bindings wcb ON wc.id = wcb.website_id
                            WHERE wcb.channel_id = ?
                            ORDER BY wcb.created_at, wc.created_at
                        ''', (lookup_id,))

                    configs = []
                    for row in cursor.fetchall():
                        config = dict(row)
                        config['reply_language'] = get_effective_reply_languages(
                            config.get('reply_language')
                        )
                        configs.append(config)

                    if configs:
                        return configs

                return []
        except Exception as e:
            logger.error(f"根据频道获取网站配置失败: {e}")
            return []

    def get_website_config_by_channel(self, channel_id: str, user_id: int = None) -> Dict:
        """根据频道ID获取绑定的网站配置（兼容单个返回）"""
        configs = self.get_website_configs_by_channel(channel_id, user_id)
        return configs[0] if configs else None

    def get_all_bound_channel_ids(self) -> set:
        """【新增】高效获取所有已绑定的频道ID列表（用于Bot白名单缓存）

        返回所有已绑定的频道ID集合，包括:
        1. website_channel_bindings 表中的所有频道
        2. 系统配置中的 CNFANS_CHANNEL_ID 和 ACBUY_CHANNEL_ID

        Returns:
            set: 频道ID字符串集合，用于O(1)快速查找
        """
        try:
            channel_ids = set()

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 1. 从绑定表中获取所有频道ID
                cursor.execute('SELECT DISTINCT channel_id FROM website_channel_bindings')
                rows = cursor.fetchall()
                for row in rows:
                    channel_id = row[0]
                    if channel_id:
                        # 兼容完整URL格式，提取频道ID
                        if 'discord.com/channels/' in channel_id:
                            parts = channel_id.rstrip('/').split('/')
                            if len(parts) >= 1:
                                channel_id = parts[-1]
                        channel_ids.add(str(channel_id))

            # 2. 添加系统配置中的频道ID（兼容旧配置）
            try:
                from config import config
                if hasattr(config, 'CNFANS_CHANNEL_ID') and config.CNFANS_CHANNEL_ID:
                    channel_ids.add(str(config.CNFANS_CHANNEL_ID))
                if hasattr(config, 'ACBUY_CHANNEL_ID') and config.ACBUY_CHANNEL_ID:
                    channel_ids.add(str(config.ACBUY_CHANNEL_ID))
            except Exception as e:
                logger.debug(f"读取系统配置频道ID失败（可忽略）: {e}")

            logger.debug(f"获取到 {len(channel_ids)} 个已绑定的频道ID")
            return channel_ids

        except Exception as e:
            logger.error(f"获取已绑定频道ID列表失败: {e}")
            return set()

    def get_website_url_configs(self) -> List[Dict]:
        """获取生成商品跳转链接所需的网站模板配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name, display_name, url_template, badge_color
                    FROM website_configs
                    ORDER BY created_at
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站URL模板失败: {e}")
            return []

    def generate_website_urls(self, weidian_id: str, website_configs: Optional[List[Dict]] = None) -> List[Dict]:
        """根据微店ID生成所有网站的URL"""
        try:
            website_configs = website_configs if website_configs is not None else self.get_website_url_configs()
            urls = []

            for config in website_configs:
                try:
                    # 替换URL模板中的{id}占位符
                    url = config['url_template'].replace('{id}', weidian_id)
                    urls.append({
                        'name': config['name'],
                        'display_name': config['display_name'],
                        'url': url,
                        'badge_color': config['badge_color'],
                    })
                except Exception as e:
                    logger.warning(f"生成网站URL失败 {config['name']}: {e}")

            return urls
        except Exception as e:
            logger.error(f"生成网站URL失败: {e}")
            return []

    # ===== 网站账号绑定方法 =====

    def add_website_account_binding(self, website_id: int, account_id: int, role: str, user_id: int) -> bool:
        """添加网站账号绑定"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO website_account_bindings
                    (website_id, account_id, role, user_id)
                    VALUES (?, ?, ?, ?)
                ''', (website_id, account_id, role, user_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加网站账号绑定失败: {e}")
            return False

    @staticmethod
    def _normalize_account_binding_ids(account_ids: Sequence[Any]) -> List[int]:
        normalized_ids: List[int] = []
        for raw_id in account_ids or []:
            try:
                account_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if account_id <= 0 or account_id in normalized_ids:
                continue
            normalized_ids.append(account_id)
        return normalized_ids

    def add_website_account_bindings_auto(self, website_id: int, account_ids: Sequence[Any], user_id: int) -> List[Dict]:
        """自动为网站绑定账号。

        策略保持一个可监听账号，其余账号作为发送账号，以兼容现有监听/发送链路。
        """
        normalized_ids = self._normalize_account_binding_ids(account_ids)
        if not normalized_ids:
            return []

        try:
            existing_bindings = self.get_website_account_bindings(website_id, user_id)
            existing_by_account = {
                int(binding['account_id']): binding
                for binding in existing_bindings
            }
            has_listener = any(
                str(binding.get('role') or '').strip() in {'listener', 'both'}
                for binding in existing_bindings
            )

            with self.get_connection() as conn:
                cursor = conn.cursor()
                for account_id in normalized_ids:
                    existing_binding = existing_by_account.get(account_id)
                    assigned_role = (
                        str(existing_binding.get('role') or '').strip()
                        if existing_binding
                        else ''
                    )
                    if assigned_role not in {'listener', 'sender', 'both'}:
                        assigned_role = 'sender' if has_listener else 'both'

                    cursor.execute('''
                        INSERT INTO website_account_bindings
                        (website_id, account_id, role, user_id)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(website_id, account_id) DO UPDATE SET
                            role = excluded.role,
                            user_id = excluded.user_id
                    ''', (website_id, account_id, assigned_role, user_id))

                    if assigned_role in {'listener', 'both'}:
                        has_listener = True

                conn.commit()

            self.ensure_website_has_listener_binding(website_id, user_id)
            binding_map = {
                int(binding['account_id']): binding
                for binding in self.get_website_account_bindings(website_id, user_id)
            }
            return [
                binding_map[account_id]
                for account_id in normalized_ids
                if account_id in binding_map
            ]
        except Exception as e:
            logger.error(f"自动绑定网站账号失败: {e}")
            return []

    def ensure_website_has_listener_binding(self, website_id: int, user_id: int = None) -> Optional[int]:
        """确保网站至少存在一个可监听账号。

        当监听位为空时，自动提升最早绑定的 sender 为 both。
        """
        try:
            bindings = self.get_website_account_bindings(website_id, user_id)
            if not bindings:
                return None

            for binding in bindings:
                role = str(binding.get('role') or '').strip()
                if role in {'listener', 'both'}:
                    return int(binding['account_id'])

            promoted_binding = bindings[0]
            account_id = int(promoted_binding['account_id'])

            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id is not None:
                    cursor.execute('''
                        UPDATE website_account_bindings
                        SET role = 'both'
                        WHERE website_id = ? AND account_id = ? AND user_id = ?
                    ''', (website_id, account_id, user_id))
                else:
                    cursor.execute('''
                        UPDATE website_account_bindings
                        SET role = 'both'
                        WHERE website_id = ? AND account_id = ?
                    ''', (website_id, account_id))
                conn.commit()

            return account_id
        except Exception as e:
            logger.error(f"确保网站监听账号失败: {e}")
            return None

    def remove_website_account_binding(self, website_id: int, account_id: int, user_id: int) -> bool:
        """移除网站账号绑定（按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM website_account_bindings
                    WHERE website_id = ? AND account_id = ? AND (user_id = ? OR user_id IS NULL)
                ''', (website_id, account_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"移除网站账号绑定失败: {e}")
            return False

    def get_website_account_bindings(self, website_id: int, user_id: int = None) -> List[Dict]:
        """获取网站的所有账号绑定（可选按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute('''
                        SELECT wab.id, wab.account_id, wab.role, wab.created_at,
                               da.username, da.token, da.status
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ? AND wab.user_id = ?
                        ORDER BY wab.created_at
                    ''', (website_id, user_id))
                else:
                    cursor.execute('''
                        SELECT wab.id, wab.account_id, wab.role, wab.created_at,
                               da.username, da.token, da.status
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ?
                        ORDER BY wab.created_at
                    ''', (website_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站账号绑定失败: {e}")
            return []

    def get_website_account_bindings_map(self, user_id: int) -> Dict[int, List[Dict]]:
        """批量获取用户的网站账号绑定，避免逐站点查询"""
        bindings: Dict[int, List[Dict]] = {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT wab.website_id, wab.id, wab.account_id, wab.role, wab.created_at,
                           da.username, da.token, da.status
                    FROM website_account_bindings wab
                    JOIN discord_accounts da ON wab.account_id = da.id
                    WHERE wab.user_id = ?
                    ORDER BY wab.website_id, wab.created_at
                ''', (user_id,))
                for row in cursor.fetchall():
                    item = dict(row)
                    website_id = item.pop('website_id')
                    bindings.setdefault(website_id, []).append(item)
        except Exception as e:
            logger.error(f"批量获取网站账号绑定失败: {e}")
        return bindings

    def get_account_website_bindings(self, account_id: int) -> List[Dict]:
        """获取账号的所有网站绑定"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT wab.id, wab.website_id, wab.role, wab.created_at,
                           wc.name, wc.display_name
                    FROM website_account_bindings wab
                    JOIN website_configs wc ON wab.website_id = wc.id
                    WHERE wab.account_id = ?
                    ORDER BY wab.created_at
                ''', (account_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取账号网站绑定失败: {e}")
            return []

    def get_website_senders(self, website_id: int, user_id: int = None) -> List[int]:
        """获取网站的发送账号ID列表（可选按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute('''
                        SELECT wab.account_id
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ? AND wab.user_id = ? AND wab.role IN ('sender', 'both')
                    ''', (website_id, user_id))
                else:
                    cursor.execute('''
                        SELECT wab.account_id
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ? AND wab.role IN ('sender', 'both')
                    ''', (website_id,))
                return [row['account_id'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站发送账号失败: {e}")
            return []

    def get_website_listeners(self, website_id: int, user_id: int = None) -> List[int]:
        """获取网站的监听账号ID列表（可选按用户过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute('''
                        SELECT wab.account_id
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ? AND wab.user_id = ? AND wab.role IN ('listener', 'both')
                    ''', (website_id, user_id))
                else:
                    cursor.execute('''
                        SELECT wab.account_id
                        FROM website_account_bindings wab
                        JOIN discord_accounts da ON wab.account_id = da.id
                        WHERE wab.website_id = ? AND wab.role IN ('listener', 'both')
                    ''', (website_id,))
                return [row['account_id'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站监听账号失败: {e}")
            return []

    def update_website_config_rotation(self, config_id: int, rotation_interval: int) -> bool:
        """更新网站配置的轮换间隔"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE website_configs
                    SET rotation_interval = ?
                    WHERE id = ?
                ''', (rotation_interval, config_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站轮换间隔失败: {e}")
            return False

    def update_website_config_rotation_enabled(self, config_id: int, rotation_enabled: int) -> bool:
        """更新网站配置的轮换启用状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE website_configs
                    SET rotation_enabled = ?
                    WHERE id = ?
                ''', (rotation_enabled, config_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站配置轮换启用状态失败: {e}")
            return False

    def update_website_message_filters(self, config_id: int, message_filters: str) -> bool:
        """更新网站配置的消息过滤条件"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE website_configs
                    SET message_filters = ?
                    WHERE id = ?
                ''', (message_filters, config_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站消息过滤条件失败: {e}")
            return False

    def add_keyword_reply_review_item(self, item: Dict[str, Any]) -> int:
        """写入关键词回复人工审核队列"""
        try:
            payload = item.get('payload') or {}
            account_ids = item.get('account_ids') or []
            account_names = item.get('account_names') or []
            payload_json = json.dumps(payload, ensure_ascii=False)
            account_ids_json = json.dumps(account_ids, ensure_ascii=False)

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO keyword_reply_review_items (
                        user_id,
                        website_id,
                        channel_id,
                        guild_id,
                        guild_name,
                        channel_name,
                        account_ids_json,
                        account_names,
                        sender_id,
                        sender_name,
                        content,
                        source_content,
                        message_id,
                        reply_mode,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(item.get('user_id') or 0),
                        int(item.get('website_id') or 0),
                        str(item.get('channel_id') or ''),
                        str(item.get('guild_id') or ''),
                        str(item.get('guild_name') or ''),
                        str(item.get('channel_name') or ''),
                        account_ids_json,
                        ', '.join(str(name).strip() for name in account_names if str(name).strip()),
                        str(item.get('sender_id') or ''),
                        str(item.get('sender_name') or ''),
                        str(item.get('content') or ''),
                        str(item.get('source_content') or ''),
                        str(item.get('message_id') or ''),
                        str(item.get('reply_mode') or 'keyword'),
                        str(item.get('status') or 'pending'),
                        payload_json,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid or 0)
        except Exception as e:
            logger.error(f"写入关键词审核队列失败: {e}")
            return 0

    def _parse_keyword_reply_review_item_row(self, row: Any) -> Dict[str, Any]:
        item = dict(row)
        try:
            item['payload'] = json.loads(item.get('payload_json') or '{}')
        except Exception:
            item['payload'] = {}
        try:
            item['account_ids'] = json.loads(item.get('account_ids_json') or '[]')
        except Exception:
            item['account_ids'] = []
        item['keyword_review_enabled'] = 1 if int(item.get('keyword_review_enabled') or 0) else 0
        return item

    def get_keyword_reply_review_item(self, item_id: int, user_id: int = None) -> Optional[Dict[str, Any]]:
        """获取单条关键词审核队列记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT *
                    FROM keyword_reply_review_items
                    WHERE id = ?
                '''
                params: List[Any] = [item_id]
                if user_id is not None:
                    query += ' AND user_id = ?'
                    params.append(user_id)
                cursor.execute(query, params)
                row = cursor.fetchone()
                return self._parse_keyword_reply_review_item_row(row) if row else None
        except Exception as e:
            logger.error(f"获取关键词审核队列记录失败: {e}")
            return None

    def get_keyword_reply_review_items(
        self,
        user_id: int,
        website_id: int = None,
        status: str = 'pending',
    ) -> List[Dict[str, Any]]:
        """获取关键词审核队列列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT *
                    FROM keyword_reply_review_items
                    WHERE user_id = ?
                '''
                params: List[Any] = [user_id]
                if website_id is not None:
                    query += ' AND website_id = ?'
                    params.append(website_id)
                if status is not None:
                    query += ' AND status = ?'
                    params.append(status)
                query += ' ORDER BY created_at DESC, id DESC'
                cursor.execute(query, params)
                return [self._parse_keyword_reply_review_item_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取关键词审核队列列表失败: {e}")
            return []

    def update_keyword_reply_review_item_status(
        self,
        item_id: int,
        status: str,
        reviewed_by_user_id: int = None,
        error_message: str = None,
    ) -> bool:
        """更新关键词审核队列状态"""
        try:
            normalized_status = str(status or '').strip().lower()
            if not normalized_status:
                return False

            with self.get_connection() as conn:
                cursor = conn.cursor()
                updates = ['status = ?', 'updated_at = CURRENT_TIMESTAMP']
                params: List[Any] = [normalized_status]
                if reviewed_by_user_id is not None:
                    updates.append('reviewed_by_user_id = ?')
                    params.append(reviewed_by_user_id)
                if error_message is not None:
                    updates.append('error_message = ?')
                    params.append(str(error_message))
                if normalized_status in {'approved', 'rejected'}:
                    updates.append('reviewed_at = CURRENT_TIMESTAMP')
                if normalized_status in {'sent', 'failed'}:
                    updates.append('sent_at = CURRENT_TIMESTAMP')
                params.append(item_id)
                cursor.execute(
                    f'''
                    UPDATE keyword_reply_review_items
                    SET {', '.join(updates)}
                    WHERE id = ?
                    ''',
                    params,
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新关键词审核队列状态失败: {e}")
            return False

    # ===== 用户级别的网站设置方法 =====

    def _default_user_website_settings(self) -> Dict[str, Any]:
        return {
            'rotation_interval': 180,
            'rotation_enabled': 1,
            'reply_mode': 'rotation',
            'keyword_reply_interval': 180,
            'keyword_reply_batch_size': 0,
            'keyword_batch_dispatch_mode': 'immediate',
            'thread_reply_enabled': 0,
            'forum_post_reply_enabled': 0,
            'keyword_match_limit': None,
            'keyword_image_search_enabled': 0,
            'keyword_image_search_mode': 'manual',
            'keyword_image_search_max_images': 3,
            'message_filters': '[]',
            'image_similarity_threshold': None,
            'reply_min_delay': None,
            'reply_max_delay': None,
        }

    def _normalize_user_website_settings_row(self, row: Any) -> Dict[str, Any]:
        if not row:
            return self._default_user_website_settings()

        raw_rotation_interval = row['rotation_interval']
        reply_mode = row['reply_mode']
        if reply_mode not in {'default', 'rotation', 'keyword', 'all'}:
            reply_mode = 'keyword' if (row['rotation_enabled'] == 0 and (row['keyword_reply_batch_size'] or 0) > 0) else 'rotation'
        if raw_rotation_interval is None:
            rotation_interval = 180
        else:
            try:
                rotation_interval = int(raw_rotation_interval)
            except (TypeError, ValueError):
                rotation_interval = 180
        if reply_mode != 'all' and rotation_interval <= 0:
            rotation_interval = 180

        raw_keyword_reply_interval = row['keyword_reply_interval']
        if raw_keyword_reply_interval is None:
            keyword_reply_interval = rotation_interval if rotation_interval > 0 else 180
        else:
            try:
                keyword_reply_interval = int(raw_keyword_reply_interval)
            except (TypeError, ValueError):
                keyword_reply_interval = rotation_interval if rotation_interval > 0 else 180
        if keyword_reply_interval <= 0:
            keyword_reply_interval = rotation_interval if rotation_interval > 0 else 180

        keyword_batch_dispatch_mode = (row['keyword_batch_dispatch_mode'] or 'immediate').strip().lower()
        if keyword_batch_dispatch_mode not in {'immediate', 'window_end'}:
            keyword_batch_dispatch_mode = 'immediate'
        keyword_image_search_mode = str(
            row['keyword_image_search_mode'] or 'manual'
        ).strip().lower()
        if keyword_image_search_mode not in {'manual', 'auto'}:
            keyword_image_search_mode = 'manual'
        try:
            keyword_image_search_max_images = int(row['keyword_image_search_max_images'] or 3)
        except (TypeError, ValueError):
            keyword_image_search_max_images = 3
        keyword_image_search_max_images = max(1, min(keyword_image_search_max_images, 10))

        return {
            'rotation_interval': rotation_interval,
            'rotation_enabled': row['rotation_enabled'],
            'reply_mode': reply_mode,
            'keyword_reply_interval': keyword_reply_interval,
            'keyword_reply_batch_size': row['keyword_reply_batch_size'] or 0,
            'keyword_batch_dispatch_mode': keyword_batch_dispatch_mode,
            'thread_reply_enabled': 1 if int(row['thread_reply_enabled'] or 0) else 0,
            'forum_post_reply_enabled': 1 if int(row['forum_post_reply_enabled'] or 0) else 0,
            'keyword_match_limit': row['keyword_match_limit'],
            'keyword_image_search_enabled': 1 if int(row['keyword_image_search_enabled'] or 0) else 0,
            'keyword_image_search_mode': keyword_image_search_mode,
            'keyword_image_search_max_images': keyword_image_search_max_images,
            'message_filters': row['message_filters'],
            'image_similarity_threshold': row['image_similarity_threshold'],
            'reply_min_delay': row['reply_min_delay'],
            'reply_max_delay': row['reply_max_delay'],
        }

    def get_user_website_settings(self, user_id: int, website_id: int) -> Dict:
        """获取用户的网站设置（轮换和过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT rotation_interval, rotation_enabled, reply_mode, keyword_reply_interval, keyword_reply_batch_size,
                           keyword_batch_dispatch_mode, thread_reply_enabled, forum_post_reply_enabled,
                           keyword_match_limit, keyword_image_search_enabled, keyword_image_search_mode,
                           keyword_image_search_max_images, message_filters,
                           image_similarity_threshold, reply_min_delay, reply_max_delay
                    FROM user_website_settings
                    WHERE user_id = ? AND website_id = ?
                ''', (user_id, website_id))
                return self._normalize_user_website_settings_row(cursor.fetchone())
        except Exception as e:
            logger.error(f"获取用户网站设置失败: {e}")
            return self._default_user_website_settings()

    def get_user_website_settings_map(self, user_id: int, website_ids: Optional[List[int]] = None) -> Dict[int, Dict[str, Any]]:
        """批量获取用户的网站设置，避免逐站点查询"""
        settings_map: Dict[int, Dict[str, Any]] = {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                params: List[Any] = [user_id]
                query = '''
                    SELECT website_id, rotation_interval, rotation_enabled, reply_mode, keyword_reply_interval,
                           keyword_reply_batch_size, keyword_batch_dispatch_mode, thread_reply_enabled,
                           forum_post_reply_enabled,
                           keyword_match_limit, keyword_image_search_enabled, keyword_image_search_mode,
                           keyword_image_search_max_images, message_filters, image_similarity_threshold,
                           reply_min_delay, reply_max_delay
                    FROM user_website_settings
                    WHERE user_id = ?
                '''
                if website_ids:
                    placeholders = ','.join('?' * len(website_ids))
                    query += f' AND website_id IN ({placeholders})'
                    params.extend(website_ids)
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    settings_map[row['website_id']] = self._normalize_user_website_settings_row(row)
        except Exception as e:
            logger.error(f"批量获取用户网站设置失败: {e}")
        return settings_map

    def update_user_website_similarity(self, user_id: int, website_id: int, threshold: float = None) -> bool:
        """更新用户的网站图片相似度阈值"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_website_settings (user_id, website_id, image_similarity_threshold)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, website_id) DO UPDATE SET
                        image_similarity_threshold = excluded.image_similarity_threshold,
                        updated_at = CURRENT_TIMESTAMP
                ''', (user_id, website_id, threshold))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户网站相似度阈值失败: {e}")
            return False

    def update_user_website_reply_delay(self, user_id: int, website_id: int, min_delay: float = None, max_delay: float = None) -> bool:
        """更新用户的网站回复延迟覆盖"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_website_settings (user_id, website_id, reply_min_delay, reply_max_delay)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, website_id) DO UPDATE SET
                        reply_min_delay = excluded.reply_min_delay,
                        reply_max_delay = excluded.reply_max_delay,
                        updated_at = CURRENT_TIMESTAMP
                ''', (user_id, website_id, min_delay, max_delay))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户网站回复延迟失败: {e}")
            return False

    def update_user_website_keyword_match_limit(self, user_id: int, website_id: int, keyword_match_limit: int = None) -> bool:
        """更新用户的网站关键词命中上限覆盖"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_website_settings (user_id, website_id, keyword_match_limit)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, website_id) DO UPDATE SET
                        keyword_match_limit = excluded.keyword_match_limit,
                        updated_at = CURRENT_TIMESTAMP
                ''', (user_id, website_id, keyword_match_limit))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户网站关键词命中上限失败: {e}")
            return False

    def update_user_website_rotation(
        self,
        user_id: int,
        website_id: int,
        rotation_interval: int = None,
        rotation_enabled: int = None,
        reply_mode: str = None,
        keyword_reply_interval: int = None,
        keyword_reply_batch_size: int = None,
        keyword_batch_dispatch_mode: str = None,
        thread_reply_enabled: int = None,
        forum_post_reply_enabled: int = None,
        keyword_match_limit: int = None,
        keyword_image_search_enabled: int = None,
        keyword_image_search_mode: str = None,
        keyword_image_search_max_images: int = None,
    ) -> bool:
        """更新用户的网站轮换设置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                normalized_reply_mode = reply_mode if reply_mode in {'default', 'rotation', 'keyword', 'all'} else None
                normalized_keyword_batch_dispatch_mode = (
                    keyword_batch_dispatch_mode
                    if keyword_batch_dispatch_mode in {'immediate', 'window_end'}
                    else None
                )
                normalized_thread_reply_enabled = None
                if thread_reply_enabled is not None:
                    normalized_thread_reply_enabled = 1 if int(thread_reply_enabled) else 0
                normalized_forum_post_reply_enabled = None
                if forum_post_reply_enabled is not None:
                    normalized_forum_post_reply_enabled = 1 if int(forum_post_reply_enabled) else 0
                normalized_keyword_image_search_enabled = None
                if keyword_image_search_enabled is not None:
                    normalized_keyword_image_search_enabled = 1 if int(keyword_image_search_enabled) else 0
                normalized_keyword_image_search_mode = None
                if keyword_image_search_mode is not None:
                    candidate_mode = str(keyword_image_search_mode).strip().lower()
                    if candidate_mode in {'manual', 'auto'}:
                        normalized_keyword_image_search_mode = candidate_mode
                normalized_keyword_image_search_max_images = None
                if keyword_image_search_max_images is not None:
                    try:
                        normalized_keyword_image_search_max_images = int(keyword_image_search_max_images)
                    except (TypeError, ValueError):
                        normalized_keyword_image_search_max_images = 3
                    normalized_keyword_image_search_max_images = max(
                        1,
                        min(normalized_keyword_image_search_max_images, 10),
                    )
                if normalized_reply_mode is None:
                    if rotation_enabled == 0 and (keyword_reply_batch_size or 0) > 0:
                        normalized_reply_mode = 'keyword'
                    elif rotation_enabled is not None:
                        normalized_reply_mode = 'rotation'

                normalized_rotation_enabled = rotation_enabled
                if normalized_reply_mode == 'keyword':
                    normalized_rotation_enabled = 0
                elif normalized_reply_mode == 'all':
                    normalized_rotation_enabled = 0
                elif normalized_reply_mode == 'default':
                    normalized_rotation_enabled = 0
                elif normalized_reply_mode == 'rotation' and normalized_rotation_enabled is None:
                    normalized_rotation_enabled = 1

                # 先检查是否存在记录
                cursor.execute('''
                    SELECT id FROM user_website_settings WHERE user_id = ? AND website_id = ?
                ''', (user_id, website_id))
                exists = cursor.fetchone()

                if exists:
                    # 更新现有记录
                    updates = []
                    params = []
                    if rotation_interval is not None:
                        updates.append('rotation_interval = ?')
                        params.append(rotation_interval)
                    if normalized_rotation_enabled is not None:
                        updates.append('rotation_enabled = ?')
                        params.append(normalized_rotation_enabled)
                    if normalized_reply_mode is not None:
                        updates.append('reply_mode = ?')
                        params.append(normalized_reply_mode)
                    if keyword_reply_interval is not None:
                        updates.append('keyword_reply_interval = ?')
                        params.append(keyword_reply_interval)
                    if keyword_reply_batch_size is not None:
                        updates.append('keyword_reply_batch_size = ?')
                        params.append(keyword_reply_batch_size)
                    if normalized_keyword_batch_dispatch_mode is not None:
                        updates.append('keyword_batch_dispatch_mode = ?')
                        params.append(normalized_keyword_batch_dispatch_mode)
                    if normalized_thread_reply_enabled is not None:
                        updates.append('thread_reply_enabled = ?')
                        params.append(normalized_thread_reply_enabled)
                    if normalized_forum_post_reply_enabled is not None:
                        updates.append('forum_post_reply_enabled = ?')
                        params.append(normalized_forum_post_reply_enabled)
                    if keyword_match_limit is not None:
                        updates.append('keyword_match_limit = ?')
                        params.append(keyword_match_limit)
                    if normalized_keyword_image_search_enabled is not None:
                        updates.append('keyword_image_search_enabled = ?')
                        params.append(normalized_keyword_image_search_enabled)
                    if normalized_keyword_image_search_mode is not None:
                        updates.append('keyword_image_search_mode = ?')
                        params.append(normalized_keyword_image_search_mode)
                    if normalized_keyword_image_search_max_images is not None:
                        updates.append('keyword_image_search_max_images = ?')
                        params.append(normalized_keyword_image_search_max_images)
                    if updates:
                        updates.append('updated_at = CURRENT_TIMESTAMP')
                        params.extend([user_id, website_id])
                        cursor.execute(f'''
                            UPDATE user_website_settings
                            SET {', '.join(updates)}
                            WHERE user_id = ? AND website_id = ?
                        ''', params)
                else:
                    # 插入新记录
                    cursor.execute('''
                        INSERT INTO user_website_settings (
                            user_id,
                            website_id,
                            rotation_interval,
                            rotation_enabled,
                            reply_mode,
                            keyword_reply_interval,
                            keyword_reply_batch_size,
                            keyword_batch_dispatch_mode,
                            thread_reply_enabled,
                            forum_post_reply_enabled,
                            keyword_match_limit,
                            keyword_image_search_enabled,
                            keyword_image_search_mode,
                            keyword_image_search_max_images
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        user_id,
                        website_id,
                        rotation_interval if rotation_interval is not None else 180,
                        normalized_rotation_enabled if normalized_rotation_enabled is not None else 1,
                        normalized_reply_mode or 'rotation',
                        keyword_reply_interval if keyword_reply_interval is not None else (
                            rotation_interval if rotation_interval is not None and rotation_interval > 0 else 180
                        ),
                        keyword_reply_batch_size if keyword_reply_batch_size is not None else 0,
                        normalized_keyword_batch_dispatch_mode or 'immediate',
                        normalized_thread_reply_enabled if normalized_thread_reply_enabled is not None else 0,
                        normalized_forum_post_reply_enabled if normalized_forum_post_reply_enabled is not None else 0,
                        keyword_match_limit,
                        normalized_keyword_image_search_enabled if normalized_keyword_image_search_enabled is not None else 0,
                        normalized_keyword_image_search_mode or 'manual',
                        normalized_keyword_image_search_max_images if normalized_keyword_image_search_max_images is not None else 3,
                    ))

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户网站轮换设置失败: {e}")
            return False

    @staticmethod
    def _normalize_keyword_image_search_job_status(value: Any) -> str:
        candidate = str(value or 'pending').strip().lower()
        if candidate in {'pending', 'ready', 'sent', 'no_match', 'failed'}:
            return candidate
        return 'pending'

    @staticmethod
    def _normalize_keyword_image_search_job_mode(value: Any) -> str:
        candidate = str(value or 'manual').strip().lower()
        if candidate in {'manual', 'auto'}:
            return candidate
        return 'manual'

    @staticmethod
    def _parse_keyword_image_search_candidates(raw_value: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_value, list):
            return [item for item in raw_value if isinstance(item, dict)]
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    def _normalize_keyword_image_search_job_row(self, row: Any) -> Optional[Dict[str, Any]]:
        if not row:
            return None

        payload = dict(row)
        payload['mode'] = self._normalize_keyword_image_search_job_mode(payload.get('mode'))
        payload['status'] = self._normalize_keyword_image_search_job_status(payload.get('status'))
        payload['candidates'] = self._parse_keyword_image_search_candidates(
            payload.get('candidates_json')
        )
        payload.pop('candidates_json', None)
        payload['external_result_count'] = int(payload.get('external_result_count') or 0)
        payload['matched_result_count'] = int(payload.get('matched_result_count') or 0)
        return payload

    def create_keyword_image_search_job(
        self,
        *,
        user_id: int,
        website_id: int,
        query_text: str,
        channel_id: str,
        message_id: str,
        guild_id: Optional[str] = None,
        author_id: Optional[str] = None,
        mode: str = 'manual',
        provider: str = 'searchapi_google_images',
        status: str = 'pending',
        error_message: Optional[str] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        external_result_count: int = 0,
        matched_result_count: int = 0,
    ) -> Optional[int]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO keyword_image_search_jobs (
                        user_id,
                        website_id,
                        query_text,
                        channel_id,
                        message_id,
                        guild_id,
                        author_id,
                        mode,
                        provider,
                        status,
                        error_message,
                        external_result_count,
                        matched_result_count,
                        candidates_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(user_id),
                        int(website_id),
                        str(query_text or '').strip(),
                        str(channel_id or ''),
                        str(message_id or ''),
                        str(guild_id) if guild_id is not None else None,
                        str(author_id) if author_id is not None else None,
                        self._normalize_keyword_image_search_job_mode(mode),
                        str(provider or 'searchapi_google_images').strip() or 'searchapi_google_images',
                        self._normalize_keyword_image_search_job_status(status),
                        error_message,
                        max(0, int(external_result_count or 0)),
                        max(0, int(matched_result_count or 0)),
                        json.dumps(candidates or [], ensure_ascii=False),
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"创建关键词搜图任务失败: {e}")
            return None

    def get_keyword_image_search_job(
        self,
        job_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                user_scope_sql = ' AND kij.user_id = ?' if user_id is not None else ''
                params: List[Any] = [job_id]
                if user_id is not None:
                    params.append(user_id)
                cursor.execute(
                    f'''
                    SELECT
                        kij.*,
                        wc.display_name AS website_display_name,
                        wc.name AS website_name
                    FROM keyword_image_search_jobs kij
                    LEFT JOIN website_configs wc ON wc.id = kij.website_id
                    WHERE kij.id = ?{user_scope_sql}
                    ''',
                    params,
                )
                return self._normalize_keyword_image_search_job_row(cursor.fetchone())
        except Exception as e:
            logger.error(f"获取关键词搜图任务失败: {e}")
            return None

    def list_keyword_image_search_jobs(
        self,
        user_id: int,
        *,
        website_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        try:
            normalized_limit = max(1, min(int(limit or 50), 200))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT
                        kij.*,
                        wc.display_name AS website_display_name,
                        wc.name AS website_name
                    FROM keyword_image_search_jobs kij
                    LEFT JOIN website_configs wc ON wc.id = kij.website_id
                    WHERE kij.user_id = ?
                '''
                params: List[Any] = [user_id]
                if website_id:
                    query += ' AND kij.website_id = ?'
                    params.append(website_id)
                if status:
                    query += ' AND kij.status = ?'
                    params.append(self._normalize_keyword_image_search_job_status(status))
                query += ' ORDER BY kij.created_at DESC, kij.id DESC LIMIT ?'
                params.append(normalized_limit)
                cursor.execute(query, params)
                return [
                    job
                    for job in (
                        self._normalize_keyword_image_search_job_row(row)
                        for row in cursor.fetchall()
                    )
                    if job is not None
                ]
        except Exception as e:
            logger.error(f"列出关键词搜图任务失败: {e}")
            return []

    def update_keyword_image_search_job(
        self,
        job_id: int,
        *,
        user_id: Optional[int] = None,
        **updates: Any,
    ) -> bool:
        try:
            update_pairs: List[str] = []
            params: List[Any] = []
            for field, value in updates.items():
                if value is None and field not in {'error_message', 'selected_candidate_index', 'sent_product_id'}:
                    continue
                if field == 'status':
                    update_pairs.append('status = ?')
                    params.append(self._normalize_keyword_image_search_job_status(value))
                elif field == 'mode':
                    update_pairs.append('mode = ?')
                    params.append(self._normalize_keyword_image_search_job_mode(value))
                elif field == 'candidates':
                    update_pairs.append('candidates_json = ?')
                    params.append(json.dumps(value or [], ensure_ascii=False))
                elif field in {
                    'error_message',
                    'selected_candidate_index',
                    'sent_product_id',
                    'external_result_count',
                    'matched_result_count',
                    'provider',
                }:
                    update_pairs.append(f'{field} = ?')
                    params.append(value)

            if not update_pairs:
                return False

            update_pairs.append('updated_at = CURRENT_TIMESTAMP')
            user_scope_sql = ' AND user_id = ?' if user_id is not None else ''
            params.append(job_id)
            if user_id is not None:
                params.append(user_id)

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f'''
                    UPDATE keyword_image_search_jobs
                    SET {', '.join(update_pairs)}
                    WHERE id = ?{user_scope_sql}
                    ''',
                    params,
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新关键词搜图任务失败: {e}")
            return False

    def update_user_website_filters(self, user_id: int, website_id: int, message_filters: str) -> bool:
        """更新用户的网站消息过滤设置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 使用 INSERT OR REPLACE
                cursor.execute('''
                    INSERT INTO user_website_settings (user_id, website_id, message_filters)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, website_id) DO UPDATE SET
                        message_filters = excluded.message_filters,
                        updated_at = CURRENT_TIMESTAMP
                ''', (user_id, website_id, message_filters))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户网站消息过滤失败: {e}")
            return False

    def get_system_stats(self, user_id: int = None, role: str = 'user') -> Dict:
        """获取系统统计信息 (支持权限隔离)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 1. 统计店铺
                if role == 'admin' or user_id is None:
                    cursor.execute("SELECT COUNT(*), GROUP_CONCAT(name) FROM shops")
                else:
                    cursor.execute("""
                        SELECT COUNT(*), GROUP_CONCAT(s.name)
                        FROM shops s
                        JOIN user_shop_permissions usp ON s.shop_id = usp.shop_id
                        WHERE usp.user_id = ?
                    """, (user_id,))

                shop_result = cursor.fetchone()
                shop_count = shop_result[0] or 0
                shop_names_str = shop_result[1]
                shop_names = shop_names_str.split(',') if shop_names_str else []

                if role == 'admin' or user_id is None:
                    cursor.execute("SELECT COALESCE(SUM(stat_replies_total), 0) FROM website_configs")
                    total_replies = cursor.fetchone()[0] or 0
                    cursor.execute("""
                        SELECT COALESCE(SUM(stat_replies_total), 0)
                        FROM website_reply_stats_daily
                        WHERE stat_date = date('now','localtime')
                    """)
                    daily_replies = cursor.fetchone()[0] or 0
                else:
                    cursor.execute('''
                        SELECT stat_replies_total
                        FROM user_reply_stats
                        WHERE user_id = ?
                    ''', (user_id,))
                    total_row = cursor.fetchone()
                    total_replies = total_row[0] if total_row else 0
                    cursor.execute('''
                        SELECT stat_replies_total
                        FROM user_reply_stats_daily
                        WHERE user_id = ? AND stat_date = date('now','localtime')
                    ''', (user_id,))
                    daily_row = cursor.fetchone()
                    daily_replies = daily_row[0] if daily_row else 0

                if shop_count == 0 and role != 'admin':
                    return {
                        'shop_count': 0,
                        'product_count': 0,
                        'image_count': 0,
                        'user_count': 0,
                        'total_replies': total_replies,
                        'daily_replies_total': daily_replies
                    }

                # 2. 统计商品
                if role == 'admin' or user_id is None:
                    cursor.execute("SELECT COUNT(*) FROM products")
                    product_count = cursor.fetchone()[0] or 0
                else:
                    placeholders = ','.join('?' * len(shop_names))
                    query = f"SELECT COUNT(*) FROM products WHERE shop_name IN ({placeholders})"
                    cursor.execute(query, shop_names)
                    product_count = cursor.fetchone()[0] or 0

                # 3. 统计图片
                if role == 'admin' or user_id is None:
                    cursor.execute("SELECT COUNT(*) FROM product_images")
                    image_count = cursor.fetchone()[0] or 0
                else:
                    placeholders = ','.join('?' * len(shop_names))
                    query = f"""
                        SELECT COUNT(*) FROM product_images pi
                        JOIN products p ON pi.product_id = p.id
                        WHERE p.shop_name IN ({placeholders})
                    """
                    cursor.execute(query, shop_names)
                    image_count = cursor.fetchone()[0] or 0

                # 4. 统计用户
                if role == 'admin' or user_id is None:
                    cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
                    user_count = cursor.fetchone()[0] or 0
                else:
                    user_count = 1

                return {
                    'shop_count': shop_count,
                    'product_count': product_count,
                    'image_count': image_count,
                    'user_count': user_count,
                    'total_replies': total_replies,
                    'daily_replies_total': daily_replies
                }
        except Exception as e:
            logger.error(f"获取系统统计信息失败: {e}")
            return {
                'shop_count': 0,
                'product_count': 0,
                'image_count': 0,
                'user_count': 0,
                'total_replies': 0,
                'daily_replies_total': 0
            }

    def cleanup_orphaned_images(self) -> int:
        """清理孤立的图片记录（没有对应商品的图片）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 删除没有对应商品的图片记录
                cursor.execute("""
                    DELETE FROM product_images
                    WHERE product_id NOT IN (SELECT id FROM products)
                """)
                deleted_count = cursor.rowcount
                conn.commit()
                if deleted_count > 0:
                    logger.info(f"清理了 {deleted_count} 条孤立的图片记录")
                return deleted_count
        except Exception as e:
            logger.error(f"清理孤立图片记录失败: {e}")
            return 0

    def get_active_announcements(self) -> List[Dict]:
        """获取活跃的系统公告"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, content, created_at, updated_at
                    FROM system_announcements
                    WHERE is_active = 1
                    ORDER BY updated_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取系统公告失败: {e}")
            return []

    def create_announcement(self, title: str, content: str) -> bool:
        """创建系统公告"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO system_announcements (title, content)
                    VALUES (?, ?)
                ''', (title, content))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"创建系统公告失败: {e}")
            return False

    def update_announcement(self, announcement_id: int, title: str, content: str, is_active: bool) -> bool:
        """更新系统公告"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE system_announcements
                    SET title = ?, content = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (title, content, is_active, announcement_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新系统公告失败: {e}")
            return False

    def delete_announcement(self, announcement_id: int) -> bool:
        """删除系统公告"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM system_announcements WHERE id = ?', (announcement_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除系统公告失败: {e}")
            return False

    def get_message_filters(self) -> List[Dict]:
        """获取消息过滤规则"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, filter_type, filter_value, is_active, created_at
                    FROM message_filters
                    WHERE is_active = 1
                    ORDER BY created_at
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取消息过滤规则失败: {e}")
            return []

    def add_message_filter(self, filter_type: str, filter_value: str) -> int:
        """添加消息过滤规则"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO message_filters (filter_type, filter_value)
                    VALUES (?, ?)
                ''', (filter_type, filter_value))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"添加消息过滤规则失败: {e}")
            return 0

    def update_message_filter(self, filter_id: int, filter_type: str, filter_value: str, is_active: bool) -> bool:
        """更新消息过滤规则"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE message_filters
                    SET filter_type = ?, filter_value = ?, is_active = ?
                    WHERE id = ?
                ''', (filter_type, filter_value, is_active, filter_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新消息过滤规则失败: {e}")
            return False

    def delete_message_filter(self, filter_id: int) -> bool:
        """删除消息过滤规则"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM message_filters WHERE id = ?', (filter_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除消息过滤规则失败: {e}")
            return False

    def upsert_message_filter_blocked_user(
        self,
        filter_id: int,
        discord_user_id: str,
        discord_username: str = '',
        trigger_keyword: str = '',
    ) -> bool:
        try:
            normalized_discord_user_id = str(discord_user_id or '').strip()
            if not normalized_discord_user_id:
                return False

            normalized_username = str(discord_username or '').strip()
            normalized_trigger_keyword = str(trigger_keyword or '').strip()

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO message_filter_blocked_users (
                        filter_id,
                        discord_user_id,
                        discord_username,
                        trigger_keyword
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(filter_id, discord_user_id) DO UPDATE SET
                        discord_username = excluded.discord_username,
                        trigger_keyword = excluded.trigger_keyword,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        filter_id,
                        normalized_discord_user_id,
                        normalized_username,
                        normalized_trigger_keyword,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"写入全局拉黑用户失败: {e}")
            return False

    def get_message_filter_blocked_users(self, filter_id: int) -> List[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT
                        id,
                        filter_id,
                        discord_user_id,
                        discord_username,
                        trigger_keyword,
                        created_at,
                        updated_at
                    FROM message_filter_blocked_users
                    WHERE filter_id = ?
                    ORDER BY updated_at DESC, id DESC
                    ''',
                    (filter_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取全局拉黑用户失败: {e}")
            return []

    def delete_message_filter_blocked_user(self, filter_id: int, discord_user_id: str) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    DELETE FROM message_filter_blocked_users
                    WHERE filter_id = ? AND discord_user_id = ?
                    ''',
                    (filter_id, str(discord_user_id or '').strip()),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除全局拉黑用户失败: {e}")
            return False

    def get_blocked_message_filter_ids_for_discord_user(
        self,
        *,
        discord_user_id: str,
        candidate_filter_ids: Optional[Sequence[int]] = None,
    ) -> set[int]:
        try:
            normalized_discord_user_id = str(discord_user_id or '').strip()
            if not normalized_discord_user_id:
                return set()

            filter_ids: Optional[List[int]] = None
            if candidate_filter_ids is not None:
                filter_ids = [
                    int(filter_id)
                    for filter_id in candidate_filter_ids
                    if filter_id is not None and str(filter_id).strip()
                ]
                if not filter_ids:
                    return set()

            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT filter_id
                    FROM message_filter_blocked_users
                    WHERE discord_user_id = ?
                '''
                params: List[Any] = [normalized_discord_user_id]
                if filter_ids is not None:
                    placeholders = ','.join('?' * len(filter_ids))
                    query += f' AND filter_id IN ({placeholders})'
                    params.extend(filter_ids)
                cursor.execute(query, params)
                return {
                    int(row['filter_id'])
                    for row in cursor.fetchall()
                    if row['filter_id'] is not None
                }
        except Exception as e:
            logger.error(f"获取用户命中全局拉黑列表失败: {e}")
            return set()

    def add_message_filter_image(self, filter_id: int, image_path: str, features: np.ndarray) -> int:
        """添加消息过滤图片，返回记录ID"""
        try:
            features_str = None
            if features is not None:
                import json
                features_str = json.dumps(features.tolist())
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO message_filter_images (filter_id, image_path, features)
                    VALUES (?, ?, ?)
                ''', (filter_id, image_path, features_str))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"添加过滤图片失败: {e}")
            raise e

    def get_message_filter_images(self, filter_id: int, include_features: bool = False) -> List[Dict]:
        """获取某条过滤规则的图片列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if include_features:
                    cursor.execute('''
                        SELECT id, image_path, features, created_at
                        FROM message_filter_images
                        WHERE filter_id = ?
                        ORDER BY created_at DESC
                    ''', (filter_id,))
                else:
                    cursor.execute('''
                        SELECT id, image_path, created_at
                        FROM message_filter_images
                        WHERE filter_id = ?
                        ORDER BY created_at DESC
                    ''', (filter_id,))
                rows = [dict(row) for row in cursor.fetchall()]
                if include_features:
                    import json
                    for row in rows:
                        try:
                            row['features'] = json.loads(row.get('features') or '[]')
                        except Exception:
                            row['features'] = []
                return rows
        except Exception as e:
            logger.error(f"获取过滤图片失败: {e}")
            return []

    def has_global_image_filter_images(self) -> bool:
        """是否存在启用中的全局图片过滤图"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT 1
                    FROM message_filter_images mfi
                    JOIN message_filters mf ON mf.id = mfi.filter_id
                    WHERE mf.is_active = 1
                      AND mf.filter_type = 'image_filter'
                    LIMIT 1
                    '''
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查全局图片过滤图失败: {e}")
            return False

    def get_message_filter_image_by_id(self, image_id: int) -> Optional[Dict]:
        """获取单条过滤图片记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, filter_id, image_path, created_at
                    FROM message_filter_images
                    WHERE id = ?
                ''', (image_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"获取过滤图片失败: {e}")
            return None

    def delete_message_filter_image(self, image_id: int) -> Optional[str]:
        """删除过滤图片记录并返回文件路径"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT image_path FROM message_filter_images WHERE id = ?', (image_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                image_path = row['image_path']
                cursor.execute('DELETE FROM message_filter_images WHERE id = ?', (image_id,))
                conn.commit()
                return image_path
        except Exception as e:
            logger.error(f"删除过滤图片失败: {e}")
            return None

    def delete_message_filter_images_by_filter_id(self, filter_id: int) -> List[str]:
        """删除某条过滤规则的所有图片并返回文件路径列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT image_path FROM message_filter_images WHERE filter_id = ?', (filter_id,))
                rows = cursor.fetchall()
                paths = [row['image_path'] for row in rows]
                cursor.execute('DELETE FROM message_filter_images WHERE filter_id = ?', (filter_id,))
                conn.commit()
                return paths
        except Exception as e:
            logger.error(f"删除过滤图片失败: {e}")
            return []

    def get_all_user_website_filters(self, user_id: int) -> List[Dict]:
        """获取用户所有网站的过滤设置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT website_id, message_filters
                    FROM user_website_settings
                    WHERE user_id = ?
                ''', (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取用户网站过滤失败: {e}")
            return []

    def upsert_website_blocked_user(
        self,
        *,
        user_id: int,
        website_id: int,
        discord_user_id: str,
        discord_username: str,
        trigger_keyword: str = '',
    ) -> bool:
        try:
            normalized_discord_user_id = str(discord_user_id or '').strip()
            if not normalized_discord_user_id:
                return False

            normalized_username = str(discord_username or '').strip()
            normalized_trigger_keyword = str(trigger_keyword or '').strip()

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO website_blocked_users (
                        user_id,
                        website_id,
                        discord_user_id,
                        discord_username,
                        trigger_keyword
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, website_id, discord_user_id) DO UPDATE SET
                        discord_username = excluded.discord_username,
                        trigger_keyword = excluded.trigger_keyword,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        user_id,
                        website_id,
                        normalized_discord_user_id,
                        normalized_username,
                        normalized_trigger_keyword,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"写入网站拉黑用户失败: {e}")
            return False

    def get_website_blocked_users(self, user_id: int, website_id: int) -> List[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT
                        id,
                        user_id,
                        website_id,
                        discord_user_id,
                        discord_username,
                        trigger_keyword,
                        created_at,
                        updated_at
                    FROM website_blocked_users
                    WHERE user_id = ? AND website_id = ?
                    ORDER BY updated_at DESC, id DESC
                    ''',
                    (user_id, website_id),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站拉黑用户失败: {e}")
            return []

    def delete_website_blocked_user(self, user_id: int, website_id: int, discord_user_id: str) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    DELETE FROM website_blocked_users
                    WHERE user_id = ? AND website_id = ? AND discord_user_id = ?
                    ''',
                    (user_id, website_id, str(discord_user_id or '').strip()),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除网站拉黑用户失败: {e}")
            return False

    def get_blocked_website_ids_for_discord_user(
        self,
        *,
        user_id: int,
        discord_user_id: str,
        candidate_website_ids: Optional[Sequence[int]] = None,
    ) -> set[int]:
        try:
            normalized_discord_user_id = str(discord_user_id or '').strip()
            if not normalized_discord_user_id:
                return set()

            website_ids: Optional[List[int]] = None
            if candidate_website_ids is not None:
                website_ids = [
                    int(website_id)
                    for website_id in candidate_website_ids
                    if website_id is not None and str(website_id).strip()
                ]
                if not website_ids:
                    return set()

            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT website_id
                    FROM website_blocked_users
                    WHERE user_id = ? AND discord_user_id = ?
                '''
                params: List[Any] = [user_id, normalized_discord_user_id]
                if website_ids is not None:
                    placeholders = ','.join('?' * len(website_ids))
                    query += f' AND website_id IN ({placeholders})'
                    params.extend(website_ids)
                cursor.execute(query, params)
                return {
                    int(row['website_id'])
                    for row in cursor.fetchall()
                    if row['website_id'] is not None
                }
        except Exception as e:
            logger.error(f"获取用户命中网站拉黑列表失败: {e}")
            return set()

    def has_user_website_filter_images(self, user_id: int) -> bool:
        """指定用户是否存在网站级图片过滤图"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT 1
                    FROM website_filter_images
                    WHERE user_id = ?
                    LIMIT 1
                    ''',
                    (user_id,),
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查网站图片过滤图失败: {e}")
            return False

    def add_website_filter_image(self, user_id: int, website_id: int, filter_id: str, image_path: str, features: np.ndarray) -> int:
        """添加网站过滤图片，返回记录ID"""
        try:
            features_str = None
            if features is not None:
                import json
                features_str = json.dumps(features.tolist())
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO website_filter_images (user_id, website_id, filter_id, image_path, features)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, website_id, filter_id, image_path, features_str))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"添加网站过滤图片失败: {e}")
            raise e

    def get_website_filter_images(self, user_id: int, website_id: int, filter_id: str, include_features: bool = False) -> List[Dict]:
        """获取网站过滤图片列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if include_features:
                    cursor.execute('''
                        SELECT id, image_path, features, created_at
                        FROM website_filter_images
                        WHERE user_id = ? AND website_id = ? AND filter_id = ?
                        ORDER BY created_at DESC
                    ''', (user_id, website_id, filter_id))
                else:
                    cursor.execute('''
                        SELECT id, image_path, created_at
                        FROM website_filter_images
                        WHERE user_id = ? AND website_id = ? AND filter_id = ?
                        ORDER BY created_at DESC
                    ''', (user_id, website_id, filter_id))
                rows = [dict(row) for row in cursor.fetchall()]
                if include_features:
                    import json
                    for row in rows:
                        try:
                            row['features'] = json.loads(row.get('features') or '[]')
                        except Exception:
                            row['features'] = []
                return rows
        except Exception as e:
            logger.error(f"获取网站过滤图片失败: {e}")
            return []

    def get_website_filter_image_by_id(self, image_id: int) -> Optional[Dict]:
        """获取单条网站过滤图片记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, user_id, website_id, filter_id, image_path, created_at
                    FROM website_filter_images
                    WHERE id = ?
                ''', (image_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"获取网站过滤图片失败: {e}")
            return None

    def delete_website_filter_image(self, image_id: int) -> Optional[str]:
        """删除网站过滤图片并返回文件路径"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT image_path FROM website_filter_images WHERE id = ?', (image_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                image_path = row['image_path']
                cursor.execute('DELETE FROM website_filter_images WHERE id = ?', (image_id,))
                conn.commit()
                return image_path
        except Exception as e:
            logger.error(f"删除网站过滤图片失败: {e}")
            return None

    def delete_website_filter_images_by_filter(self, user_id: int, website_id: int, filter_id: str) -> List[str]:
        """删除某条网站过滤规则的所有图片并返回文件路径列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT image_path FROM website_filter_images
                    WHERE user_id = ? AND website_id = ? AND filter_id = ?
                ''', (user_id, website_id, filter_id))
                rows = cursor.fetchall()
                paths = [row['image_path'] for row in rows]
                cursor.execute('''
                    DELETE FROM website_filter_images
                    WHERE user_id = ? AND website_id = ? AND filter_id = ?
                ''', (user_id, website_id, filter_id))
                conn.commit()
                return paths
        except Exception as e:
            logger.error(f"删除网站过滤图片失败: {e}")
            return []

    def get_custom_replies(self) -> List[Dict]:
        """获取自定义回复内容"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, reply_type, content, image_url, is_active, priority, created_at
                    FROM custom_replies
                    WHERE is_active = 1
                    ORDER BY priority DESC, created_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取自定义回复内容失败: {e}")
            return []

    def add_custom_reply(self, reply_type: str, content: str = None, image_url: str = None, priority: int = 0) -> bool:
        """添加自定义回复内容"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO custom_replies (reply_type, content, image_url, priority)
                    VALUES (?, ?, ?, ?)
                ''', (reply_type, content, image_url, priority))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加自定义回复内容失败: {e}")
            return False

    def update_custom_reply(self, reply_id: int, reply_type: str, content: str = None, image_url: str = None, priority: int = 0, is_active: bool = True) -> bool:
        """更新自定义回复内容"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE custom_replies
                    SET reply_type = ?, content = ?, image_url = ?, priority = ?, is_active = ?
                    WHERE id = ?
                ''', (reply_type, content, image_url, priority, is_active, reply_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新自定义回复内容失败: {e}")
            return False

    def delete_custom_reply(self, reply_id: int) -> bool:
        """删除自定义回复内容"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM custom_replies WHERE id = ?', (reply_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除自定义回复内容失败: {e}")
            return False

    def get_products_by_user_shops(
        self,
        user_shops: List[str],
        limit: int = None,
        offset: int = 0,
        keyword: str = None,
        search_type: str = 'all',
        shop_name: str = None
    ) -> Dict:
        """根据用户店铺权限获取商品（支持分页与搜索过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                shop_names = None
                if user_shops is not None:
                    if not isinstance(user_shops, list):
                        user_shops = []
                    if not user_shops:
                        return {'products': [], 'total': 0}

                    shop_names = []
                    for shop_id in user_shops:
                        cursor.execute("SELECT name FROM shops WHERE shop_id = ?", (shop_id,))
                        shop_row = cursor.fetchone()
                        if shop_row:
                            shop_names.append(shop_row[0])

                    if not shop_names:
                        return {'products': [], 'total': 0}

                where_clauses = []
                params: List = []

                if shop_names is not None:
                    placeholders = ','.join('?' * len(shop_names))
                    where_clauses.append(f"p.shop_name IN ({placeholders})")
                    params.extend(shop_names)

                if shop_name and shop_name != '__ALL__':
                    where_clauses.append("p.shop_name = ?")
                    params.append(shop_name)

                if keyword:
                    keyword = keyword.strip()
                if keyword:
                    keyword_lower = keyword.lower()
                    like = f"%{keyword_lower}%"

                    if search_type == 'id':
                        where_clauses.append("(CAST(p.id AS TEXT) = ? OR LOWER(p.product_url) LIKE ?)")
                        params.extend([keyword, f"%itemid={keyword_lower}%"])
                    elif search_type == 'keyword':
                        where_clauses.append("LOWER(p.english_title) LIKE ?")
                        params.append(like)
                    elif search_type == 'chinese':
                        where_clauses.append("LOWER(p.title) LIKE ?")
                        params.append(like)
                    else:
                        where_clauses.append(
                            "(CAST(p.id AS TEXT) = ? OR LOWER(p.title) LIKE ? OR LOWER(p.english_title) LIKE ? OR LOWER(p.product_url) LIKE ?)"
                        )
                        params.extend([keyword, like, like, f"%itemid={keyword_lower}%"])

                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

                query = f'''
                    SELECT p.*,
                           GROUP_CONCAT(pi.image_index) as image_indices,
                           COUNT(pi.id) as image_count,
                           p.custom_reply_text, p.custom_reply_images, p.custom_image_urls, p.image_source
                    FROM products p
                    LEFT JOIN product_images pi ON p.id = pi.product_id
                    {where_sql}
                    GROUP BY p.id
                    ORDER BY p.created_at DESC, p.id DESC
                '''

                query_params = list(params)
                if limit is not None and limit > 0:
                    query += " LIMIT ? OFFSET ?"
                    query_params.extend([limit, offset])

                cursor.execute(query, query_params)
                rows = cursor.fetchall()

                count_query = f"SELECT COUNT(*) FROM products p {where_sql}"
                cursor.execute(count_query, params)
                total = cursor.fetchone()[0]

                products = []
                website_url_configs = self.get_website_url_configs()
                for row in rows:
                    prod = dict(row)
                    if prod.get('image_indices'):
                        image_indices = [int(idx) for idx in prod['image_indices'].split(',') if idx]
                        prod['images'] = [f"/api/image/{prod['id']}/{idx}" for idx in image_indices]
                    else:
                        prod['images'] = []

                    prod['weidianUrl'] = prod.get('product_url')
                    prod['englishTitle'] = prod.get('english_title') or ''
                    prod['titleTranslations'] = normalize_title_translations(
                        prod.get('title_translations'),
                        title=prod.get('title'),
                        english_title=prod.get('english_title'),
                    )
                    prod['cnfansUrl'] = prod.get('cnfans_url') or ''
                    prod['acbuyUrl'] = prod.get('acbuy_url') or ''
                    prod['createdAt'] = prod.get('created_at')
                    prod['autoReplyEnabled'] = prod.get('ruleEnabled', True)
                    prod['shopName'] = prod.get('shop_name') or '未知店铺'
                    prod['customReplyText'] = prod.get('custom_reply_text') or ''
                    prod['replyScope'] = prod.get('reply_scope') or 'all'
                    prod['perWebsiteReplySettings'] = build_frontend_per_website_reply_settings(
                        prod.get('per_website_reply_settings'),
                        prod.get('id'),
                    )

                    try:
                        custom_reply_images = prod.get('custom_reply_images')
                        if custom_reply_images:
                            prod['selectedImageIndexes'] = json.loads(custom_reply_images)
                        else:
                            prod['selectedImageIndexes'] = []
                    except Exception:
                        prod['selectedImageIndexes'] = []

                    try:
                        if prod.get('uploaded_reply_images'):
                            filenames = json.loads(prod['uploaded_reply_images'])
                            prod['uploadedImages'] = [f"/api/custom_reply_image/{prod['id']}/{fn}" for fn in filenames]
                        else:
                            prod['uploadedImages'] = []
                    except Exception:
                        prod['uploadedImages'] = []

                    try:
                        import re
                        m = re.search(r'itemID=(\d+)', prod.get('product_url') or '')
                        prod['weidianId'] = m.group(1) if m else ''
                    except Exception:
                        prod['weidianId'] = ''

                    try:
                        prod['websiteUrls'] = (
                            self.generate_website_urls(prod['weidianId'], website_url_configs)
                            if prod.get('weidianId')
                            else []
                        )
                    except Exception:
                        prod['websiteUrls'] = []

                    products.append(prod)

                return {'products': products, 'total': total}

        except Exception as e:
            print(f"DEBUG: Exception in get_products_by_user_shops: {type(e).__name__}: {e}")
            import traceback
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")
            logger.error("获取用户商品失败: %s", str(e))
            return {'products': [], 'total': 0}

    def get_product_ids_by_user_shops(
        self,
        user_shops: List[str],
        keyword: str = None,
        search_type: str = 'all',
        shop_name: str = None
    ) -> List[int]:
        """根据用户店铺权限获取商品ID（支持搜索过滤）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                shop_names = None
                if user_shops is not None:
                    if not isinstance(user_shops, list):
                        user_shops = []
                    if not user_shops:
                        return []

                    shop_names = []
                    for shop_id in user_shops:
                        cursor.execute("SELECT name FROM shops WHERE shop_id = ?", (shop_id,))
                        shop_row = cursor.fetchone()
                        if shop_row:
                            shop_names.append(shop_row[0])

                    if not shop_names:
                        return []

                where_clauses = []
                params: List = []

                if shop_names is not None:
                    placeholders = ','.join('?' * len(shop_names))
                    where_clauses.append(f"p.shop_name IN ({placeholders})")
                    params.extend(shop_names)

                if shop_name and shop_name != '__ALL__':
                    where_clauses.append("p.shop_name = ?")
                    params.append(shop_name)

                if keyword:
                    keyword = keyword.strip()
                if keyword:
                    keyword_lower = keyword.lower()
                    like = f"%{keyword_lower}%"

                    if search_type == 'id':
                        where_clauses.append("(CAST(p.id AS TEXT) = ? OR LOWER(p.product_url) LIKE ?)")
                        params.extend([keyword, f"%itemid={keyword_lower}%"])
                    elif search_type == 'keyword':
                        where_clauses.append("LOWER(p.english_title) LIKE ?")
                        params.append(like)
                    elif search_type == 'chinese':
                        where_clauses.append("LOWER(p.title) LIKE ?")
                        params.append(like)
                    else:
                        where_clauses.append(
                            "(CAST(p.id AS TEXT) = ? OR LOWER(p.title) LIKE ? OR LOWER(p.english_title) LIKE ? OR LOWER(p.product_url) LIKE ?)"
                        )
                        params.extend([keyword, like, like, f"%itemid={keyword_lower}%"])

                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                query = f"SELECT p.id FROM products p {where_sql} ORDER BY p.created_at DESC, p.id DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [row[0] for row in rows]

        except Exception as e:
            logger.error("获取用户商品ID失败: %s", str(e))
            return []

    def get_global_reply_config(self) -> Dict[str, float]:
        """获取全局回复延迟配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT min_delay, max_delay FROM global_reply_config WHERE id = 1')
                row = cursor.fetchone()
                if row:
                    min_delay, max_delay = normalize_reply_delay_range(row[0] or 1.0, row[1] or 3.0)
                    return {'min_delay': min_delay, 'max_delay': max_delay}
                return {'min_delay': 1.0, 'max_delay': 3.0}  # 默认值
        except Exception as e:
            logger.error(f"获取全局回复配置失败: {e}")
            return {'min_delay': 1.0, 'max_delay': 3.0}

    def update_global_reply_config(self, min_delay: float, max_delay: float) -> bool:
        """更新全局回复延迟配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE global_reply_config
                    SET min_delay = ?, max_delay = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''', (min_delay, max_delay))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新全局回复配置失败: {e}")
            return False

    def get_system_config(self) -> Dict[str, any]:
        """获取系统配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id, scrape_threads FROM system_config WHERE id = 1')
                row = cursor.fetchone()
                if row:
                    return {
                        'discord_channel_id': row[0] or '',
                        'download_threads': row[1] or 4,
                        'feature_extract_threads': row[2] or 4,
                        'discord_similarity_threshold': row[3] or 0.6,
                        'cnfans_channel_id': row[4] or '',
                        'acbuy_channel_id': row[5] or '',
                        'scrape_threads': row[6] or 2
                    }
                # 如果没有配置记录，创建默认配置
                cursor.execute('''
                    INSERT OR IGNORE INTO system_config (id, discord_channel_id, download_threads, feature_extract_threads, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id, scrape_threads)
                    VALUES (1, '', 4, 4, 0.6, '', '', 2)
                ''')
                conn.commit()
                return {
                    'discord_channel_id': '',
                    'download_threads': 4,
                    'feature_extract_threads': 4,
                    'discord_similarity_threshold': 0.6,
                    'cnfans_channel_id': '',
                    'acbuy_channel_id': '',
                    'scrape_threads': 2
                }
        except Exception as e:
            logger.error(f"获取系统配置失败: {e}")
            return {
                'discord_channel_id': '',
                'download_threads': 4,
                'feature_extract_threads': 4,
                'discord_similarity_threshold': 0.6,
                'cnfans_channel_id': '',
                'acbuy_channel_id': '',
                'scrape_threads': 2
            }

    def get_user_settings(self, user_id: int) -> Dict[str, any]:
        """获取用户个性化设置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT download_threads, feature_extract_threads, discord_similarity_threshold,
                           global_reply_min_delay, global_reply_max_delay, user_blacklist, keyword_filters,
                           keyword_reply_enabled, image_reply_enabled, keyword_match_limit,
                           global_reply_template, numeric_filter_keyword, filter_size_min, filter_size_max,
                           bark_enabled, bark_server_url, bark_device_key,
                           keyword_reply_send_best_match_image,
                           keyword_image_search_api_key, keyword_image_search_cx,
                           review_bark_enabled, review_bark_mode, review_bark_count_threshold,
                           review_bark_interval_minutes, review_bark_last_notified_at,
                           review_bark_last_pending_count
                    FROM user_settings WHERE user_id = ?
                ''', (user_id,))
                row = cursor.fetchone()
                if row:
                    min_delay, max_delay = normalize_reply_delay_range(row[3] or 1.0, row[4] or 3.0)
                    return {
                        'download_threads': row[0] or 4,
                        'feature_extract_threads': row[1] or 4,
                        'discord_similarity_threshold': row[2] or 0.6,
                        'global_reply_min_delay': min_delay,
                        'global_reply_max_delay': max_delay,
                        'user_blacklist': row[5] or '',
                        'keyword_filters': row[6] or '',
                        'keyword_reply_enabled': row[7] if row[7] is not None else 1,
                        'image_reply_enabled': row[8] if row[8] is not None else 1,
                        'keyword_match_limit': row[9] if row[9] is not None else 0,
                        'global_reply_template': row[10] or '',
                        'numeric_filter_keyword': row[11] if row[11] is not None else '',
                        'filter_size_min': row[12] if row[12] is not None else 35,
                        'filter_size_max': row[13] if row[13] is not None else 46,
                        'bark_enabled': row[14] if row[14] is not None else 0,
                        'bark_server_url': row[15] or 'https://api.day.app',
                        'bark_device_key': row[16] or '',
                        'keyword_reply_send_best_match_image': row[17] if row[17] is not None else 0,
                        'keyword_image_search_api_key': row[18] or '',
                        'keyword_image_search_cx': row[19] or '',
                        'review_bark_enabled': row[20] if row[20] is not None else 0,
                        'review_bark_mode': row[21] or 'count',
                        'review_bark_count_threshold': row[22] if row[22] is not None else 5,
                        'review_bark_interval_minutes': row[23] if row[23] is not None else 60,
                        'review_bark_last_notified_at': row[24] or '',
                        'review_bark_last_pending_count': row[25] if row[25] is not None else 0,
                    }
                # 如果用户没有设置，返回默认值
                return {
                    'download_threads': 4,
                    'feature_extract_threads': 4,
                    'discord_similarity_threshold': 0.6,
                    'global_reply_min_delay': 1.0,
                    'global_reply_max_delay': 3.0,
                    'user_blacklist': '',
                    'keyword_filters': '',
                    'keyword_reply_enabled': 1,
                    'image_reply_enabled': 1,
                    'keyword_match_limit': 0,
                    'global_reply_template': '',
                    'numeric_filter_keyword': '',
                    'filter_size_min': 35,
                    'filter_size_max': 46,
                    'bark_enabled': 0,
                    'bark_server_url': 'https://api.day.app',
                    'bark_device_key': '',
                    'keyword_reply_send_best_match_image': 0,
                    'keyword_image_search_api_key': '',
                    'keyword_image_search_cx': '',
                    'review_bark_enabled': 0,
                    'review_bark_mode': 'count',
                    'review_bark_count_threshold': 5,
                    'review_bark_interval_minutes': 60,
                    'review_bark_last_notified_at': '',
                    'review_bark_last_pending_count': 0,
                }
        except Exception as e:
            logger.error(f"获取用户设置失败: {e}")
            return {
                'download_threads': 4,
                'feature_extract_threads': 4,
                'discord_similarity_threshold': 0.6,
                'global_reply_min_delay': 1.0,
                'global_reply_max_delay': 3.0,
                'user_blacklist': '',
                'keyword_filters': '',
                'keyword_reply_enabled': 1,
                'image_reply_enabled': 1,
                'keyword_match_limit': 0,
                'global_reply_template': '',
                'numeric_filter_keyword': '',
                'filter_size_min': 35,
                'filter_size_max': 46,
                'bark_enabled': 0,
                'bark_server_url': 'https://api.day.app',
                'bark_device_key': '',
                'keyword_reply_send_best_match_image': 0,
                'keyword_image_search_api_key': '',
                'keyword_image_search_cx': '',
                'review_bark_enabled': 0,
                'review_bark_mode': 'count',
                'review_bark_count_threshold': 5,
                'review_bark_interval_minutes': 60,
                'review_bark_last_notified_at': '',
                'review_bark_last_pending_count': 0,
            }

    def update_user_settings(self, user_id: int, download_threads: int = None,
                           feature_extract_threads: int = None, discord_similarity_threshold: float = None,
                           global_reply_min_delay: float = None, global_reply_max_delay: float = None,
                           user_blacklist: str = None, keyword_filters: str = None,
                           keyword_reply_enabled: int = None, image_reply_enabled: int = None,
                           keyword_match_limit: int = None,
                           global_reply_template: str = None, numeric_filter_keyword: str = None,
                           filter_size_min: int = None, filter_size_max: int = None,
                           bark_enabled: int = None, bark_server_url: str = None,
                           bark_device_key: str = None,
                           keyword_reply_send_best_match_image: int = None,
                           keyword_image_search_api_key: str = None,
                           keyword_image_search_cx: str = None,
                           review_bark_enabled: int = None,
                           review_bark_mode: str = None,
                           review_bark_count_threshold: int = None,
                           review_bark_interval_minutes: int = None,
                           review_bark_last_notified_at: str = None,
                           review_bark_last_pending_count: int = None) -> bool:
        """更新用户个性化设置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 检查用户是否已有设置
                cursor.execute('SELECT id FROM user_settings WHERE user_id = ?', (user_id,))
                existing = cursor.fetchone()

                if existing:
                    # 更新现有设置
                    update_fields = []
                    params = []

                    if download_threads is not None:
                        update_fields.append('download_threads = ?')
                        params.append(download_threads)

                    if feature_extract_threads is not None:
                        update_fields.append('feature_extract_threads = ?')
                        params.append(feature_extract_threads)

                    if discord_similarity_threshold is not None:
                        update_fields.append('discord_similarity_threshold = ?')
                        params.append(discord_similarity_threshold)

                    if global_reply_min_delay is not None:
                        update_fields.append('global_reply_min_delay = ?')
                        params.append(global_reply_min_delay)

                    if global_reply_max_delay is not None:
                        update_fields.append('global_reply_max_delay = ?')
                        params.append(global_reply_max_delay)

                    if user_blacklist is not None:
                        update_fields.append('user_blacklist = ?')
                        params.append(user_blacklist)

                    if keyword_filters is not None:
                        update_fields.append('keyword_filters = ?')
                        params.append(keyword_filters)

                    if keyword_reply_enabled is not None:
                        update_fields.append('keyword_reply_enabled = ?')
                        params.append(keyword_reply_enabled)

                    if image_reply_enabled is not None:
                        update_fields.append('image_reply_enabled = ?')
                        params.append(image_reply_enabled)

                    if keyword_match_limit is not None:
                        update_fields.append('keyword_match_limit = ?')
                        params.append(keyword_match_limit)

                    if global_reply_template is not None:
                        update_fields.append('global_reply_template = ?')
                        params.append(global_reply_template)

                    if numeric_filter_keyword is not None:
                        update_fields.append('numeric_filter_keyword = ?')
                        params.append(numeric_filter_keyword)

                    if filter_size_min is not None:
                        update_fields.append('filter_size_min = ?')
                        params.append(filter_size_min)

                    if filter_size_max is not None:
                        update_fields.append('filter_size_max = ?')
                        params.append(filter_size_max)

                    if bark_enabled is not None:
                        update_fields.append('bark_enabled = ?')
                        params.append(bark_enabled)

                    if bark_server_url is not None:
                        update_fields.append('bark_server_url = ?')
                        params.append(bark_server_url)

                    if bark_device_key is not None:
                        update_fields.append('bark_device_key = ?')
                        params.append(bark_device_key)

                    if keyword_reply_send_best_match_image is not None:
                        update_fields.append('keyword_reply_send_best_match_image = ?')
                        params.append(keyword_reply_send_best_match_image)

                    if keyword_image_search_api_key is not None:
                        update_fields.append('keyword_image_search_api_key = ?')
                        params.append(keyword_image_search_api_key)

                    if keyword_image_search_cx is not None:
                        update_fields.append('keyword_image_search_cx = ?')
                        params.append(keyword_image_search_cx)

                    if review_bark_enabled is not None:
                        update_fields.append('review_bark_enabled = ?')
                        params.append(review_bark_enabled)

                    if review_bark_mode is not None:
                        update_fields.append('review_bark_mode = ?')
                        params.append(review_bark_mode)

                    if review_bark_count_threshold is not None:
                        update_fields.append('review_bark_count_threshold = ?')
                        params.append(review_bark_count_threshold)

                    if review_bark_interval_minutes is not None:
                        update_fields.append('review_bark_interval_minutes = ?')
                        params.append(review_bark_interval_minutes)

                    if review_bark_last_notified_at is not None:
                        update_fields.append('review_bark_last_notified_at = ?')
                        params.append(review_bark_last_notified_at)

                    if review_bark_last_pending_count is not None:
                        update_fields.append('review_bark_last_pending_count = ?')
                        params.append(review_bark_last_pending_count)

                    if update_fields:
                        update_fields.append('updated_at = CURRENT_TIMESTAMP')
                        sql = f'UPDATE user_settings SET {", ".join(update_fields)} WHERE user_id = ?'
                        params.append(user_id)
                        cursor.execute(sql, params)
                else:
                    # 插入新设置
                    cursor.execute('''
                        INSERT INTO user_settings
                        (user_id, download_threads, feature_extract_threads, discord_similarity_threshold,
                         global_reply_min_delay, global_reply_max_delay, user_blacklist, keyword_filters,
                         keyword_reply_enabled, image_reply_enabled, keyword_match_limit, global_reply_template,
                         numeric_filter_keyword, filter_size_min, filter_size_max, bark_enabled, bark_server_url, bark_device_key,
                         keyword_reply_send_best_match_image, keyword_image_search_api_key, keyword_image_search_cx,
                         review_bark_enabled, review_bark_mode,
                         review_bark_count_threshold, review_bark_interval_minutes,
                         review_bark_last_notified_at, review_bark_last_pending_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        user_id,
                        download_threads or 4,
                        feature_extract_threads or 4,
                        discord_similarity_threshold or 0.6,
                        global_reply_min_delay or 1.0,
                        global_reply_max_delay or 3.0,
                        user_blacklist or '',
                        keyword_filters or '',
                        keyword_reply_enabled if keyword_reply_enabled is not None else 1,
                        image_reply_enabled if image_reply_enabled is not None else 1,
                        keyword_match_limit if keyword_match_limit is not None else 0,
                        global_reply_template or '',
                        numeric_filter_keyword or '',
                        filter_size_min if filter_size_min is not None else 35,
                        filter_size_max if filter_size_max is not None else 46,
                        bark_enabled if bark_enabled is not None else 0,
                        bark_server_url if bark_server_url is not None else 'https://api.day.app',
                        bark_device_key or '',
                        keyword_reply_send_best_match_image if keyword_reply_send_best_match_image is not None else 0,
                        keyword_image_search_api_key or '',
                        keyword_image_search_cx or '',
                        review_bark_enabled if review_bark_enabled is not None else 0,
                        review_bark_mode or 'count',
                        review_bark_count_threshold if review_bark_count_threshold is not None else 5,
                        review_bark_interval_minutes if review_bark_interval_minutes is not None else 60,
                        review_bark_last_notified_at or '',
                        review_bark_last_pending_count if review_bark_last_pending_count is not None else 0,
                    ))

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户设置失败: {e}")
            return False

    def count_pending_keyword_reply_review_items(self, user_id: int) -> int:
        """统计用户当前待审核的关键词回复数量"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT COUNT(1)
                    FROM keyword_reply_review_items
                    WHERE user_id = ? AND status = 'pending'
                    ''',
                    (user_id,),
                )
                row = cursor.fetchone()
                return int((row[0] if row else 0) or 0)
        except Exception as e:
            logger.error(f"统计关键词审核队列数量失败: {e}")
            return 0

    def get_pending_keyword_reply_review_user_ids(self) -> List[int]:
        """获取当前存在待审核关键词回复的用户ID列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT DISTINCT user_id
                    FROM keyword_reply_review_items
                    WHERE status = 'pending' AND user_id IS NOT NULL
                    ORDER BY user_id ASC
                    '''
                )
                return [
                    int(row[0])
                    for row in cursor.fetchall()
                    if row and row[0] is not None
                ]
        except Exception as e:
            logger.error(f"获取待审核关键词回复用户列表失败: {e}")
            return []

    def update_system_config(self, discord_channel_id: str = None, discord_similarity_threshold: float = None,
                           cnfans_channel_id: str = None, acbuy_channel_id: str = None) -> bool:
        """更新系统配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 首先确保配置记录存在
                cursor.execute('''
                    INSERT OR IGNORE INTO system_config (id, discord_channel_id, discord_similarity_threshold, cnfans_channel_id, acbuy_channel_id)
                    VALUES (1, '', 0.6, '', '')
                ''')

                # 构建更新语句
                update_fields = []
                params = []

                if discord_channel_id is not None:
                    update_fields.append('discord_channel_id = ?')
                    params.append(discord_channel_id)

                if discord_similarity_threshold is not None:
                    update_fields.append('discord_similarity_threshold = ?')
                    params.append(discord_similarity_threshold)

                if cnfans_channel_id is not None:
                    update_fields.append('cnfans_channel_id = ?')
                    params.append(cnfans_channel_id)

                if acbuy_channel_id is not None:
                    update_fields.append('acbuy_channel_id = ?')
                    params.append(acbuy_channel_id)

                if update_fields:
                    update_fields.append('updated_at = CURRENT_TIMESTAMP')
                    sql = f'UPDATE system_config SET {", ".join(update_fields)} WHERE id = 1'
                    cursor.execute(sql, params)
                    conn.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"更新系统配置失败: {e}")
            return False

    # ===== 店铺管理方法 =====

    def add_shop(self, shop_id: str, name: str, owner_user_id: Optional[int] = None) -> bool:
        """添加新店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 检查店铺是否已存在
                cursor.execute('SELECT id FROM shops WHERE shop_id = ?', (shop_id,))
                if cursor.fetchone():
                    logger.warning(f"店铺 {shop_id} 已存在")
                    return False

                cursor.execute('''
                    INSERT INTO shops (shop_id, name, product_count)
                    VALUES (?, ?, 0)
                ''', (shop_id, name))

                if owner_user_id:
                    cursor.execute('''
                        INSERT OR IGNORE INTO user_shop_permissions (user_id, shop_id)
                        VALUES (?, ?)
                    ''', (owner_user_id, shop_id))

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加店铺失败: {e}")
            return False

    def get_all_shops(self) -> List[Dict]:
        """获取所有店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM shops ORDER BY created_at DESC')
                rows = cursor.fetchall()

                shops = []
                for row in rows:
                    shops.append({
                        'id': row[0],
                        'shop_id': row[1],
                        'name': row[2],
                        'product_count': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    })
                return shops
        except Exception as e:
            logger.error(f"获取店铺列表失败: {e}")
            return []

    def get_shop_by_id(self, shop_id: str) -> Optional[Dict]:
        """根据shop_id获取店铺信息"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM shops WHERE shop_id = ?', (shop_id,))
                row = cursor.fetchone()

                if row:
                    return {
                        'id': row[0],
                        'shop_id': row[1],
                        'name': row[2],
                        'product_count': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    }
                return None
        except Exception as e:
            logger.error(f"获取店铺信息失败: {e}")
            return None

    def update_shop_product_count(self, shop_id: str, product_count: int) -> bool:
        """更新店铺的商品数量"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE shops
                    SET product_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE shop_id = ?
                ''', (product_count, shop_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新店铺商品数量失败: {e}")
            return False

    def delete_shop(self, shop_id: str) -> bool:
        """删除店铺"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM user_shop_permissions WHERE shop_id = ?', (shop_id,))
                cursor.execute('DELETE FROM shops WHERE shop_id = ?', (shop_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除店铺失败: {e}")
            return False

    # ========== 抓取状态管理方法 ==========

    def get_scrape_status(self) -> Dict:
        """获取抓取状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM scrape_status WHERE id = 1')
                row = cursor.fetchone()

                if row:
                    failed_items_raw = row['failed_items'] if 'failed_items' in row.keys() else '[]'
                    try:
                        failed_items = json.loads(failed_items_raw) if failed_items_raw else []
                    except (TypeError, ValueError):
                        failed_items = []

                    return {
                        'id': row['id'],
                        'is_scraping': bool(row['is_scraping']),
                        'stop_signal': bool(row['stop_signal']),
                        'current_shop_id': row['current_shop_id'],
                        'total': row['total'] or 0,
                        'processed': row['processed'] or 0,
                        'success': row['success'] or 0,
                        'failed': (row['failed'] if 'failed' in row.keys() else 0) or 0,
                        'image_failed': (row['image_failed'] if 'image_failed' in row.keys() else 0) or 0,
                        'index_failed': (row['index_failed'] if 'index_failed' in row.keys() else 0) or 0,
                        'failed_items': failed_items,
                        'progress': row['progress'] or 0.0,
                        'message': row['message'] or '等待开始...',
                        'completed': bool(row['completed']),
                        'thread_id': row['thread_id'],
                        'updated_at': row['updated_at']
                    }
                else:
                    # 如果没有记录，创建默认记录
                    return self.reset_scrape_status()

        except Exception as e:
            logger.error(f"获取抓取状态失败: {e}")
            return {
                'is_scraping': False,
                'stop_signal': False,
                'current_shop_id': None,
                'total': 0,
                'processed': 0,
                'success': 0,
                'failed': 0,
                'image_failed': 0,
                'index_failed': 0,
                'failed_items': [],
                'progress': 0.0,
                'message': '获取状态失败',
                'completed': False,
                'thread_id': None,
                'updated_at': None
            }

    def update_scrape_status(self, **kwargs) -> bool:
        """更新抓取状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 构建更新语句
                fields = []
                values = []
                for key, value in kwargs.items():
                    if key in ['is_scraping', 'stop_signal', 'completed']:
                        fields.append(f'{key} = ?')
                        values.append(1 if value else 0)
                    elif key in ['total', 'processed', 'success', 'failed', 'image_failed', 'index_failed']:
                        fields.append(f'{key} = ?')
                        values.append(int(value) if value is not None else 0)
                    elif key == 'progress':
                        fields.append(f'{key} = ?')
                        values.append(float(value) if value is not None else 0.0)
                    elif key == 'failed_items':
                        fields.append('failed_items = ?')
                        if value is None:
                            values.append('[]')
                        elif isinstance(value, str):
                            values.append(value)
                        else:
                            values.append(json.dumps(value, ensure_ascii=False))
                    elif key in ['current_shop_id', 'message', 'thread_id']:
                        fields.append(f'{key} = ?')
                        values.append(str(value) if value is not None else None)

                if fields:
                    fields.append('updated_at = CURRENT_TIMESTAMP')
                    query = f'UPDATE scrape_status SET {", ".join(fields)} WHERE id = 1'
                    cursor.execute(query, values)
                    conn.commit()
                    return cursor.rowcount > 0

                return False

        except Exception as e:
            logger.error(f"更新抓取状态失败: {e}")
            return False

    def reset_scrape_status(self) -> Dict:
        """重置抓取状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE scrape_status SET
                        is_scraping = 0,
                        stop_signal = 0,
                        current_shop_id = NULL,
                        total = 0,
                        processed = 0,
                        success = 0,
                        failed = 0,
                        image_failed = 0,
                        index_failed = 0,
                        failed_items = '[]',
                        progress = 0,
                        message = '等待开始...',
                        completed = 0,
                        thread_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''')
                conn.commit()

                return {
                    'is_scraping': False,
                    'stop_signal': False,
                    'current_shop_id': None,
                    'total': 0,
                    'processed': 0,
                    'success': 0,
                    'failed': 0,
                    'image_failed': 0,
                    'index_failed': 0,
                    'failed_items': [],
                    'progress': 0.0,
                    'message': '等待开始...',
                    'completed': False,
                    'thread_id': None,
                    'updated_at': None
                }

        except Exception as e:
            logger.error(f"重置抓取状态失败: {e}")
            return {
                'is_scraping': False,
                'stop_signal': False,
                'current_shop_id': None,
                'total': 0,
                'processed': 0,
                'success': 0,
                'failed': 0,
                'image_failed': 0,
                'index_failed': 0,
                'progress': 0.0,
                'message': '重置失败',
                'completed': False,
                'thread_id': None,
                'updated_at': None
            }

# 全局数据库实例
db = Database()
