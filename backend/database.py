import sqlite3
import numpy as np
import os
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
try:
    from config import config
except ImportError:
    from .config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # SQLite 数据库路径 (用于存储商品元数据和Discord账号信息)
        self.db_path = os.path.join(os.path.dirname(__file__), 'data', 'metadata.db')

        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化 SQLite 数据库
        self.init_sqlite_database()

    def init_sqlite_database(self):
        """初始化 SQLite 数据库 (用于元数据存储)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 创建商品表（移除商品级别延迟，使用全局延迟）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    description TEXT,
                    english_title TEXT,
                    cnfans_url TEXT,
                    acbuy_url TEXT,
                    shop_name TEXT,
                    ruleEnabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建索引以优化查询性能
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_shop_name ON products(shop_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_rule_enabled ON products(ruleEnabled)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_images_product_id ON product_images(product_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_images_image_index ON product_images(image_index)')
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
                cursor.execute('ALTER TABLE products ADD COLUMN shop_name TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN cnfans_channel_id TEXT')
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute('ALTER TABLE system_config ADD COLUMN acbuy_channel_id TEXT')
            except sqlite3.OperationalError:
                pass

            # 创建图片表 (milvus_id 替代 faiss_id)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    image_index INTEGER NOT NULL,
                    features TEXT,  -- 存储序列化的特征向量
                    milvus_id INTEGER UNIQUE,
                    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
                    UNIQUE(product_id, image_index)
                )
            ''')

            # 创建用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',  -- admin, user
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

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
                    status TEXT DEFAULT 'offline',
                    last_active TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
                )
            ''')

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
                    search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (matched_product_id) REFERENCES products (id) ON DELETE SET NULL
                )
            ''')

            # 创建全局延迟配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_reply_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    min_delay REAL DEFAULT 3.0,
                    max_delay REAL DEFAULT 8.0,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建网站频道绑定表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_channel_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    channel_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (website_id) REFERENCES website_configs (id) ON DELETE CASCADE,
                    UNIQUE(website_id, channel_id)
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

            # 插入默认网站配置
            cursor.execute('''
                INSERT OR IGNORE INTO website_configs (name, display_name, url_template, id_pattern, badge_color)
                VALUES
                    ('cnfans', 'CNFans', 'https://cnfans.com/product?id={id}&platform=WEIDIAN', '{id}', 'blue'),
                    ('acbuy', 'AcBuy', 'https://www.acbuy.com/product?url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D{id}&id={id}&source=WD', '{id}', 'orange'),
                    ('weidian', '微店', 'https://weidian.com/item.html?itemID={id}', '{id}', 'gray')
            ''')

            # 创建用户设置表（每个用户的个性化设置）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    download_threads INTEGER DEFAULT 4,
                    feature_extract_threads INTEGER DEFAULT 4,
                    discord_similarity_threshold REAL DEFAULT 0.6,
                    global_reply_min_delay REAL DEFAULT 3.0,
                    global_reply_max_delay REAL DEFAULT 8.0,
                    user_blacklist TEXT DEFAULT '',  -- 用户黑名单，逗号分隔
                    keyword_filters TEXT DEFAULT '',  -- 关键词过滤，逗号分隔
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    UNIQUE(user_id)
                )
            ''')

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
                    progress REAL DEFAULT 0,
                    message TEXT DEFAULT '等待开始...',
                    completed BOOLEAN DEFAULT 0,
                    thread_id TEXT,  -- 记录当前线程ID
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认状态记录
            cursor.execute('''
                INSERT OR IGNORE INTO scrape_status (id, is_scraping, stop_signal, message)
                VALUES (1, 0, 0, '等待开始...')
            ''')

            # 插入默认全局延迟配置
            cursor.execute('''
                INSERT OR IGNORE INTO global_reply_config (id, min_delay, max_delay)
                VALUES (1, 3.0, 8.0)
            ''')

            # 为现有商品设置默认店铺名称
            try:
                cursor.execute('UPDATE products SET shop_name = ? WHERE shop_name IS NULL OR shop_name = ?', ('未知店铺', ''))
                logger.info("已为缺少店铺名称的商品设置默认值")
            except Exception as e:
                logger.warning(f"设置默认店铺名称失败: {e}")

            conn.commit()


    @contextmanager
    def get_connection(self):
        """获取 SQLite 数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # 启用行工厂
            yield conn
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
            cursor.execute('''
                INSERT OR REPLACE INTO products
                (product_url, title, description, english_title, cnfans_url, acbuy_url, shop_name, ruleEnabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                product_data['product_url'],
                product_data.get('title', ''),
                product_data.get('description', ''),
                product_data.get('english_title', ''),
                product_data.get('cnfans_url', ''),
                product_data.get('acbuy_url', ''),
                product_data.get('shop_name', ''),
                product_data.get('ruleEnabled', True)
            ))
            product_id = cursor.lastrowid
            conn.commit()
            return product_id

    def insert_image_record(self, product_id: int, image_path: str, image_index: int, features: np.ndarray = None) -> int:
        """插入图像记录到数据库，返回记录ID供FAISS使用"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 将特征向量序列化为字符串存储
                features_str = None
                if features is not None:
                    import json
                    features_str = json.dumps(features.tolist())

                cursor.execute('''
                    INSERT INTO product_images
                    (product_id, image_path, image_index, features)
                    VALUES (?, ?, ?, ?)
                ''', (product_id, image_path, image_index, features_str))
                conn.commit()
                record_id = cursor.lastrowid
                logger.info(f"图像记录插入成功: product_id={product_id}, image_index={image_index}, record_id={record_id}")
                return record_id

        except Exception as e:
            logger.error(f"插入图像记录失败: {e}")
            raise e

    def search_similar_images(self, query_vector: np.ndarray, limit: int = 1,
                             threshold: float = 0.6, user_shops: Optional[List[str]] = None) -> List[Dict]:
        """使用FAISS搜索相似图像"""
        try:
            try:
                from vector_engine import get_vector_engine
            except ImportError:
                from .vector_engine import get_vector_engine
            engine = get_vector_engine()

            print(f"DEBUG DB: Starting FAISS search, threshold: {threshold}, limit: {limit}")
            print(f"DEBUG DB: Query vector length: {len(query_vector) if hasattr(query_vector, '__len__') else 'unknown'}")

            # 执行FAISS搜索 - 请求更多结果以应对被删除的向量
            faiss_results = engine.search(query_vector, top_k=min(limit * 3, 50))  # 请求更多候选结果
            print(f"DEBUG DB: FAISS search returned {len(faiss_results)} results")

            matched_results = []

            for result in faiss_results:
                score = result['score']
                db_id = result['db_id']

                print(f"DEBUG DB: Processing result - db_id: {db_id}, score: {score}, threshold: {threshold}")

                # 通过image_db_id获取产品信息
                image_info = self.get_image_info_by_id(db_id)
                if image_info:
                    print(f"DEBUG DB: Found image info for db_id {db_id}: product_id={image_info['product_id']}")
                    product_info = self._get_product_info_by_id(image_info['product_id'])

                    if product_info:
                        # 如果指定了用户店铺权限，进行过滤
                        if user_shops and product_info.get('shop_name') not in user_shops:
                            print(f"DEBUG DB: Skipping product from shop {product_info.get('shop_name')} - not in user shops {user_shops}")
                            continue

                        print(f"DEBUG DB: Found product info for product_id {image_info['product_id']}: ruleEnabled={product_info.get('ruleEnabled', True)}")
                        result_dict = {
                            **product_info,
                            'similarity': score,
                            'image_index': image_info['image_index'],
                            'image_path': image_info['image_path']
                        }
                        matched_results.append(result_dict)
                        print(f"DEBUG DB: Added result with similarity {score}")

                        # 如果找到了足够的结果，就停止
                        if len(matched_results) >= limit:
                            break
                    else:
                        print(f"DEBUG DB: Product info not found for product_id {image_info['product_id']}")
                else:
                    print(f"DEBUG DB: Image info not found for db_id {db_id}")

            # 如果没有找到任何结果，返回最佳匹配（即使低于阈值）
            if not matched_results and faiss_results:
                print(f"DEBUG DB: No results above threshold {threshold}, returning best match")
                best_result = faiss_results[0]
                db_id = best_result['db_id']
                image_info = self.get_image_info_by_id(db_id)
                if image_info:
                    product_info = self._get_product_info_by_id(image_info['product_id'])
                    if product_info:
                        result_dict = {
                            **product_info,
                            'similarity': best_result['score'],
                            'image_index': image_info['image_index'],
                            'image_path': image_info['image_path']
                        }
                        matched_results.append(result_dict)
                        print(f"DEBUG DB: Added best match with similarity {best_result['score']}")

            return matched_results

        except Exception as e:
            logger.error(f"FAISS搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []

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
        """获取已建立索引的商品URL列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT p.product_url
                FROM products p
                JOIN product_images pi ON p.id = pi.product_id
            ''')
            return [row['product_url'] for row in cursor.fetchall()]

    def get_product_images(self, product_id: int) -> List[Dict]:
        """获取商品的所有图片及其特征向量"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, image_path, image_index, features
                    FROM product_images
                    WHERE product_id = ?
                    ORDER BY image_index
                ''', (product_id,))

                images = []
                for row in cursor.fetchall():
                    image_data = dict(row)
                    # 反序列化特征向量
                    if image_data.get('features'):
                        import json
                        try:
                            features_list = json.loads(image_data['features'])
                            image_data['features'] = np.array(features_list, dtype='float32')
                        except Exception as e:
                            logger.warning(f"反序列化特征向量失败: {e}")
                            image_data['features'] = None
                    else:
                        image_data['features'] = None
                    images.append(image_data)

                return images

        except Exception as e:
            logger.error(f"获取商品图片失败: {e}")
            return []

    def delete_product_images(self, product_id: int) -> bool:
        """删除商品的所有图像和物理文件"""
        try:
            # 获取该商品的所有图像记录ID和文件路径
            image_records = []
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, image_path FROM product_images WHERE product_id = ?", (product_id,))
                image_records = [{'id': row['id'], 'path': row['image_path']} for row in cursor.fetchall()]

            if image_records:
                # 从FAISS中删除向量
                try:
                    from vector_engine import get_vector_engine
                except ImportError:
                    from .vector_engine import get_vector_engine
                engine = get_vector_engine()
                for record in image_records:
                    engine.remove_vector_by_db_id(record['id'])

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

            # 保存FAISS索引
            if image_records:
                engine.save()

            return True
        except Exception as e:
            logger.error(f"删除商品图像失败: {e}")
            return False

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

    def delete_image_vector(self, product_id: int, image_index: int) -> bool:
        """删除特定的图像向量和物理文件"""
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

            # 从FAISS中删除向量并重建索引
            try:
                from vector_engine import get_vector_engine
            except ImportError:
                from .vector_engine import get_vector_engine
            engine = get_vector_engine()
            success = engine.remove_vector_by_db_id(image_id)
            if not success:
                logger.error(f"FAISS删除向量失败: db_id={image_id}")
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

                # --- 删除重新排序的代码 ---
                # 重新排序会导致前端 React key 冲突和浏览器缓存问题
                # 让图片索引保持固定，删除中间图片后索引不变
                # cursor.execute("SELECT id, image_index FROM product_images WHERE product_id = ? ORDER BY image_index",
                #              (product_id,))
                # remaining_images = cursor.fetchall()
                #
                # # 更新索引，从0开始重新编号
                # for new_index, (img_id, old_index) in enumerate(remaining_images):
                #     if new_index != old_index:
                #         cursor.execute("UPDATE product_images SET image_index = ? WHERE id = ?",
                #                      (new_index, img_id))

                conn.commit()

            logger.info(f"图片删除成功: product_id={product_id}, image_index={image_index}")
            return True
        except Exception as e:
            logger.error(f"删除图像向量失败: {e}")
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
        """获取已索引的总图片数量"""
        try:
            try:
                from vector_engine import get_vector_engine
            except ImportError:
                from .vector_engine import get_vector_engine
            engine = get_vector_engine()
            return engine.count()
        except Exception as e:
            logger.error(f"获取索引图片数量失败: {e}")
            return 0

    def get_indexed_product_urls(self) -> List[str]:
        """获取已建立索引的商品URL列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT p.product_url
                    FROM products p
                    JOIN product_images pi ON p.id = pi.product_id
                ''')
                return [row['product_url'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取已索引商品URL失败: {e}")
            return []

    def add_search_history(self, query_image_path: str, matched_product_id: int,
                          matched_image_index: int, similarity: float, threshold: float) -> bool:
        """添加搜索历史记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO search_history
                    (query_image_path, matched_product_id, matched_image_index, similarity, threshold)
                    VALUES (?, ?, ?, ?, ?)
                ''', (query_image_path, matched_product_id, matched_image_index, similarity, threshold))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加搜索历史失败: {e}")
            return False

    def get_search_history(self, limit: int = 50, offset: int = 0) -> Dict:
        """获取搜索历史记录（支持分页）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 获取总数
                cursor.execute('SELECT COUNT(*) FROM search_history')
                total = cursor.fetchone()[0]

                # 获取分页数据
                cursor.execute('''
                    SELECT
                        sh.id,
                        sh.query_image_path,
                        sh.matched_product_id,
                        sh.matched_image_index,
                        sh.similarity,
                        sh.threshold,
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
                    ORDER BY sh.search_time DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
                rows = cursor.fetchall()
                history = []
                for row in rows:
                    history.append({
                        'id': row['id'],
                        'query_image_path': row['query_image_path'],
                        'matched_product_id': row['matched_product_id'],
                        'matched_image_index': row['matched_image_index'],
                        'similarity': row['similarity'],
                        'threshold': row['threshold'],
                        'search_time': row['search_time'],
                        'title': row['title'],
                        'english_title': row['english_title'],
                        'weidian_url': row['weidian_url'],
                        'cnfans_url': row['cnfans_url'],
                        'acbuy_url': row['acbuy_url'],
                        'ruleEnabled': row['ruleEnabled'],
                        'matched_image_path': row['matched_image_path']
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

    # ===== 用户权限管理方法 =====

    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """用户认证"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, username, password_hash, role, is_active, created_at
                    FROM users
                    WHERE username = ? AND is_active = 1
                ''', (username,))
                user = cursor.fetchone()
                if user:
                    user_dict = dict(user)
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

                    if authenticated:
                        # 获取用户管理的店铺
                        user_dict['shops'] = self.get_user_shops(user_dict['id'])
                        return user_dict
                return None
        except Exception as e:
            logger.error(f"用户认证失败: {e}")
            return None

    def create_user(self, username: str, password: str, role: str = 'user') -> bool:
        """创建新用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 简单的密码哈希（生产环境应该使用bcrypt）
                import hashlib
                password_hash = f"hashed_{password}"  # 简化版，实际应该用bcrypt

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
                    SELECT id, username, role, is_active, created_at
                    FROM users
                    ORDER BY created_at DESC
                ''')
                users = []
                for row in cursor.fetchall():
                    user = dict(row)
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

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据ID获取用户"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, username, role, is_active, created_at
                    FROM users
                    WHERE id = ?
                ''', (user_id,))
                user = cursor.fetchone()
                if user:
                    user_dict = dict(user)
                    user_dict['shops'] = self.get_user_shops(user_id)
                    return user_dict
                return None
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return None

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
                        SELECT id, username, token, status, last_active, created_at, user_id
                    FROM discord_accounts
                    ORDER BY created_at DESC
                    ''')
                else:
                    # 普通用户查询自己的账号
                    cursor.execute('''
                        SELECT id, username, token, status, last_active, created_at, user_id
                        FROM discord_accounts
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                    ''', (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取用户Discord账号失败: {e}")
            return []

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
                    'title', 'english_title', 'ruleEnabled',
                    'custom_reply_text', 'custom_reply_images', 'custom_image_urls'
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

    def update_account_status(self, account_id: int, status: str) -> bool:
        """更新Discord账号状态"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE discord_accounts
                    SET status = ?, last_active = datetime('now')
                    WHERE id = ?
                ''', (status, account_id))
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
                        wc.id_pattern, wc.badge_color, wc.created_at,
                        GROUP_CONCAT(wcb.channel_id) as channels
                    FROM website_configs wc
                    LEFT JOIN website_channel_bindings wcb ON wc.id = wcb.website_id
                    GROUP BY wc.id, wc.name, wc.display_name, wc.url_template, wc.id_pattern, wc.badge_color, wc.created_at
                    ORDER BY wc.created_at
                ''')

                configs = []
                for row in cursor.fetchall():
                    config = dict(row)
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

    def add_website_config(self, name: str, display_name: str, url_template: str, id_pattern: str, badge_color: str = 'blue') -> bool:
        """添加网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO website_configs (name, display_name, url_template, id_pattern, badge_color)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, display_name, url_template, id_pattern, badge_color))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加网站配置失败: {e}")
            return False

    def update_website_config(self, config_id: int, name: str, display_name: str, url_template: str, id_pattern: str, badge_color: str) -> bool:
        """更新网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE website_configs
                    SET name = ?, display_name = ?, url_template = ?, id_pattern = ?, badge_color = ?
                    WHERE id = ?
                ''', (name, display_name, url_template, id_pattern, badge_color, config_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新网站配置失败: {e}")
            return False

    def delete_website_config(self, config_id: int) -> bool:
        """删除网站配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM website_configs WHERE id = ?', (config_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除网站配置失败: {e}")
            return False

    def get_website_channel_bindings(self, website_id: int) -> List[str]:
        """获取网站绑定的频道列表"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT channel_id FROM website_channel_bindings
                    WHERE website_id = ?
                    ORDER BY created_at
                ''', (website_id,))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取网站频道绑定失败: {e}")
            return []

    def add_website_channel_binding(self, website_id: int, channel_id: str) -> bool:
        """添加网站频道绑定"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO website_channel_bindings (website_id, channel_id)
                    VALUES (?, ?)
                ''', (website_id, channel_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"添加网站频道绑定失败: {e}")
            return False

    def remove_website_channel_binding(self, website_id: int, channel_id: str) -> bool:
        """移除网站频道绑定"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM website_channel_bindings
                    WHERE website_id = ? AND channel_id = ?
                ''', (website_id, channel_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"移除网站频道绑定失败: {e}")
            return False

    def generate_website_urls(self, weidian_id: str) -> List[Dict]:
        """根据微店ID生成所有网站的URL"""
        try:
            website_configs = self.get_website_configs()
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
                        'channels': self.get_website_channel_bindings(config['id'])
                    })
                except Exception as e:
                    logger.warning(f"生成网站URL失败 {config['name']}: {e}")

            return urls
        except Exception as e:
            logger.error(f"生成网站URL失败: {e}")
            return []

    def get_system_stats(self) -> Dict:
        """获取系统统计信息"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 获取店铺数量（从shops表统计）
                cursor.execute("SELECT COUNT(*) FROM shops")
                shop_count = cursor.fetchone()[0] or 0

                # 获取商品数量
                cursor.execute("SELECT COUNT(*) FROM products")
                product_count = cursor.fetchone()[0] or 0

                # 获取图片数量
                cursor.execute("SELECT COUNT(*) FROM product_images")
                image_count = cursor.fetchone()[0] or 0

                # 获取用户数量
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
                user_count = cursor.fetchone()[0] or 0

                return {
                    'shop_count': shop_count,
                    'product_count': product_count,
                    'image_count': image_count,
                    'user_count': user_count
                }
        except Exception as e:
            logger.error(f"获取系统统计信息失败: {e}")
            return {'shop_count': 0, 'product_count': 0, 'image_count': 0, 'user_count': 0}

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

    def add_message_filter(self, filter_type: str, filter_value: str) -> bool:
        """添加消息过滤规则"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO message_filters (filter_type, filter_value)
                    VALUES (?, ?)
                ''', (filter_type, filter_value))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加消息过滤规则失败: {e}")
            return False

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

    def get_products_by_user_shops(self, user_shops: List[str], limit: int = None, offset: int = 0) -> Dict:
        """根据用户店铺权限获取商品"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor = conn.cursor()

                if user_shops is None:
                    # 管理员可以看到所有商品（不限制店铺）- 优化查询性能
                    if limit is None or limit <= 0:
                        # 一次性获取所有商品和对应的图片索引
                        query = '''
                            SELECT p.*,
                                   GROUP_CONCAT(pi.image_index) as image_indices,
                                   COUNT(pi.id) as image_count,
                                   p.custom_reply_text, p.custom_reply_images, p.custom_image_urls, p.image_source
                            FROM products p
                            LEFT JOIN product_images pi ON p.id = pi.product_id
                            GROUP BY p.id
                            ORDER BY p.created_at DESC
                        '''
                        cursor.execute(query)
                        rows = cursor.fetchall()

                        # 获取总数
                        cursor.execute('SELECT COUNT(*) FROM products')
                        total = cursor.fetchone()[0]
                    else:
                        # 分页查询 - 使用子查询优化性能
                        query = '''
                            SELECT p.*,
                                   GROUP_CONCAT(pi.image_index) as image_indices,
                                   COUNT(pi.id) as image_count,
                                   p.custom_reply_text, p.custom_reply_images, p.custom_image_urls, p.image_source
                            FROM products p
                            LEFT JOIN product_images pi ON p.id = pi.product_id
                            GROUP BY p.id
                            ORDER BY p.created_at DESC
                            LIMIT ? OFFSET ?
                        '''
                        cursor.execute(query, [limit, offset])
                    rows = cursor.fetchall()

                    # 获取总数
                    cursor.execute('SELECT COUNT(*) FROM products')
                    total = cursor.fetchone()[0]

                    products = []
                    for row in rows:
                        prod = dict(row)
                        # 处理图片路径 - 直接使用预查询的image_indices
                        if prod.get('image_indices'):
                            image_indices = [int(idx) for idx in prod['image_indices'].split(',') if idx]
                            prod['images'] = [f"/api/image/{prod['id']}/{idx}" for idx in image_indices]
                        else:
                            prod['images'] = []

                        # 格式化字段名以兼容前端
                        prod['weidianUrl'] = prod.get('product_url')
                        prod['englishTitle'] = prod.get('english_title') or ''
                        prod['cnfansUrl'] = prod.get('cnfans_url') or ''
                        prod['acbuyUrl'] = prod.get('acbuy_url') or ''
                        prod['createdAt'] = prod.get('created_at')
                        prod['autoReplyEnabled'] = prod.get('ruleEnabled', True)
                        prod['shopName'] = prod.get('shop_name') or '未知店铺'

                        # 提取微店ID
                        try:
                            import re
                            m = re.search(r'itemID=(\d+)', prod.get('product_url') or '')
                            prod['weidianId'] = m.group(1) if m else ''
                        except:
                            prod['weidianId'] = ''

                        products.append(prod)

                    return {'products': products, 'total': total}

                elif not user_shops:
                    # 如果用户没有店铺权限，返回空结果
                    return {'products': [], 'total': 0}

                # 确保user_shops是list类型
                if not isinstance(user_shops, list):
                    user_shops = []

                # 根据shop_id找到对应的shop_name
                shop_names = []
                for shop_id in user_shops:
                    cursor.execute("SELECT name FROM shops WHERE shop_id = ?", (shop_id,))
                    shop_row = cursor.fetchone()
                    if shop_row:
                        shop_names.append(shop_row[0])

                if not shop_names:
                    # 如果没有找到对应的店铺名称，返回空结果
                    return {'products': [], 'total': 0}

                # 构建IN查询 - 优化性能
                placeholders = ','.join('?' * len(shop_names))
                if limit is None or limit <= 0:
                    query = f'''
                        SELECT p.*,
                               GROUP_CONCAT(pi.image_index) as image_indices,
                               COUNT(pi.id) as image_count,
                               p.custom_reply_text, p.custom_reply_images, p.custom_image_urls, p.image_source
                        FROM products p
                        LEFT JOIN product_images pi ON p.id = pi.product_id
                        WHERE p.shop_name IN ({placeholders})
                        GROUP BY p.id
                        ORDER BY p.created_at DESC
                    '''
                    cursor.execute(query, shop_names)
                    rows = cursor.fetchall()

                    # 获取总数
                    count_query = f'SELECT COUNT(*) FROM products WHERE shop_name IN ({placeholders})'
                    cursor.execute(count_query, shop_names)
                    total = cursor.fetchone()[0]
                else:
                    query = f'''
                        SELECT p.*,
                               GROUP_CONCAT(pi.image_index) as image_indices,
                               COUNT(pi.id) as image_count,
                               p.custom_reply_text, p.custom_reply_images, p.custom_image_urls, p.image_source
                        FROM products p
                        LEFT JOIN product_images pi ON p.id = pi.product_id
                        WHERE p.shop_name IN ({placeholders})
                        GROUP BY p.id
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    '''
                    cursor.execute(query, shop_names + [limit, offset])
                rows = cursor.fetchall()

                # 获取总数
                count_query = f'SELECT COUNT(*) FROM products WHERE shop_name IN ({placeholders})'
                cursor.execute(count_query, shop_names)
                total = cursor.fetchone()[0]

                products = []
                for row in rows:
                    prod = dict(row)
                    # 处理图片路径 - 直接使用预查询的image_indices
                    if prod.get('image_indices'):
                        image_indices = [int(idx) for idx in prod['image_indices'].split(',') if idx]
                        prod['images'] = [f"/api/image/{prod['id']}/{idx}" for idx in image_indices]
                    else:
                        prod['images'] = []

                    # 格式化字段名以兼容前端
                    prod['weidianUrl'] = prod.get('product_url')
                    prod['englishTitle'] = prod.get('english_title') or ''
                    prod['cnfansUrl'] = prod.get('cnfans_url') or ''
                    prod['acbuyUrl'] = prod.get('acbuy_url') or ''
                    prod['createdAt'] = prod.get('created_at')
                    prod['autoReplyEnabled'] = prod.get('ruleEnabled', True)
                    prod['shopName'] = prod.get('shop_name') or '未知店铺'
                    prod['customReplyText'] = prod.get('custom_reply_text') or ''
                    # 解析自定义回复图片索引
                    try:
                        custom_reply_images = prod.get('custom_reply_images')
                        if custom_reply_images:
                            prod['selectedImageIndexes'] = json.loads(custom_reply_images)
                        else:
                            prod['selectedImageIndexes'] = []
                    except:
                        prod['selectedImageIndexes'] = []

                    # 提取微店ID
                    try:
                        import re
                        m = re.search(r'itemID=(\d+)', prod.get('product_url') or '')
                        prod['weidianId'] = m.group(1) if m else ''
                    except:
                        prod['weidianId'] = ''

                    products.append(prod)

                return {'products': products, 'total': total}

        except Exception as e:
            print(f"DEBUG: Exception in get_products_by_user_shops: {type(e).__name__}: {e}")
            import traceback
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")
            logger.error("获取用户商品失败: %s", str(e))
            return {'products': [], 'total': 0}

    def get_global_reply_config(self) -> Dict[str, float]:
        """获取全局回复延迟配置"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT min_delay, max_delay FROM global_reply_config WHERE id = 1')
                row = cursor.fetchone()
                if row:
                    return {'min_delay': row[0], 'max_delay': row[1]}
                return {'min_delay': 3.0, 'max_delay': 8.0}  # 默认值
        except Exception as e:
            logger.error(f"获取全局回复配置失败: {e}")
            return {'min_delay': 3.0, 'max_delay': 8.0}

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
                    SELECT discord_similarity_threshold, global_reply_min_delay, global_reply_max_delay,
                           user_blacklist, keyword_filters
                    FROM user_settings WHERE user_id = ?
                ''', (user_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'discord_similarity_threshold': row[0] or 0.6,
                        'global_reply_min_delay': row[1] or 3.0,
                        'global_reply_max_delay': row[2] or 8.0,
                        'user_blacklist': row[3] or '',
                        'keyword_filters': row[4] or '',
                    }
                # 如果用户没有设置，返回默认值
                return {
                    'discord_similarity_threshold': 0.6,
                    'global_reply_min_delay': 3.0,
                    'global_reply_max_delay': 8.0,
                    'user_blacklist': '',
                    'keyword_filters': '',
                }
        except Exception as e:
            logger.error(f"获取用户设置失败: {e}")
            return {
                'download_threads': 4,
                'feature_extract_threads': 4,
                'discord_similarity_threshold': 0.6,
                'global_reply_min_delay': 3.0,
                'global_reply_max_delay': 8.0,
                'user_blacklist': '',
                'keyword_filters': '',
            }

    def update_user_settings(self, user_id: int, discord_similarity_threshold: float = None,
                           global_reply_min_delay: float = None, global_reply_max_delay: float = None,
                           user_blacklist: str = None, keyword_filters: str = None) -> bool:
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

                    if update_fields:
                        update_fields.append('updated_at = CURRENT_TIMESTAMP')
                        sql = f'UPDATE user_settings SET {", ".join(update_fields)} WHERE user_id = ?'
                        params.append(user_id)
                        cursor.execute(sql, params)
                else:
                    # 插入新设置
                    cursor.execute('''
                        INSERT INTO user_settings
                        (user_id, discord_similarity_threshold, global_reply_min_delay, global_reply_max_delay,
                         user_blacklist, keyword_filters)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        user_id,
                        discord_similarity_threshold or 0.6,
                        global_reply_min_delay or 3.0,
                        global_reply_max_delay or 8.0,
                        user_blacklist or '',
                        keyword_filters or ''
                    ))

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户设置失败: {e}")
            return False

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

    def add_shop(self, shop_id: str, name: str) -> bool:
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
                    return {
                        'id': row[0],
                        'is_scraping': bool(row[1]),
                        'stop_signal': bool(row[2]),
                        'current_shop_id': row[3],
                        'total': row[4] or 0,
                        'processed': row[5] or 0,
                        'success': row[6] or 0,
                        'progress': row[7] or 0.0,
                        'message': row[8] or '等待开始...',
                        'completed': bool(row[9]),
                        'thread_id': row[10],
                        'updated_at': row[11]
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
                    elif key in ['total', 'processed', 'success']:
                        fields.append(f'{key} = ?')
                        values.append(int(value) if value is not None else 0)
                    elif key == 'progress':
                        fields.append(f'{key} = ?')
                        values.append(float(value) if value is not None else 0.0)
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
                'progress': 0.0,
                'message': '重置失败',
                'completed': False,
                'thread_id': None,
                'updated_at': None
            }

# 全局数据库实例
db = Database()
